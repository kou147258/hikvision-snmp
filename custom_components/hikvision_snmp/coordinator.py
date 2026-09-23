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
        # On V5.x firmware we walk the system subtree which lives at
        # ``.1.3.6.1.4.1.39165.1``. NVRs additionally publish channel /
        # disk subtrees at ``.2`` / ``.3``; we walk those too and let
        # the per-channel / per-disk entity code path decide what to do.
        sys_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.1"
        ch_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.2"
        disk_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.3"

        # Pass known leaf indices so walk() can patch missing values with single GETs.
        sys_raw = await self._client.walk(
            sys_root, max_repetitions=BULK_MAX_REPETITIONS, known_leaves=list(SYSTEM_OIDS.keys())
        )

        # Channel / disk walks are best-effort — many devices (notably
        # standalone IPCs) don't expose those subtrees. Failures are
        # silently ignored; the per-disk / per-channel sensor code paths
        # simply see empty dicts.
        ch_raw: list[tuple[str, Any]] = []
        disk_raw: list[tuple[str, Any]] = []
        try:
            ch_raw = await self._client.walk(ch_root, max_repetitions=BULK_MAX_REPETITIONS)
        except HikvisionSnmpError as exc:
            _LOGGER.debug("channel walk failed (likely no NVR channels): %s", exc)
        try:
            disk_raw = await self._client.walk(disk_root, max_repetitions=BULK_MAX_REPETITIONS)
        except HikvisionSnmpError as exc:
            _LOGGER.debug("disk walk failed (likely no NVR disks): %s", exc)

        return {
            "identification": decode_walk_results(sys_raw, sys_root, SYSTEM_OIDS),
            "channels": decode_walk_results(ch_raw, ch_root, CHANNEL_OIDS),
            "disks": decode_walk_results(disk_raw, disk_root, DISK_OIDS),
        }