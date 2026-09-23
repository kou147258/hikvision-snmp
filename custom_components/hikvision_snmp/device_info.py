"""Identify a Hikvision device and build its DeviceInfo descriptor."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, HIKVISION_PRIVATE_MIB_ROOT, MANUFACTURER, SYSTEM_OIDS
from .helpers import decode_octet_string, decode_walk_results
from .snmp_client import HikvisionSnmpClient


async def async_identify_device(client: HikvisionSnmpClient) -> dict[str, Any]:
    """GETBULK the system subtree and return a flat dict of scalar values."""
    raw = await client.walk(f"{HIKVISION_PRIVATE_MIB_ROOT}.1", max_repetitions=10)
    decoded = decode_walk_results(raw, f"{HIKVISION_PRIVATE_MIB_ROOT}.1", SYSTEM_OIDS)
    # decoded is {metric_key: {"0": value}}. Flatten to {metric_key: value}.
    out: dict[str, Any] = {}
    for key in SYSTEM_OIDS:
        entry = decoded.get(key, {})
        if not entry:
            out[key] = None
            continue
        out[key] = entry.get("0") or next(iter(entry.values()), None)
    return out


def build_device_info(
    entry_id: str, host: str, identification: dict[str, Any], name: str
) -> DeviceInfo:
    """Build an HA DeviceInfo for a Hikvision device."""
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