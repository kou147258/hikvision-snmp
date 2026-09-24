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

import asyncio
import logging
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

_LOGGER = logging.getLogger(__name__)


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
    # v0.1.19 — restored explicit ``name=`` on every entry. v0.1.17
    # removed them to "let translation_key drive the name", but HA
    # Core's ``Entity.name`` property short-circuits on a missing
    # ``_attr_name`` and falls back to just the device name (no
    # suffix at all). The ``_attr_name`` chain needs a non-None
    # English fallback for the entity to display anything besides
    # "ipc" / "NVR".
    HikvisionSensorDescription(
        key="model",
        name="Model",
        translation_key="model",
        icon="mdi:information-outline",
        value_fn=lambda d: decode_octet_string(_scalar("model")(d)),
    ),
    HikvisionSensorDescription(
        key="device_name",
        name="Device Name",
        translation_key="device_name",
        icon="mdi:tag-outline",
        value_fn=lambda d: decode_octet_string(_scalar("device_name")(d)),
    ),
    HikvisionSensorDescription(
        key="firmware",
        name="Firmware Version",
        translation_key="firmware",
        icon="mdi:chip",
        value_fn=lambda d: decode_octet_string(_scalar("firmware")(d)),
    ),
    HikvisionSensorDescription(
        key="mac",
        name="MAC Address",
        translation_key="mac",
        icon="mdi:network",
        value_fn=lambda d: decode_octet_string(_scalar("mac")(d)),
    ),
    HikvisionSensorDescription(
        key="manufacturer",
        name="Manufacturer",
        translation_key="manufacturer",
        icon="mdi:factory",
        value_fn=lambda d: decode_octet_string(_scalar("manufacturer")(d)),
    ),
    HikvisionSensorDescription(
        key="cpu",
        name="CPU Usage",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("cpu")(d))[0],
    ),
    HikvisionSensorDescription(
        key="memory_used_pct",
        name="Memory Usage",
        translation_key="memory_used_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("memory_used_pct")(d))[0],
    ),
    HikvisionSensorDescription(
        key="memory_total",
        name="Memory Total",
        translation_key="memory_total",
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("memory_total")(d))[0],
    ),
    HikvisionSensorDescription(
        key="storage_total",
        name="Storage Total",
        translation_key="storage_total",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("storage_total")(d))[0],
    ),
    HikvisionSensorDescription(
        key="storage_used_pct",
        name="Storage Used",
        translation_key="storage_used_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("storage_used_pct")(d))[0],
    ),
    HikvisionSensorDescription(
        key="uptime_seconds",
        name="Uptime",
        translation_key="uptime_seconds",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: parse_int(_scalar("uptime_seconds")(d)),
    ),
    HikvisionSensorDescription(
        key="device_time",
        name="Device Time",
        translation_key="device_time",
        icon="mdi:clock-outline",
        value_fn=lambda d: decode_octet_string(_scalar("device_time")(d)),
    ),
    HikvisionSensorDescription(
        key="network_type",
        name="Network Type",
        translation_key="network_type",
        icon="mdi:lan",
        value_fn=lambda d: decode_octet_string(_scalar("network_type")(d)),
    ),
    # v0.1.18 — IPC network panel fields. These were defined in
    # const.py: SYSTEM_OIDS since v0.1.0 but never mapped to a
    # HikvisionSensorDescription, so the integration queried them
    # via the system OID walk but never exposed them as entities.
    HikvisionSensorDescription(
        key="ip_addr",
        name="IP Address",
        translation_key="ip_addr",
        icon="mdi:ip",
        # IpAddress from pysnmp; str() gives dotted notation.
        value_fn=lambda d: str(_scalar("ip_addr")(d)) if _scalar("ip_addr")(d) else None,
    ),
    HikvisionSensorDescription(
        key="subnet_mask",
        name="Subnet Mask",
        translation_key="subnet_mask",
        icon="mdi:subnet",
        value_fn=lambda d: str(_scalar("subnet_mask")(d)) if _scalar("subnet_mask")(d) else None,
    ),
    HikvisionSensorDescription(
        key="gateway",
        name="Gateway",
        translation_key="gateway",
        icon="mdi:router-network",
        value_fn=lambda d: str(_scalar("gateway")(d)) if _scalar("gateway")(d) else None,
    ),
    HikvisionSensorDescription(
        key="video_codec_primary",
        name="Primary Video Codec",
        translation_key="video_codec_primary",
        icon="mdi:video-high-definition",
        value_fn=lambda d: decode_octet_string(_scalar("video_codec_primary")(d)),
    ),
    HikvisionSensorDescription(
        key="video_codec_secondary",
        name="Secondary Video Codec",
        translation_key="video_codec_secondary",
        icon="mdi:video-high-definition",
        value_fn=lambda d: decode_octet_string(_scalar("video_codec_secondary")(d)),
    ),
)


# ---- NVR scalar sensors (enterprise 50001) ----

NVR_SENSORS: tuple[HikvisionSensorDescription, ...] = (
    # v0.1.19 — restored explicit ``name=`` on every entry. See the
    # IPC_SENSORS comment above for the rationale — HA Core 2026.x
    # short-circuits on ``_attr_name=None`` and falls back to just
    # the device name.
    HikvisionSensorDescription(
        key="serial",
        name="Serial Number",
        translation_key="serial",
        icon="mdi:barcode",
        value_fn=lambda d: decode_octet_string(_scalar("serial")(d)),
    ),
    HikvisionSensorDescription(
        key="ip_addr",
        name="IP Address",
        translation_key="ip_addr",
        icon="mdi:ip",
        value_fn=lambda d: str(_scalar("ip_addr")(d)) if _scalar("ip_addr")(d) else None,
    ),
    HikvisionSensorDescription(
        key="trap_target",
        name="Trap Target",
        translation_key="trap_target",
        icon="mdi:lan-connect",
        value_fn=lambda d: decode_octet_string(_scalar("trap_target")(d)),
    ),
    HikvisionSensorDescription(
        key="cpu_freq",
        name="CPU Frequency",
        translation_key="cpu_freq",
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
        translation_key="temperature_or_load",
        # The .220.0 leaf is device-specific — could be temperature (×10)
        # or a load counter. Show raw value; user can rename / re-unit.
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: parse_int(_scalar("temperature_or_load")(d)),
    ),
    HikvisionSensorDescription(
        key="traffic_or_iops",
        name="Traffic / IOPS",
        translation_key="traffic_or_iops",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:swap-vertical",
        value_fn=lambda d: parse_int(_scalar("traffic_or_iops")(d)),
    ),
    HikvisionSensorDescription(
        key="channels_total",
        name="Channels Total",
        translation_key="channels_total",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:counter",
        value_fn=lambda d: parse_int(_scalar("channel_count")(d)),
    ),
    HikvisionSensorDescription(
        key="active_state",
        name="Active State",
        translation_key="active_state",
        # .230.0 — INTEGER 1 typically means "any channel active/recording".
        icon="mdi:record-rec",
        value_fn=lambda d: parse_int(_scalar("active_state")(d)),
    ),
    HikvisionSensorDescription(
        key="online_state",
        name="Online State",
        translation_key="online_state",
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

    # v0.1.16 — guard the first-refresh wait. Hikvision V5.x firmware can
    # take 8-15 s for the first poll (system walk + channel walk + disk
    # walk, each potentially 1-2 s × N channels), and HA's entry-setup
    # timeout was being hit on ipc / NVR devices in production, surfacing
    # as ``asyncio.exceptions.CancelledError`` propagated up from
    # ``entity_platform._async_setup_platform``. Bounding the wait at
    # 15 s lets entities register with stale-but-non-blocking state
    # (they'll be unavailable until the coordinator recovers on its
    # next 10 s poll), instead of the whole entry being cancelled.
    try:
        await asyncio.wait_for(
            coordinator.async_config_entry_first_refresh(),
            timeout=15,
        )
    except asyncio.TimeoutError:
        _LOGGER.warning(
            "Initial poll did not complete within 15 s for %s; "
            "sensors will become available once the coordinator recovers",
            coordinator.client.host,
        )
    except Exception:  # noqa: BLE001
        # UpdateFailed, ConfigEntryNotReady, etc. — let HA handle.
        raise

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
    for ch_idx in sorted(channel_keys, key=lambda x: int(x.split(".")[0])):
        if coordinator.vendor == VENDOR_HIKVISION_NVR:
            entities.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "label", "Channel Label",
                translation_key="nvr_channel_label",
            ))
            entities.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "motion_flag", "Motion",
                translation_key="nvr_channel_motion",
            ))
            entities.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "sub_stream_size", "Sub-stream Size",
                translation_key="nvr_channel_sub_stream_size",
                unit=UnitOfInformation.KILOBITS_PER_SECOND,
            ))
            entities.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "bytes_used", "Bytes Used",
                translation_key="nvr_channel_bytes_used",
                unit=UnitOfInformation.BYTES,
            ))
        else:
            entities.append(HikvisionChannelSensor(
                coordinator, entry, ch_idx, "name", "Channel Name",
                translation_key="ipc_channel_name",
            ))
            entities.append(HikvisionChannelSensor(
                coordinator, entry, ch_idx, "bitrate", "Channel Bitrate",
                translation_key="ipc_channel_bitrate",
                unit=UnitOfInformation.KILOBITS_PER_SECOND,
            ))

    # Per-disk sensors (IPC SD card or NVR HDD via .3 table — IPC only)
    disk_keys = data.get("disks", {}).get("name", {}).keys()
    for disk_idx in sorted(disk_keys, key=lambda x: int(x.split(".")[0])):
        entities.append(HikvisionDiskSensor(
            coordinator, entry, disk_idx, "name", "Disk Name",
            translation_key="disk_name",
        ))
        entities.append(HikvisionDiskSensor(
            coordinator, entry, disk_idx, "capacity", "Disk Capacity",
            translation_key="disk_capacity",
            unit=UnitOfInformation.GIGABYTES,
        ))

    async_add_entities(entities)

    # v0.1.20 — force entity_registry to re-derive entity names from
    # ``translation_key`` by clearing the cached ``name`` field. HA's
    # frontend applies ``translation_key`` to the displayed name only
    # when ``entity_registry.name`` is ``None`` (no user override) AND
    # the entity's ``original_name`` field doesn't shadow the lookup.
    # The v0.1.19 release set ``_attr_name = "Model"`` etc. (restoring
    # the v0.1.14 behaviour of always showing an English suffix), which
    # caused HA to use ``name`` directly instead of running the
    # translation_key lookup — so even zh-locale HA installs continued
    # to display English names. This post-setup hook clears the name
    # override on every entity we just created, forcing HA's frontend
    # to consult ``translation_key`` on the next render and display
    # the user's locale's translation (e.g. "型号" for zh-locale users).
    from homeassistant.helpers import entity_registry as _er

    registry = _er.async_get(hass)
    for entity in entities:
        try:
            if entity.entity_id:
                registry.async_update_entity(entity.entity_id, name=None)
        except Exception:  # noqa: BLE001
            # Best-effort — if the registry entry doesn't exist yet
            # (race with HA's internal async_get_or_create) the next
            # poll cycle will hit the same path.
            pass


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
        # v0.1.19 — restore English suffix display. v0.1.17 set
        # ``_attr_name = None`` to "let translation_key drive the
        # name", but HA Core 2026.x's ``Entity.name`` cached_property
        # checks ``_attr_name`` first and short-circuits when it's
        # None (rather than falling back to ``entity_description.name``
        # or to ``registry.translation_key`` for translation lookup).
        # The result was entities displayed as just the device name
        # ("ipc", "NVR") with NO suffix at all — strictly worse than
        # the v0.1.14 English-suffix behaviour.
        #
        # The translation_key is still set so HA frontend translation
        # CAN apply it on top of the English fallback. With
        # ``_attr_name = "Model"`` and ``_attr_translation_key =
        # "model"``:
        # - English locale: HA's __init__ path returns "Model",
        #   frontend doesn't translate (en.json's "Model" maps to
        #   "Model" anyway).
        # - Chinese locale: ideally HA frontend replaces "Model" with
        #   "型号". If HA doesn't apply translation (observed on the
        #   user's HAOS 2026.x), user sees "ipc Model" instead of
        #   the broken "ipc " (no suffix).
        #
        # ``description.name`` is set on HikvisionSensorDescription
        # entries as the canonical English name; if absent we
        # synthesize a Title-Case fallback from the key so the entity
        # always has a meaningful suffix.
        if description.name:
            self._attr_name = description.name
        else:
            self._attr_name = description.key.replace("_", " ").title()
        self._attr_translation_key = description.translation_key
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
        translation_key: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._metric_key = metric_key
        # v0.1.19 — restore the v0.1.14 behaviour where ``_attr_name``
        # is set to the English ``name_suffix`` (e.g. "Channel Label",
        # "Motion", "Disk Name"). v0.1.17 set ``_attr_name = None``
        # which made the entities display as just the device name
        # (e.g. "ipc" / "NVR") with NO suffix — strictly worse.
        #
        # The translation_key is still set so HA's frontend CAN
        # overlay the translated name on top of the English suffix
        # if it decides to honour translation_key for entities that
        # already have a ``_attr_name`` set. If HA's frontend doesn't
        # honour it (observed on the user's HAOS 2026.x), the user
        # sees the English suffix — which is at least a meaningful
        # entity name instead of a blank device-name-only entry.
        self._attr_name = name_suffix
        self._attr_translation_key = translation_key
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
