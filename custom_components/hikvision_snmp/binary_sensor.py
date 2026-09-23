"""Binary sensor platform for Hikvision SNMP.

Two product lines are supported:

- **IPC / PTZ (enterprise 39165)** — exposes explicit ``.24.0`` (online,
  INTEGER 1/0) and ``.25.0`` (recording, INTEGER 1/0) scalars. Recording
  can additionally be inferred from any per-channel ``recording`` leaf.
- **NVR (enterprise 50001)** — no ``.24`` / ``.25`` scalars. Online is
  derived from ``coordinator.last_update_success`` (the coordinator is
  considered the source of truth for reachability). Recording is derived
  from any NVR channel having ``motion_flag > 0``, OR from the device-level
  ``active_state`` (``identification.active_state`` == 1).
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VENDOR_HIKVISION_NVR
from .coordinator import HikvisionDataUpdateCoordinator
from .helpers import parse_int

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HikvisionDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # v0.1.16 — same 15 s wait_for guard as sensor.py. See that file's
    # comment for the full rationale; the binary_sensor platform's first
    # refresh was hitting HA's entry-setup timeout on slow V5.x NVRs
    # with many channels.
    try:
        await asyncio.wait_for(
            coordinator.async_config_entry_first_refresh(),
            timeout=15,
        )
    except asyncio.TimeoutError:
        _LOGGER.warning(
            "Initial poll did not complete within 15 s for %s; "
            "binary sensors will become available once the coordinator recovers",
            coordinator.client.host,
        )
    except Exception:  # noqa: BLE001
        raise

    async_add_entities([
        HikvisionOnlineBinarySensor(coordinator, entry),
        HikvisionRecordingBinarySensor(coordinator, entry),
    ])


class _Base(
    CoordinatorEntity[HikvisionDataUpdateCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: HikvisionDataUpdateCoordinator, entry
    ) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info


class HikvisionOnlineBinarySensor(_Base):
    """Device online state.

    Resolution order:
        1. IPC scalar ``.24.0`` (INTEGER 1 = online, 0 = offline).
        2. NVR ``active_state`` (``identification.active_state`` == 1).
        3. ``coordinator.last_update_success`` as a final fallback.
    """

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: HikvisionDataUpdateCoordinator, entry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_online"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        # 1. IPC .24.0
        oid_val = parse_int(
            self.coordinator.data.get("identification", {}).get("online", {}).get("0")
        )
        if oid_val is not None:
            return oid_val == 1
        # 2. NVR active_state — 1 means at least one channel is alive
        if self.coordinator.vendor == VENDOR_HIKVISION_NVR:
            nvr_state = parse_int(
                self.coordinator.data.get("identification", {}).get("active_state", {}).get("0")
            )
            if nvr_state is not None:
                return nvr_state == 1
        # 3. Coordinator heartbeat as final fallback
        return self.coordinator.last_update_success


class HikvisionRecordingBinarySensor(_Base):
    """Recording state for the device.

    Resolution order:
        1. IPC scalar ``.25.0`` (INTEGER 1/0).
        2. NVR: any channel with ``motion_flag > 0`` in the channel table.
        3. NVR: device-level ``active_state`` == 1 (at least one channel
           is active — not strictly "recording" but is the closest device-
           level indicator available in the 50001 MIB).
    """

    _attr_translation_key = "recording"

    def __init__(
        self, coordinator: HikvisionDataUpdateCoordinator, entry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_recording"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None

        # IPC standalone camera: any per-channel recording flag
        ipc_ch_rec = self.coordinator.data.get("channels", {}).get("recording", {})
        if ipc_ch_rec:
            return any(parse_int(v) == 1 for v in ipc_ch_rec.values())

        # IPC device-level scalar
        oid_val = parse_int(
            self.coordinator.data.get("identification", {}).get("recording", {}).get("0")
        )
        if oid_val is not None:
            return oid_val == 1

        # NVR: any channel with motion_flag > 0
        if self.coordinator.vendor == VENDOR_HIKVISION_NVR:
            nvr_motion = self.coordinator.data.get("channels", {}).get("motion_flag", {})
            if nvr_motion:
                return any((parse_int(v) or 0) > 0 for v in nvr_motion.values())
            # NVR: device-level active_state
            active = parse_int(
                self.coordinator.data.get("identification", {}).get("active_state", {}).get("0")
            )
            if active is not None:
                return active == 1

        return None
