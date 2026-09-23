"""Sensor platform for Hikvision SNMP."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HikvisionDataUpdateCoordinator
from .helpers import decode_octet_string, parse_int, parse_value_with_unit


@dataclass(frozen=True)
class HikvisionSensorDescription(SensorEntityDescription):
    """Description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], Any] = lambda _: None


def _scalar(metric_key: str):
    """Build a value extractor that reads a scalar metric from coordinator data."""
    def _fn(data: dict[str, Any]) -> Any:
        return data.get("identification", {}).get(metric_key, {}).get("0")
    return _fn


# ---- Static sensors for Hikvision V5.x IPC firmware ----

SENSORS: tuple[HikvisionSensorDescription, ...] = (
    HikvisionSensorDescription(
        key="model",
        name="Model",
        icon="mdi:information-outline",
        value_fn=lambda d: decode_octet_string(_scalar("model")(d)),
    ),
    HikvisionSensorDescription(
        key="device_name",
        name="Device Name",
        icon="mdi:tag-outline",
        value_fn=lambda d: decode_octet_string(_scalar("device_name")(d)),
    ),
    HikvisionSensorDescription(
        key="firmware",
        name="Firmware Version",
        icon="mdi:chip",
        value_fn=lambda d: decode_octet_string(_scalar("firmware")(d)),
    ),
    HikvisionSensorDescription(
        key="mac",
        name="MAC Address",
        icon="mdi:network",
        value_fn=lambda d: decode_octet_string(_scalar("mac")(d)),
    ),
    HikvisionSensorDescription(
        key="manufacturer",
        name="Manufacturer",
        icon="mdi:factory",
        value_fn=lambda d: decode_octet_string(_scalar("manufacturer")(d)),
    ),
    HikvisionSensorDescription(
        key="cpu",
        name="CPU Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("cpu")(d))[0],
    ),
    HikvisionSensorDescription(
        key="memory_used_pct",
        name="Memory Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("memory_used_pct")(d))[0],
    ),
    HikvisionSensorDescription(
        key="memory_total",
        name="Memory Total",
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("memory_total")(d))[0],
    ),
    HikvisionSensorDescription(
        key="storage_total",
        name="Storage Total",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("storage_total")(d))[0],
    ),
    HikvisionSensorDescription(
        key="storage_used_pct",
        name="Storage Used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("storage_used_pct")(d))[0],
    ),
    HikvisionSensorDescription(
        key="uptime_seconds",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: parse_int(_scalar("uptime_seconds")(d)),
    ),
    HikvisionSensorDescription(
        key="device_time",
        name="Device Time",
        icon="mdi:clock-outline",
        value_fn=lambda d: decode_octet_string(_scalar("device_time")(d)),
    ),
    HikvisionSensorDescription(
        key="network_type",
        name="Network Type",
        icon="mdi:lan",
        value_fn=lambda d: decode_octet_string(_scalar("network_type")(d)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator: HikvisionDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    await coordinator.async_config_entry_first_refresh()
    data = coordinator.data or {}

    entities: list[SensorEntity] = []

    for desc in SENSORS:
        entities.append(HikvisionSensor(coordinator, entry, desc))

    # Per-channel sensors (NVRs that publish the channel subtree)
    for ch_idx in sorted(data.get("channels", {}).get("name", {}).keys(), key=lambda x: int(x)):
        entities.append(HikvisionChannelSensor(coordinator, entry, ch_idx, "name", "Name", None))
        entities.append(HikvisionChannelSensor(coordinator, entry, ch_idx, "bitrate", "Bitrate", UnitOfInformation.KILOBITS_PER_SECOND))

    # Per-disk sensors (NVRs with HDD arrays)
    for disk_idx in sorted(data.get("disks", {}).get("name", {}).keys()):
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "name", "Disk Name", None))
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "capacity", "Disk Capacity", UnitOfInformation.GIGABYTES))

    async_add_entities(entities)


class HikvisionSensor(
    CoordinatorEntity[HikvisionDataUpdateCoordinator], SensorEntity
):
    """Static sensor entity."""

    _attr_has_entity_name = True
    entity_description: HikvisionSensorDescription

    def __init__(
        self,
        coordinator: HikvisionDataUpdateCoordinator,
        entry,
        description: HikvisionSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class _DynamicTableSensor(
    CoordinatorEntity[HikvisionDataUpdateCoordinator], SensorEntity
):
    """Base for per-row sensors (disk / channel)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HikvisionDataUpdateCoordinator,
        entry,
        idx: str,
        metric_key: str,
        name_suffix: str,
        unit: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._metric_key = metric_key
        self._attr_name = name_suffix
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = f"{entry.entry_id}_{self._table_name}_{idx}_{metric_key}"
        self._attr_device_info = coordinator.device_info

    @property
    def _table_name(self) -> str:
        raise NotImplementedError

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        table = self.coordinator.data.get(self._table_name, {})
        raw = table.get(self._metric_key, {}).get(self._idx)
        return self._decode(raw)

    def _decode(self, raw: Any) -> Any:
        raise NotImplementedError


class HikvisionDiskSensor(_DynamicTableSensor):
    """Per-disk sensor (NVR HDD or IPC SD card)."""

    @property
    def _table_name(self) -> str:
        return "disks"

    def _decode(self, raw: Any) -> Any:
        if raw is None:
            return None
        if self._metric_key == "name":
            return decode_octet_string(raw)
        if self._metric_key in ("capacity", "free"):
            num, _ = parse_value_with_unit(raw)
            if num is None:
                return None
            # Heuristic: if value < 1e6, treat as MB; if larger, as GB
            if num < 1_000_000:
                return round(num, 2)
            return round(num, 2)
        return None


class HikvisionChannelSensor(_DynamicTableSensor):
    """Per-channel sensor (NVR only)."""

    @property
    def _table_name(self) -> str:
        return "channels"

    def _decode(self, raw: Any) -> Any:
        if raw is None:
            return None
        if self._metric_key == "name":
            return decode_octet_string(raw)
        if self._metric_key == "bitrate":
            return parse_int(raw)
        return None