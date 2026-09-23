"""Identify a Hikvision device and build its DeviceInfo descriptor."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    HIKVISION_PRIVATE_MIB_ROOT,
    MANUFACTURER,
    SYSTEM_OIDS,
)
from .helpers import decode_octet_string, decode_walk_results, parse_int
from .snmp_client import HikvisionSnmpClient


async def async_identify_device(client: HikvisionSnmpClient) -> dict[str, Any]:
    """GETBULK the system subtree and return a flat dict of scalar values."""
    raw = await client.walk(f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1", max_repetitions=10)
    decoded = decode_walk_results(raw, f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1", SYSTEM_OIDS)
    scalar_keys = [
        "model", "device_name", "firmware", "device_type_code",
        "uptime", "cpu", "memory", "temperature",
    ]
    out: dict[str, Any] = {}
    for key in scalar_keys:
        entry = decoded.get(key, {})
        if not entry:
            out[key] = None
            continue
        # System scalars are typically instance "0"; fall back to first value.
        raw_value = entry.get("0") or next(iter(entry.values()), None)
        if key in ("model", "device_name", "firmware"):
            out[key] = decode_octet_string(raw_value)
        else:
            out[key] = parse_int(raw_value)
    return out


def build_device_info(
    entry_id: str, host: str, identification: dict[str, Any], name: str
) -> DeviceInfo:
    """Build an HA DeviceInfo for a Hikvision device."""
    model = identification.get("model") or "Hikvision Device"
    firmware = identification.get("firmware")
    return DeviceInfo(
        identifiers={(DOMAIN, host)},
        manufacturer=MANUFACTURER,
        model=model,
        name=name,
        sw_version=firmware,
        configuration_url=f"http://{host}",
    )