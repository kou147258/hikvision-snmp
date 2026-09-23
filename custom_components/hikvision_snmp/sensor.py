"""Sensor platform for Hikvision SNMP.

Two product lines are supported; the coordinator's ``vendor`` attribute picks
which set of scalar sensors to expose:

- ``VENDOR_HIKVISION_IPC`` — IPC / PTZ product line (enterprise 39165).
  Exposes model/firmware/MAC/CPU/memory/storage/uptime etc. under
  ``.39165.1.<N>.0``.
- ``VENDOR_HIKVISION_NVR`` — NVR / enterprise recorder line (enterprise 50001).
  Exposes serial/cpu_freq/temperature/channels_total/active counters under
  ``.50001.1.<N>.0``, plus per-channel scalars under ``.50001.1.241.1.<col>.<row>.0``
  (label, motion flag, bytes used, etc.).
"""

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
    UnitOfFrequency,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    VENDOR_HIKVISION_IPC,
    VENDOR_HIKVISION_NVR,
)
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


# ---- IPC / PTZ scalar sensors (enterprise 39165) ----

IPC_SENSORS: tuple[HikvisionSensorDescription, ...] = (
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


# ---- NVR scalar sensors (enterprise 50001) ----

NVR_SENSORS: tuple[HikvisionSensorDescription, ...] = (
    HikvisionSensorDescription(
        key="serial",
        name="Serial Number",
        icon="mdi:barcode",
        value_fn=lambda d: decode_octet_string(_scalar("serial")(d)),
    ),
    HikvisionSensorDescription(
        key="ip_addr",
        name="IP Address",
        icon="mdi:ip",
        value_fn=lambda d: str(_scalar("ip_addr")(d)) if _scalar("ip_addr")(d) else None,
    ),
    HikvisionSensorDescription(
        key="trap_target",
        name="Trap Target",
        icon="mdi:lan-connect",
        value_fn=lambda d: decode_octet_string(_scalar("trap_target")(d)),
    ),
    HikvisionSensorDescription(
        key="cpu_freq",
        name="CPU Frequency",
        # HA 2024 deprecated `UnitOfInformation.MEGAHERTZ` (megahertz is a
        # frequency, not an information/data unit). HA 2025.1 removed the
        # deprecated alias entirely. Use the proper ``UnitOfFrequency`` enum
        # instead. The "MHz" string value is identical.
        native_unit_of_measurement=UnitOfFrequency.MEGAHERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("cpu_freq")(d))[0],
    ),
    HikvisionSensorDescription(
        key="temperature_or_load",
        name="Temperature / Load",
        # The .220.0 leaf is device-specific — could be temperature (×10)
        # or a load counter. Show raw value; user can rename / re-unit.
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: parse_int(_scalar("temperature_or_load")(d)),
    ),
    HikvisionSensorDescription(
        key="traffic_or_iops",
        name="Traffic / IOPS",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:swap-vertical",
        value_fn=lambda d: parse_int(_scalar("traffic_or_iops")(d)),
    ),
    HikvisionSensorDescription(
        key="channels_total",
        name="Channels Total",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:counter",
        value_fn=lambda d: parse_int(_scalar("channel_count")(d)),
    ),
    HikvisionSensorDescription(
        key="active_state",
        name="Active State",
        # .230.0 — INTEGER 1 typically means "any channel active/recording".
        icon="mdi:record-rec",
        value_fn=lambda d: parse_int(_scalar("active_state")(d)),
    ),
    HikvisionSensorDescription(
        key="online_state",
        name="Online State",
        # .231.0 — INTEGER count of online channels on the NVR.
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lan-pending",
        value_fn=lambda d: parse_int(_scalar("online_state")(d)),
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

    # Vendor-aware scalar sensors
    if coordinator.vendor == VENDOR_HIKVISION_NVR:
        for desc in NVR_SENSORS:
            entities.append(HikvisionSensor(coordinator, entry, desc))
    else:
        for desc in IPC_SENSORS:
            entities.append(HikvisionSensor(coordinator, entry, desc))

    # Per-channel sensors — vendor-aware shape
    channel_keys = data.get("channels", {}).get("name", {}).keys()
    # NVR channels live in the .241.1 sub-table, so the row index in
    # `channels` here is the full dotted instance (e.g. "1.0" or just "1"
    # depending on decode_walk_results trailing-component handling).
    for ch_idx in sorted(channel_keys, key=lambda x: int(x.split(".")[0])):
        if coordinator.vendor == VENDOR_HIKVISION_NVR:
            entities.append(HikvisionNvrChannelSensor(coordinator, entry, ch_idx, "label", "Channel Label"))
            entities.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "motion_flag", "Motion",
            ))
            entities.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "sub_stream_size", "Sub-stream Size",
                unit=UnitOfInformation.KILOBITS_PER_SECOND,
            ))
            entities.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "bytes_used", "Bytes Used",
                unit=UnitOfInformation.BYTES,
            ))
        else:
            entities.append(HikvisionChannelSensor(coordinator, entry, ch_idx, "name", "Channel Name"))
            entities.append(HikvisionChannelSensor(
                coordinator, entry, ch_idx, "bitrate", "Channel Bitrate",
                unit=UnitOfInformation.KILOBITS_PER_SECOND,
            ))

    # Per-disk sensors (IPC SD card or NVR HDD via .3 table — IPC only)
    disk_keys = data.get("disks", {}).get("name", {}).keys()
    for disk_idx in sorted(disk_keys, key=lambda x: int(x.split(".")[0])):
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "name", "Disk Name"))
        entities.append(HikvisionDiskSensor(
            coordinator, entry, disk_idx, "capacity", "Disk Capacity",
            unit=UnitOfInformation.GIGABYTES,
        ))

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
        unit: str | None = None,
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
        # The instance key for an NVR channel may include the trailing ".0";
        # the IPC disk table uses bare indices. Try both forms so this works
        # for either decode shape.
        raw = table.get(self._metric_key, {}).get(self._idx)
        if raw is None and not self._idx.endswith(".0"):
            raw = table.get(self._metric_key, {}).get(f"{self._idx}.0")
        return self._decode(raw)

    def _decode(self, raw: Any) -> Any:
        raise NotImplementedError


class HikvisionDiskSensor(_DynamicTableSensor):
    """Per-disk sensor (IPC SD card)."""

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
            return round(num, 2)
        return None


class HikvisionChannelSensor(_DynamicTableSensor):
    """Per-channel sensor (IPC standalone camera with multi-channel support)."""

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


class HikvisionNvrChannelSensor(_DynamicTableSensor):
    """Per-channel sensor for NVR (.50001.1.241.1.<col>.<row>.0 sub-table).

    Columns:
        1 = row index (INTEGER 1..N)
        2 = label (STRING, e.g. "lable01")
        3 = motion flag (INTEGER 0 or 10 — value 10 indicates motion)
        4 = sub-stream size (INTEGER kbps estimate; units unconfirmed)
        5 = bytes used (INTEGER bytes of recorded data on this channel)
    """

    @property
    def _table_name(self) -> str:
        return "channels"

    def _decode(self, raw: Any) -> Any:
        if raw is None:
            return None
        if self._metric_key == "label":
            return decode_octet_string(raw)
        if self._metric_key in ("motion_flag", "sub_stream_size", "bytes_used", "row_index"):
            return parse_int(raw)
        return None
