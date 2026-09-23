"""Binary sensor platform for Hikvision SNMP."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HikvisionDataUpdateCoordinator
from .helpers import parse_int


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HikvisionDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_config_entry_first_refresh()
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
    """Device online state (Hikvision OID .24.0: INTEGER 1=online, 0=offline).

    Falls back to ``coordinator.last_update_success`` when the OID is absent
    on firmware variants that don't expose it.
    """

    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: HikvisionDataUpdateCoordinator, entry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_online"

    @property
    def is_on(self) -> bool | None:
        # Prefer the device-reported OID if present
        oid_val = parse_int(
            self.coordinator.data.get("identification", {}).get("online", {}).get("0")
        ) if self.coordinator.data else None
        if oid_val is not None:
            return oid_val == 1
        # Fallback: coordinator last-update success
        return self.coordinator.last_update_success


class HikvisionRecordingBinarySensor(_Base):
    """Recording state for the device.

    On standalone IPCs, derived from OID .25.0 (INTEGER). On NVRs, derived
    from any channel in the channel table having recording=1.
    """

    _attr_name = "Recording"

    def __init__(
        self, coordinator: HikvisionDataUpdateCoordinator, entry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_recording"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        # NVR-style: any channel in channel table
        rec = self.coordinator.data.get("channels", {}).get("recording", {})
        if rec:
            return any(parse_int(v) == 1 for v in rec.values())
        # IPC-style: device-level recording OID
        oid_val = parse_int(
            self.coordinator.data.get("identification", {}).get("recording", {}).get("0")
        )
        if oid_val is not None:
            return oid_val == 1
        return None