"""DataUpdateCoordinator that polls a Hikvision device every scan_interval.

Supports both Hikvision IPCs (enterprise 39165) and NVRs (enterprise 50001).
The vendor is determined once at setup via ``async_identify_device`` and
stored on the coordinator instance; all walks use the corresponding MIB root.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BULK_MAX_REPETITIONS,
    CHANNEL_OIDS,
    DISK_OIDS,
    HIKVISION_IPC_MIB_ROOT,
    HIKVISION_NVR_MIB_ROOT,
    NVR_CHANNEL_OIDS,
    NVR_SYSTEM_OIDS,
    SYSTEM_OIDS,
    VENDOR_HIKVISION_IPC,
    VENDOR_HIKVISION_NVR,
)
from .helpers import decode_walk_results
from .snmp_client import HikvisionSnmpClient, HikvisionSnmpError

_LOGGER = logging.getLogger(__name__)


class HikvisionDataUpdateCoordinator(DataUpdateCoordinator):
    """Per-device coordinator; vendor-aware."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: HikvisionSnmpClient,
        scan_interval: int,
        vendor: str,
        identification: dict[str, Any] | None = None,
        channel_count: int = 0,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{client.host}_hikvision",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = client
        self._vendor = vendor
        self._identification = identification or {}
        self._channel_count = channel_count
        self.device_info: Any = None  # set by __init__.py after construction

    @property
    def client(self) -> HikvisionSnmpClient:
        return self._client

    @property
    def vendor(self) -> str:
        return self._vendor

    @property
    def identification(self) -> dict[str, Any]:
        return self._identification

    @property
    def channel_count(self) -> int:
        return self._channel_count

    def _mib_root(self) -> str:
        return HIKVISION_NVR_MIB_ROOT if self._vendor == VENDOR_HIKVISION_NVR else HIKVISION_IPC_MIB_ROOT

    def _system_oids(self) -> dict[str, str]:
        return NVR_SYSTEM_OIDS if self._vendor == VENDOR_HIKVISION_NVR else SYSTEM_OIDS

    def _channel_oids(self) -> dict[str, str] | None:
        if self._vendor == VENDOR_HIKVISION_NVR:
            return NVR_CHANNEL_OIDS
        return CHANNEL_OIDS

    async def _async_update_data(self) -> dict[str, Any]:
        mib_root = self._mib_root()
        sys_root = f"{mib_root}.1"
        sys_oids = self._system_oids()

        # Pass known leaf indices so walk() can patch missing values with single GETs.
        sys_raw = await self._client.walk(
            sys_root,
            max_repetitions=BULK_MAX_REPETITIONS,
            known_leaves=list(sys_oids.values()),
        )

        # Channel / disk subtree walks — best-effort, may not be exposed.
        channel_oids = self._channel_oids()
        ch_root: str | None = None
        ch_raw: list[tuple[str, Any]] = []
        if channel_oids:
            # NVR channels live under .50001.1.241.1 (a sub-table), not .2
            if self._vendor == VENDOR_HIKVISION_NVR:
                ch_root = f"{mib_root}.1.241.1"
            else:
                ch_root = f"{mib_root}.2"
            try:
                ch_raw = await self._client.walk(ch_root, max_repetitions=BULK_MAX_REPETITIONS)
            except HikvisionSnmpError as exc:
                _LOGGER.debug("channel walk failed: %s", exc)

        # Disk walk — IPC only (NVR doesn't have a separate disk subtree in
        # the 50001 MIB; disk data is rolled into the channel table at .241).
        disk_raw: list[tuple[str, Any]] = []
        if self._vendor == VENDOR_HIKVISION_IPC:
            disk_root = f"{mib_root}.3"
            try:
                disk_raw = await self._client.walk(disk_root, max_repetitions=BULK_MAX_REPETITIONS)
            except HikvisionSnmpError as exc:
                _LOGGER.debug("disk walk failed: %s", exc)
            disks_decoded = decode_walk_results(disk_raw, disk_root, DISK_OIDS)
        else:
            disks_decoded = {}

        return {
            "identification": decode_walk_results(sys_raw, sys_root, sys_oids),
            "channels": decode_walk_results(ch_raw, ch_root, channel_oids) if ch_root else {},
            "disks": disks_decoded,
        }