"""Hikvision SNMP integration entry point."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AUTH_KEY,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_DEVICE_TYPE,
    CONF_PRIVACY_KEY,
    CONF_PRIVACY_PROTOCOL,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import HikvisionDataUpdateCoordinator
from .device_info import async_identify_device, build_device_info
from .snmp_client import HikvisionSnmpClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hikvision SNMP from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    data = entry.data
    options = entry.options
    scan_interval = options.get(
        CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    version = data.get(CONF_VERSION, "v2c")
    if version == "v2c":
        auth = {"community": data.get(CONF_COMMUNITY, "")}
    else:
        auth = {
            "username": data.get(CONF_USERNAME, ""),
            "auth_protocol": data.get(CONF_AUTH_PROTOCOL, "SHA"),
            "auth_key": data.get(CONF_AUTH_KEY, ""),
            "privacy_protocol": data.get(CONF_PRIVACY_PROTOCOL, "AES128"),
            "priv_key": data.get(CONF_PRIVACY_KEY, ""),
        }

    # Wrap client construction in try/except — ``UdpTransportTarget`` raises
    # ``socket.gaierror`` for unresolvable hostnames at construction time
    # (not at request time), which is not in HikvisionSnmpError's hierarchy
    # and would otherwise turn into an unrecoverable entry-setup failure.
    try:
        client = HikvisionSnmpClient(
            host=data[CONF_HOST],
            port=data.get(CONF_PORT, 161),
            version=version,
            auth=auth,
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error(
            "Failed to construct SNMP client for %s: %s", data.get(CONF_HOST), exc
        )
        return False

    try:
        vendor, identification, channel_counts = await async_identify_device(client)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error("Failed to identify device %s: %s", data[CONF_HOST], exc)
        await client.close()
        return False
    channel_count = channel_counts.get("channels", 0)
    device_info = build_device_info(
        entry.entry_id,
        data[CONF_HOST],
        vendor,
        identification,
        data.get(CONF_NAME, f"Hikvision {data[CONF_HOST]}"),
    )

    coordinator = HikvisionDataUpdateCoordinator(
        hass,
        client,
        scan_interval=scan_interval,
        vendor=vendor,
        identification=identification,
        channel_count=channel_count,
    )
    coordinator.device_info = device_info

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HikvisionDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.close()
    return unload_ok