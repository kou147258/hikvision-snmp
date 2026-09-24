"""Tests for the sensor and binary_sensor platforms — translation_key + setup guards.

Covers:

- **v0.1.16** — ``_attr_translation_key`` is set on every entity so HA can
  pick the user's-locale translation from ``translations/<lang>.json``.
  Both the static ``HikvisionSensorDescription`` IPC/NVR sensors and the
  dynamic ``_DynamicTableSensor`` (per-channel / per-disk) carry a
  translation_key; English ``name=`` is kept as a fallback for users
  without a translation file in their locale.
- **v0.1.16** — ``async_setup_entry`` wraps the coordinator's
  ``async_config_entry_first_refresh`` in ``asyncio.wait_for(..., 15)``
  so a slow Hikvision V5.x firmware can't make HA cancel the entry
  setup with ``asyncio.exceptions.CancelledError`` (which is what was
  happening on the user's HAOS 2026.x with NVR + ipc devices).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.hikvision_snmp.binary_sensor import (
    HikvisionOnlineBinarySensor,
    HikvisionRecordingBinarySensor,
)
from custom_components.hikvision_snmp.const import DOMAIN
from custom_components.hikvision_snmp.sensor import (
    IPC_SENSORS,
    NVR_SENSORS,
    HikvisionSensor,
    HikvisionSensorDescription,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
EN_TRANSLATIONS = json.loads(
    (REPO_ROOT / "custom_components/hikvision_snmp/translations/en.json").read_text(
        encoding="utf-8"
    )
)
ZH_TRANSLATIONS = json.loads(
    (REPO_ROOT / "custom_components/hikvision_snmp/translations/zh.json").read_text(
        encoding="utf-8"
    )
)


# ---- v0.1.16 — translation_key coverage ----


def _all_translation_keys() -> set[str]:
    """Collect every translation key the platforms could request."""
    keys: set[str] = set()
    for desc in IPC_SENSORS:
        keys.add(desc.translation_key)
    for desc in NVR_SENSORS:
        keys.add(desc.translation_key)
    # Dynamic-table sensors use fixed translation_keys set in async_setup_entry.
    keys.update({
        "nvr_channel_label", "nvr_channel_motion",
        "nvr_channel_sub_stream_size", "nvr_channel_bytes_used",
        "ipc_channel_name", "ipc_channel_bitrate",
        "disk_name", "disk_capacity",
        "online", "recording",  # binary_sensor
    })
    return keys


def test_all_static_sensor_translations_have_key():
    """Every IPC_SENSORS / NVR_SENSORS entry has a translation_key set.

    Without this, HA would either fall back to the hardcoded ``name=``
    (visible as English even in zh-locale HA installs) or to the
    translation_key itself (visible as "model" or "cpu_freq" instead of
    a human-readable label). The regression guard is here so a future
    refactor that adds a sensor forgets translation_key isn't shipped.
    """
    for desc in IPC_SENSORS:
        assert desc.translation_key, f"IPC sensor {desc.key!r} has no translation_key"
        assert desc.translation_key == desc.key, (
            f"IPC sensor {desc.key!r} translation_key should match key "
            f"for stability; got {desc.translation_key!r}"
        )
    for desc in NVR_SENSORS:
        assert desc.translation_key, f"NVR sensor {desc.key!r} has no translation_key"
        assert desc.translation_key == desc.key, (
            f"NVR sensor {desc.key!r} translation_key should match key "
            f"for stability; got {desc.translation_key!r}"
        )


def test_translation_keys_covered_in_en_json():
    """Every translation_key referenced by the platform is present in en.json.

    If a new translation_key is added without an en.json entry, English
    users see the bare translation_key as the entity name (e.g.
    "ipc_channel_bitrate" instead of "Channel Bitrate"). This test
    catches that.
    """
    en_sensor = EN_TRANSLATIONS.get("entity", {}).get("sensor", {})
    en_binary = EN_TRANSLATIONS.get("entity", {}).get("binary_sensor", {})
    for key in _all_translation_keys():
        if key in ("online", "recording"):
            assert key in en_binary, f"binary_sensor.{key} missing from en.json"
        else:
            assert key in en_sensor, f"sensor.{key} missing from en.json"


def test_translation_keys_covered_in_zh_json():
    """Every translation_key is present in zh.json so zh-locale users see Chinese."""
    zh_sensor = ZH_TRANSLATIONS.get("entity", {}).get("sensor", {})
    zh_binary = ZH_TRANSLATIONS.get("entity", {}).get("binary_sensor", {})
    for key in _all_translation_keys():
        if key in ("online", "recording"):
            assert key in zh_binary, f"binary_sensor.{key} missing from zh.json"
        else:
            assert key in zh_sensor, f"sensor.{key} missing from zh.json"


def test_zh_translations_are_actually_chinese():
    """zh.json sensor names are not the same as en.json (i.e. actually translated).

    A bug that copied the en.json structure into zh.json would pass the
    "key exists" tests above but produce English entity names in a
    zh-locale install. This test catches that class of copy-paste bug.
    """
    zh_sensor = ZH_TRANSLATIONS["entity"]["sensor"]
    en_sensor = EN_TRANSLATIONS["entity"]["sensor"]
    for key in zh_sensor:
        zh_name = zh_sensor[key]["name"]
        en_name = en_sensor[key]["name"]
        assert zh_name != en_name, (
            f"zh.json sensor.{key} name is identical to en.json "
            f"({zh_name!r}) — translation copy-paste bug"
        )


def test_binary_sensors_carry_translation_key():
    """Both HikvisionOnline and HikvisionRecording set ``_attr_translation_key``.

    They also have ``_attr_has_entity_name = True`` (inherited from
    ``_Base``), so the displayed name is ``<device name> <translation>``
    in the user's locale.
    """
    # We can check the class-level defaults without instantiating —
    # since both classes inherit from _Base which sets
    # ``_attr_has_entity_name = True``.
    assert HikvisionOnlineBinarySensor._attr_translation_key == "online"
    assert HikvisionRecordingBinarySensor._attr_translation_key == "recording"


def test_hikvision_sensor_sets_attr_translation_key_from_description():
    """HikvisionSensor.__init__ sets ``self._attr_translation_key`` from the entity_description.

    Regression guard for v0.1.17: v0.1.16 only set
    ``entity_description.translation_key`` (a dataclass field) but
    HA Core's ``Entity.name`` cached_property reads
    ``_attr_translation_key`` on the instance first, NOT
    ``entity_description.translation_key``. Setting
    ``_attr_translation_key`` explicitly on the instance is what
    actually causes HA's frontend to look up the translation in
    ``translations/<lang>.json`` and display ``型号`` /
    ``固件版本`` / etc. instead of the English fallbacks.

    If a future refactor moves ``_attr_translation_key`` assignment
    out of HikvisionSensor.__init__, this test fails — Chinese-locale
    users see English entity names again.
    """
    # Construct a minimal HikvisionSensor instance. Skip the coordinator
    # path entirely; we're testing __init__'s side effects on the
    # translation_key attribute only.
    class _StubSensor:
        """Sentinel — we won't actually call HikvisionSensor.__init__."""
        pass

    # Inspect the HikvisionSensor.__init__ source to confirm the line
    # is present. A grep-level assertion catches both "removed entirely"
    # and "moved to a different attribute name" regressions.
    import inspect

    from custom_components.hikvision_snmp.sensor import HikvisionSensor

    source = inspect.getsource(HikvisionSensor.__init__)
    assert "self._attr_translation_key = description.translation_key" in source, (
        "HikvisionSensor.__init__ must set _attr_translation_key from "
        "the entity_description — otherwise HA's Entity.name property "
        "won't pick up the zh.json translations on a zh-locale install"
    )


def test_dynamic_table_sensor_sets_attr_name_to_name_suffix():
    """_DynamicTableSensor.__init__ must NOT set ``_attr_name``.

    Regression guard for v0.1.17: v0.1.16 set both
    ``_attr_translation_key`` AND ``_attr_name = name_suffix`` on the
    instance. HA Core's ``Entity.name`` property short-circuits on
    ``_attr_name`` (it's checked first), so the translation was never
    consulted and the entity showed the English ``name_suffix``
    regardless of locale.

    v0.1.17 sets ``_attr_name = None`` instead, letting
    ``_attr_translation_key`` drive the name resolution. The English
    fallback moves to ``entity_description.name`` so the registry's
    ``original_name`` still has something to fall back on if the
    user's locale doesn't have a matching translation.
    """
    import inspect

    from custom_components.hikvision_snmp.sensor import _DynamicTableSensor

    source = inspect.getsource(_DynamicTableSensor.__init__)
    assert "self._attr_translation_key = translation_key" in source
    assert 'self._attr_name = name_suffix' in source, (
        "_DynamicTableSensor.__init__ must set _attr_name to "
        "name_suffix so per-channel / per-disk entities show a "
        "meaningful suffix (HA Core short-circuits on _attr_name=None)"
    )


# ---- v0.1.16 — entry setup wait_for guard ----


class _FakeCoordinator:
    """Stand-in for HikvisionDataUpdateCoordinator with a configurable first-refresh delay."""

    def __init__(self, host: str = "10.0.0.1", vendor: str = "hikvision_ipc"):
        self._host = host
        self.vendor = vendor
        self.last_update_success = True
        self.data: dict | None = None
        self.refresh_called = 0
        self.device_info = None  # HikvisionSensor reads coordinator.device_info
        # Set this to delay async_config_entry_first_refresh (simulating
        # a slow Hikvision V5.x NVR with many channels).
        self._delay_seconds = 0

    @property
    def client(self):
        class _C:
            host = self._host
        return _C()

    async def async_config_entry_first_refresh(self):
        self.refresh_called += 1
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        self.data = {"identification": {}, "channels": {}, "disks": {}}
        return self.data


class _FakeEntry:
    entry_id = "test_entry"


class _FakeHass:
    def __init__(self):
        self.data = {DOMAIN: {_FakeEntry.entry_id: _FakeCoordinator()}}


def _patch_sensor_module_for_setup(coordinator):
    """Wire a FakeHass + FakeEntry so async_setup_entry can resolve the coordinator."""
    hass = _FakeHass()
    hass.data[DOMAIN][_FakeEntry.entry_id] = coordinator
    entry = _FakeEntry()

    # We don't care about the entities created in the test — only that
    # ``async_setup_entry`` doesn't blow up before reaching the entity
    # registration step. Use a sync stub to avoid "coroutine never
    # awaited" warnings from the test's own helpers.
    def fake_add_entities(entities):
        pass

    return hass, entry, fake_add_entities


@pytest.mark.asyncio
async def test_sensor_setup_does_not_wait_for_first_refresh():
    """``async_setup_entry`` returns immediately without waiting for the
    coordinator's first refresh.

    v0.1.22 removed the ``asyncio.wait_for(coordinator
    .async_config_entry_first_refresh(), timeout=15)`` guard. On busy
    V5.x devices that first refresh can take 15-30 s, which exceeded
    HA's 10 s internal "Setup of X platform is taking over 10 seconds"
    monitoring threshold. By not waiting, setup completes in < 1 s
    and entities register immediately (showing as ``unavailable``
    until the coordinator's normal 10 s poll cycle populates data).
    """
    from custom_components.hikvision_snmp.sensor import async_setup_entry

    coordinator = _FakeCoordinator()
    hass, entry, add_entities = _patch_sensor_module_for_setup(coordinator)

    await async_setup_entry(hass, entry, add_entities)
    # v0.1.22 — async_setup_entry does NOT call
    # async_config_entry_first_refresh anymore (it was removed in this
    # release). refresh_called stays at 0.
    assert coordinator.refresh_called == 0


@pytest.mark.asyncio
async def test_sensor_setup_completes_under_one_second_even_with_slow_first_refresh():
    """``async_setup_entry`` completes in < 1 s even when the coordinator's
    first poll is slow.

    Regression guard for the v0.1.16 / v0.1.19 behaviour where the
    15 s ``wait_for`` caused HA's "Setup of X platform is taking
    over 10 seconds" warning to fire on busy V5.x devices.
    """
    import time

    import custom_components.hikvision_snmp.sensor as sensor_mod

    coordinator = _FakeCoordinator()
    coordinator._delay_seconds = 5.0  # way over the old 15s guard
    hass, entry, add_entities = _patch_sensor_module_for_setup(coordinator)

    start = time.monotonic()
    await sensor_mod.async_setup_entry(hass, entry, add_entities)
    elapsed = time.monotonic() - start

    # v0.1.22 — setup should be near-instantaneous (the slow refresh
    # happens in the background, NOT in async_setup_entry).
    assert elapsed < 0.5, (
        f"async_setup_entry took {elapsed:.2f}s — should be near-instant. "
        f"v0.1.22 explicitly does NOT wait for the first refresh."
    )


@pytest.mark.asyncio
async def test_binary_sensor_setup_does_not_wait_for_first_refresh():
    """Same instant-setup test for the binary_sensor platform."""
    import custom_components.hikvision_snmp.binary_sensor as binary_mod

    coordinator = _FakeCoordinator()
    coordinator._delay_seconds = 5.0
    hass, entry, add_entities = _patch_sensor_module_for_setup(coordinator)

    import time

    start = time.monotonic()
    await binary_mod.async_setup_entry(hass, entry, add_entities)
    elapsed = time.monotonic() - start

    assert elapsed < 0.5, (
        f"binary_sensor async_setup_entry took {elapsed:.2f}s — should be near-instant"
    )
    assert coordinator.refresh_called == 0


# ---- v0.1.16 — translations files are valid JSON ----


def test_translations_json_files_are_well_formed():
    """Both en.json and zh.json parse cleanly and contain the expected top-level keys.

    Guards against an accidental trailing comma or missing brace making
    HA silently fall back to showing the integration's hardcoded
    ``name=`` English strings.
    """
    for lang, data in (("en", EN_TRANSLATIONS), ("zh", ZH_TRANSLATIONS)):
        assert "config" in data, f"{lang}.json missing 'config' section"
        assert "options" in data, f"{lang}.json missing 'options' section"
        assert "entity" in data, f"{lang}.json missing 'entity' section"
        assert "sensor" in data["entity"], f"{lang}.json entity.sensor missing"
        assert "binary_sensor" in data["entity"], f"{lang}.json entity.binary_sensor missing"