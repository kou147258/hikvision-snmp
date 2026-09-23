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
    """Device reachability derived from coordinator success."""

    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self, coordinator: HikvisionDataUpdateCoordinator, entry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_online"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.last_update_success


class HikvisionRecordingBinarySensor(_Base):
    """True if any channel is currently recording."""

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
        rec = self.coordinator.data.get("channels", {}).get("recording", {})
        return any(parse_int(v) == 1 for v in rec.values())