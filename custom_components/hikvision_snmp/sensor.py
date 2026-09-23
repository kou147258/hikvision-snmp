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
    UnitOfDataSize,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HikvisionDataUpdateCoordinator
from .helpers import decode_octet_string, parse_int, parse_uptime


@dataclass(frozen=True)
class HikvisionSensorDescription(SensorEntityDescription):
    """Description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], Any] = lambda _: None


# ---- Static sensors ----

SENSORS: tuple[HikvisionSensorDescription, ...] = (
    HikvisionSensorDescription(
        key="cpu_usage",
        name="CPU Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_int(d.get("identification", {}).get("cpu", {}).get("0")),
    ),
    HikvisionSensorDescription(
        key="memory_usage",
        name="Memory Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_int(d.get("identification", {}).get("memory", {}).get("0")),
    ),
    HikvisionSensorDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_int(d.get("identification", {}).get("temperature", {}).get("0")),
    ),
    HikvisionSensorDescription(
        key="uptime",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: int(parse_uptime(
            parse_int(d.get("identification", {}).get("uptime", {}).get("0"))
        ).total_seconds()),
    ),
    HikvisionSensorDescription(
        key="firmware_version",
        name="Firmware Version",
        value_fn=lambda d: decode_octet_string(
            d.get("identification", {}).get("firmware", {}).get("0")
        ),
    ),
    HikvisionSensorDescription(
        key="device_name",
        name="Device Name",
        value_fn=lambda d: decode_octet_string(
            d.get("identification", {}).get("device_name", {}).get("0")
        ),
    ),
    HikvisionSensorDescription(
        key="model",
        name="Model",
        value_fn=lambda d: decode_octet_string(
            d.get("identification", {}).get("model", {}).get("0")
        ),
    ),
    HikvisionSensorDescription(
        key="channels_total",
        name="Channels Total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.get("channels", {}).get("name", {})),
    ),
    HikvisionSensorDescription(
        key="channels_online",
        name="Channels Online",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(
            1 for v in d.get("channels", {}).get("online", {}).values()
            if parse_int(v) == 1
        ),
    ),
    HikvisionSensorDescription(
        key="channels_recording",
        name="Channels Recording",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(
            1 for v in d.get("channels", {}).get("recording", {}).values()
            if parse_int(v) == 1
        ),
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

    for disk_idx in sorted(data.get("disks", {}).get("name", {}).keys()):
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "name", "Disk Name", None))
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "capacity", "Capacity", UnitOfDataSize.GIGABYTES))
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "free", "Free", UnitOfDataSize.GIGABYTES))
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "temperature", "Temperature", UnitOfTemperature.CELSIUS))

    for ch_idx in sorted(data.get("channels", {}).get("name", {}).keys(), key=lambda x: int(x)):
        entities.append(HikvisionChannelSensor(coordinator, entry, ch_idx, "name", "Name", None))
        entities.append(HikvisionChannelSensor(coordinator, entry, ch_idx, "bitrate", "Bitrate", UnitOfInformation.KILOBITS_PER_SECOND))

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
            mb = parse_int(raw)
            return round(mb / 1024, 2) if mb is not None else None
        if self._metric_key == "temperature":
            return parse_int(raw)
        return None


class HikvisionChannelSensor(_DynamicTableSensor):
    """Per-channel sensor."""

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