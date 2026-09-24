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
    # v0.1.21 — hardcode Chinese names in the ``name=`` field. The
    # v0.1.20 post-setup hook (clearing ``entity_registry.name`` so
    # HA's translation_key machinery runs) only worked for entities
    # that had ``_attr_name = None`` to begin with — i.e. the binary
    # sensors (Online / Recording). For static sensors with
    # ``_attr_name = "Model"`` (set in v0.1.19 as the v0.1.14 English
    # suffix fallback), HA's frontend rendered the friendly_name
    # directly without consulting the translation_key. v0.1.21 makes
    # Chinese the explicit ``name=`` value so Chinese-locale users
    # see the Chinese name regardless of whether the translation_key
    # lookup path runs. English-locale users will see the
    # ``name=`` Chinese value if HA's en.json lookup fails, but
    # the ``translation_key`` is still set so en.json can override
    # to English when HA's translation loader is working correctly.
    # Net effect: Chinese users always see Chinese. English users
    # see English when en.json is loaded (the standard case) and
    # Chinese only if en.json fails to load (rare).
    HikvisionSensorDescription(
        key="model",
        name="型号",
        translation_key="model",
        icon="mdi:information-outline",
        value_fn=lambda d: decode_octet_string(_scalar("model")(d)),
    ),
    HikvisionSensorDescription(
        key="device_name",
        name="设备名称",
        translation_key="device_name",
        icon="mdi:tag-outline",
        value_fn=lambda d: decode_octet_string(_scalar("device_name")(d)),
    ),
    HikvisionSensorDescription(
        key="firmware",
        name="固件版本",
        translation_key="firmware",
        icon="mdi:chip",
        value_fn=lambda d: decode_octet_string(_scalar("firmware")(d)),
    ),
    HikvisionSensorDescription(
        key="mac",
        name="MAC 地址",
        translation_key="mac",
        icon="mdi:network",
        value_fn=lambda d: decode_octet_string(_scalar("mac")(d)),
    ),
    HikvisionSensorDescription(
        key="manufacturer",
        name="制造商",
        translation_key="manufacturer",
        icon="mdi:factory",
        value_fn=lambda d: decode_octet_string(_scalar("manufacturer")(d)),
    ),
    HikvisionSensorDescription(
        key="cpu",
        name="CPU 使用率",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("cpu")(d))[0],
    ),
    HikvisionSensorDescription(
        key="memory_used_pct",
        name="内存使用率",
        translation_key="memory_used_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("memory_used_pct")(d))[0],
    ),
    HikvisionSensorDescription(
        key="memory_total",
        name="内存总量",
        translation_key="memory_total",
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("memory_total")(d))[0],
    ),
    HikvisionSensorDescription(
        key="storage_total",
        name="存储总量",
        translation_key="storage_total",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("storage_total")(d))[0],
    ),
    HikvisionSensorDescription(
        key="storage_used_pct",
        name="存储使用率",
        translation_key="storage_used_pct",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_value_with_unit(_scalar("storage_used_pct")(d))[0],
    ),
    HikvisionSensorDescription(
        key="uptime_seconds",
        name="运行时长",
        translation_key="uptime_seconds",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: parse_int(_scalar("uptime_seconds")(d)),
    ),
    HikvisionSensorDescription(
        key="device_time",
        name="设备时间",
        translation_key="device_time",
        icon="mdi:clock-outline",
        value_fn=lambda d: decode_octet_string(_scalar("device_time")(d)),
    ),
    HikvisionSensorDescription(
        key="network_type",
        name="网络类型",
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
        name="IP 地址",
        translation_key="ip_addr",
        icon="mdi:ip",
        # IpAddress from pysnmp; str() gives dotted notation.
        value_fn=lambda d: str(_scalar("ip_addr")(d)) if _scalar("ip_addr")(d) else None,
    ),
    HikvisionSensorDescription(
        key="subnet_mask",
        name="子网掩码",
        translation_key="subnet_mask",
        icon="mdi:subnet",
        value_fn=lambda d: str(_scalar("subnet_mask")(d)) if _scalar("subnet_mask")(d) else None,
    ),
    HikvisionSensorDescription(
        key="gateway",
        name="默认网关",
        translation_key="gateway",
        icon="mdi:router-network",
        value_fn=lambda d: str(_scalar("gateway")(d)) if _scalar("gateway")(d) else None,
    ),
    HikvisionSensorDescription(
        key="video_codec_primary",
        name="主码流编码",
        translation_key="video_codec_primary",
        icon="mdi:video-high-definition",
        value_fn=lambda d: decode_octet_string(_scalar("video_codec_primary")(d)),
    ),
    HikvisionSensorDescription(
        key="video_codec_secondary",
        name="副码流编码",
        translation_key="video_codec_secondary",
        icon="mdi:video-high-definition",
        value_fn=lambda d: decode_octet_string(_scalar("video_codec_secondary")(d)),
    ),
)


# ---- NVR scalar sensors (enterprise 50001) ----

NVR_SENSORS: tuple[HikvisionSensorDescription, ...] = (
    # v0.1.21 — hardcode Chinese in ``name=`` (see IPC_SENSORS comment
    # above for the rationale).
    HikvisionSensorDescription(
        key="serial",
        name="序列号",
        translation_key="serial",
        icon="mdi:barcode",
        value_fn=lambda d: decode_octet_string(_scalar("serial")(d)),
    ),
    HikvisionSensorDescription(
        key="ip_addr",
        name="IP 地址",
        translation_key="ip_addr",
        icon="mdi:ip",
        value_fn=lambda d: str(_scalar("ip_addr")(d)) if _scalar("ip_addr")(d) else None,
    ),
    HikvisionSensorDescription(
        key="trap_target",
        name="Trap 目标",
        translation_key="trap_target",
        icon="mdi:lan-connect",
        value_fn=lambda d: decode_octet_string(_scalar("trap_target")(d)),
    ),
    HikvisionSensorDescription(
        key="cpu_freq",
        name="CPU 频率",
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
        name="温度 / 负载",
        translation_key="temperature_or_load",
        # The .220.0 leaf is device-specific — could be temperature (×10)
        # or a load counter. Show raw value; user can rename / re-unit.
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: parse_int(_scalar("temperature_or_load")(d)),
    ),
    HikvisionSensorDescription(
        key="traffic_or_iops",
        name="流量 / IOPS",
        translation_key="traffic_or_iops",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:swap-vertical",
        value_fn=lambda d: parse_int(_scalar("traffic_or_iops")(d)),
    ),
    HikvisionSensorDescription(
        key="channels_total",
        name="通道总数",
        translation_key="channels_total",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:counter",
        value_fn=lambda d: parse_int(_scalar("channel_count")(d)),
    ),
    HikvisionSensorDescription(
        key="active_state",
        name="活动状态",
        translation_key="active_state",
        # .230.0 — INTEGER 1 typically means "any channel active/recording".
        icon="mdi:record-rec",
        value_fn=lambda d: parse_int(_scalar("active_state")(d)),
    ),
    HikvisionSensorDescription(
        key="online_state",
        name="在线状态",
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

    # v0.1.23 — split entity creation into system (immediate) and
    # per-channel/per-disk (deferred until first poll). The v0.1.22
    # design registered all entities in the initial pass, but
    # per-channel / per-disk entity creation depends on
    # ``coordinator.data`` being populated, which doesn't happen
    # until the first successful poll completes. On busy V5.x devices
    # where the first poll exceeds 10 s (or fails entirely), the
    # per-channel / per-disk entities would be skipped during the
    # initial pass.
    #
    # v0.1.23 fixes this by registering the system entities
    # immediately (model, CPU, memory, IP, etc. — these don't depend
    # on data) and deferring the per-channel / per-disk entities to a
    # coordinator listener that fires after the first successful
    # refresh. The listener is idempotent — it only adds entities
    # once per (entry, channel/disk index) so re-fires on subsequent
    # polls are no-ops.

    # ---- Phase 1: register system entities (no data dependency) ----
    system_entities: list[SensorEntity] = []
    if coordinator.vendor == VENDOR_HIKVISION_NVR:
        for desc in NVR_SENSORS:
            system_entities.append(HikvisionSensor(coordinator, entry, desc))
    else:
        for desc in IPC_SENSORS:
            system_entities.append(HikvisionSensor(coordinator, entry, desc))
    async_add_entities(system_entities)

    # v0.1.20 — force entity_registry to re-derive entity names from
    # ``translation_key`` by clearing the cached ``name`` field on every
    # system entity. The same hook is applied to dynamic entities (in
    # ``_maybe_add_dynamic_entities``) when they get added later.
    from homeassistant.helpers import entity_registry as _er

    registry = _er.async_get(hass)
    for entity in system_entities:
        try:
            if entity.entity_id:
                registry.async_update_entity(entity.entity_id, name=None)
        except Exception:  # noqa: BLE001
            pass

    # ---- Phase 2: best-effort per-channel / per-disk from current data ----
    # If the coordinator's first poll already completed (race), we
    # already have data — register those entities now.
    _maybe_add_dynamic_entities(
        hass, entry, coordinator, async_add_entities
    )

    # ---- Phase 3: register a coordinator listener for late data ----
    # If the first poll hasn't completed yet, register a one-shot
    # listener that adds per-channel / per-disk entities as soon as
    # data is available. The listener is fired after every successful
    # update, but uses a flag to be idempotent.
    if not getattr(coordinator, "_hikvision_dynamic_entities_added", False):
        coordinator._hikvision_dynamic_entities_added = False  # type: ignore[attr-defined]
        coordinator.async_add_listener(
            _make_listener(hass, entry, coordinator, async_add_entities)
        )


def _make_listener(
    hass: HomeAssistant,
    entry,
    coordinator: "HikvisionDataUpdateCoordinator",
    async_add_entities: AddEntitiesCallback,
):
    """Build a one-shot coordinator listener that adds per-channel /
    per-disk entities the first time the coordinator's data is
    populated.

    The listener is invoked after every successful refresh. The flag
    on the coordinator (``_hikvision_dynamic_entities_added``) ensures
    it only does the registration work once.
    """
    async def _on_coordinator_update() -> None:
        if getattr(coordinator, "_hikvision_dynamic_entities_added", False):
            return
        if coordinator.data is None:
            return
        _maybe_add_dynamic_entities(
            hass, entry, coordinator, async_add_entities
        )

    return _on_coordinator_update


def _maybe_add_dynamic_entities(
    hass: HomeAssistant,
    entry,
    coordinator: "HikvisionDataUpdateCoordinator",
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Register per-channel + per-disk entities if coordinator.data is populated.

    Idempotent — checks the ``_hikvision_dynamic_entities_added`` flag on
    the coordinator and returns immediately if the previous pass
    already added them. This lets both Phase 2 (immediate best-effort
    from current data) and Phase 3 (deferred listener) call this
    function without risk of duplicate entity registration.
    """
    if getattr(coordinator, "_hikvision_dynamic_entities_added", False):
        return
    if coordinator.data is None:
        return
    data = coordinator.data

    dynamic: list[SensorEntity] = []
    channel_keys = data.get("channels", {}).get("name", {}).keys()
    for ch_idx in sorted(channel_keys, key=lambda x: int(x.split(".")[0])):
        if coordinator.vendor == VENDOR_HIKVISION_NVR:
            dynamic.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "label", "通道标签",
                translation_key="nvr_channel_label",
            ))
            dynamic.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "motion_flag", "动态检测",
                translation_key="nvr_channel_motion",
            ))
            dynamic.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "sub_stream_size", "子码流大小",
                translation_key="nvr_channel_sub_stream_size",
                unit=UnitOfInformation.KILOBITS_PER_SECOND,
            ))
            dynamic.append(HikvisionNvrChannelSensor(
                coordinator, entry, ch_idx, "bytes_used", "已用字节",
                translation_key="nvr_channel_bytes_used",
                unit=UnitOfInformation.BYTES,
            ))
        else:
            dynamic.append(HikvisionChannelSensor(
                coordinator, entry, ch_idx, "name", "通道名称",
                translation_key="ipc_channel_name",
            ))
            dynamic.append(HikvisionChannelSensor(
                coordinator, entry, ch_idx, "bitrate", "通道码率",
                translation_key="ipc_channel_bitrate",
                unit=UnitOfInformation.KILOBITS_PER_SECOND,
            ))

    disk_keys = data.get("disks", {}).get("name", {}).keys()
    for disk_idx in sorted(disk_keys, key=lambda x: int(x.split(".")[0])):
        dynamic.append(HikvisionDiskSensor(
            coordinator, entry, disk_idx, "name", "磁盘名称",
            translation_key="disk_name",
        ))
        dynamic.append(HikvisionDiskSensor(
            coordinator, entry, disk_idx, "capacity", "磁盘容量",
            translation_key="disk_capacity",
            unit=UnitOfInformation.GIGABYTES,
        ))

    if not dynamic:
        return

    # Mark BEFORE async_add_entities — the listener fires the same
    # callback structure so re-fires are short-circuited.
    coordinator._hikvision_dynamic_entities_added = True  # type: ignore[attr-defined]
    async_add_entities(dynamic)

    # v0.1.20 — force entity_registry to re-derive entity names from
    # ``translation_key`` by clearing the cached ``name`` field. See
    # the comment above the original v0.1.20 call site for the full
    # rationale. The same hook is needed for the dynamically-added
    # per-channel / per-disk entities.
    from homeassistant.helpers import entity_registry as _er

    registry = _er.async_get(hass)
    for entity in dynamic:
        try:
            if entity.entity_id:
                registry.async_update_entity(entity.entity_id, name=None)
        except Exception:  # noqa: BLE001
            pass


# Backwards-compat alias so the rest of the file can still call
# _maybe_add_dynamic_entities with a simpler signature if needed.
# (The split into a separate function lets the coordinator listener
# and the immediate best-effort path share the registration logic.)
_ = _maybe_add_dynamic_entities  # silence linter unused-import


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
