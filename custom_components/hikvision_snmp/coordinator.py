"""DataUpdateCoordinator that polls a Hikvision device every scan_interval."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BULK_MAX_REPETITIONS,
    CHANNEL_OIDS,
    DEFAULT_SCAN_INTERVAL,
    DISK_OIDS,
    HIKVISION_PRIVATE_MIB_ROOT,
    SYSTEM_OIDS,
)
from .helpers import decode_walk_results
from .snmp_client import HikvisionSnmpClient, HikvisionSnmpError

_LOGGER = logging.getLogger(__name__)


class HikvisionDataUpdateCoordinator(DataUpdateCoordinator):
    """Per-device coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: HikvisionSnmpClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        identification: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{client.host}_hikvision",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = client
        self._identification = identification or {}
        self.device_info: Any = None  # set by __init__.py after construction

    @property
    def client(self) -> HikvisionSnmpClient:
        return self._client

    @property
    def identification(self) -> dict[str, Any]:
        return self._identification

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            sys_raw = await self._client.walk(
                f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1",
                max_repetitions=BULK_MAX_REPETITIONS,
            )
            ch_raw = await self._client.walk(
                f"{HIKVISION_PRIVATE_MIB_ROOT}.1.2.1",
                max_repetitions=BULK_MAX_REPETITIONS,
            )
            disk_raw = await self._client.walk(
                f"{HIKVISION_PRIVATE_MIB_ROOT}.1.3.1",
                max_repetitions=BULK_MAX_REPETITIONS,
            )
        except HikvisionSnmpError as exc:
            raise UpdateFailed(f"SNMP walk failed: {exc}") from exc

        sys_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1"
        ch_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.2.1"
        disk_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.3.1"

        sys_decoded = decode_walk_results(sys_raw, sys_root, SYSTEM_OIDS)

        return {
            "identification": sys_decoded,
            "channels": decode_walk_results(ch_raw, ch_root, CHANNEL_OIDS),
            "disks": decode_walk_results(disk_raw, disk_root, DISK_OIDS),
        }