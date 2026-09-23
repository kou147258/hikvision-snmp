"""Identify a Hikvision device and build its DeviceInfo descriptor.

Supports two enterprise OIDs (Hikvision uses one or the other depending on
product line). Auto-detection: try IPC root first, fall back to NVR root.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    HIKVISION_IPC_MIB_ROOT,
    HIKVISION_NVR_MIB_ROOT,
    MANUFACTURER,
    NVR_SYSTEM_OIDS,
    SYSTEM_OIDS,
    VENDOR_HIKVISION_IPC,
    VENDOR_HIKVISION_NVR,
)
from .helpers import decode_octet_string, decode_walk_results, parse_int
from .snmp_client import HikvisionSnmpClient


async def _walk_vendor_subtree(
    client: HikvisionSnmpClient, mib_root: str, oid_map: dict[str, str]
) -> dict[str, Any]:
    """GETBULK-walk a vendor's system subtree and return flat scalar dict."""
    raw = await client.walk(f"{mib_root}.1", max_repetitions=10)
    decoded = decode_walk_results(raw, f"{mib_root}.1", oid_map)
    out: dict[str, Any] = {}
    for key in oid_map:
        entry = decoded.get(key, {})
        if not entry:
            out[key] = None
            continue
        raw_value = entry.get("0") or next(iter(entry.values()), None)
        out[key] = raw_value
    return out


async def _probe_sys_descr(client: HikvisionSnmpClient, mib_root: str) -> str | None:
    """Single GET for vendor's model-equivalent scalar. Returns decoded string or None.

    IPC exposes model at ``.39165.1.1.0``; NVR exposes serial at ``.50001.1.3.0``
    (the closest thing to a sysDescr equivalent on the 50001 MIB). If the
    GET returns a non-empty value, the vendor is considered reachable.
    """
    if mib_root == HIKVISION_NVR_MIB_ROOT:
        oid = f"{HIKVISION_NVR_MIB_ROOT}.1.3.0"
    else:
        oid = f"{HIKVISION_IPC_MIB_ROOT}.1.1.0"
    try:
        val = await client.get(oid)
    except Exception:  # noqa: BLE001
        return None
    if val is None:
        return None
    return str(val)


async def async_identify_device(client: HikvisionSnmpClient) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Identify vendor + collect identification data.

    Returns ``(vendor, identification_dict, channel_count_dict)``:
    - vendor: ``VENDOR_HIKVISION_IPC`` or ``VENDOR_HIKVISION_NVR``
    - identification: {metric_key: scalar_value} for SYSTEM_OIDS or NVR_SYSTEM_OIDS
    - channel_count_dict: {table_name: count} — empty for IPC, has ``"channels"``
      for NVR if `.240.0` was readable.
    """
    # Try IPC first (most common — IP cameras + PTZs)
    ipc_descr = await _probe_sys_descr(client, HIKVISION_IPC_MIB_ROOT)
    if ipc_descr:
        identification = await _walk_vendor_subtree(client, HIKVISION_IPC_MIB_ROOT, SYSTEM_OIDS)
        return VENDOR_HIKVISION_IPC, identification, {}

    # Fall back to NVR (enterprise 50001)
    nvr_descr = await _probe_sys_descr(client, HIKVISION_NVR_MIB_ROOT)
    if nvr_descr:
        identification = await _walk_vendor_subtree(client, HIKVISION_NVR_MIB_ROOT, NVR_SYSTEM_OIDS)
        channel_count = parse_int(identification.get("channel_count"))
        return VENDOR_HIKVISION_NVR, identification, (
            {"channels": channel_count} if channel_count else {}
        )

    # Neither vendor responded — caller will see empty data and raise
    return VENDOR_HIKVISION_IPC, {}, {}


def build_device_info(
    entry_id: str,
    host: str,
    vendor: str,
    identification: dict[str, Any],
    name: str,
) -> DeviceInfo:
    """Build HA DeviceInfo.

    For Hikvision IPC (enterprise 39165), model/firmware/mac are read from
    scalar leaves. For NVR (enterprise 50001), serial/model_code are used.
    """
    if vendor == VENDOR_HIKVISION_NVR:
        # NVR identification fields
        serial = decode_octet_string(identification.get("serial"))
        ip = identification.get("ip_addr")
        ip_str = str(ip) if ip else None
        model = f"Hikvision NVR ({serial or 'model 8000'})"
        sw_version = None  # NVR firmware version is not exposed via this MIB subtree
        # Use serial as the unique-id suffix so the same NVR isn't duplicated
        return DeviceInfo(
            identifiers={(DOMAIN, host)},
            manufacturer=MANUFACTURER,
            model=model,
            name=name,
            serial_number=serial,
            configuration_url=f"http://{ip_str or host}",
        )

    # IPC identification fields
    model = decode_octet_string(identification.get("model")) or "Hikvision Device"
    firmware = decode_octet_string(identification.get("firmware"))
    mac = decode_octet_string(identification.get("mac"))
    return DeviceInfo(
        identifiers={(DOMAIN, host)},
        manufacturer=MANUFACTURER,
        model=model,
        name=name,
        sw_version=firmware,
        serial_number=mac,
        configuration_url=f"http://{host}",
    )