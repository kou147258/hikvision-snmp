"""Pytest config — stub homeassistant modules so unit tests can import helpers
without a full HA install.

Integration / device tests inside HA are NOT done here; they happen in Task 13
against the user's live NVR / IPC.
"""

from __future__ import annotations

import dataclasses
import sys
import types


def _install_stub(name: str, attrs: dict[str, object] | None = None) -> None:
    """Insert a minimal stub module into sys.modules."""
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(module, k, v)
    sys.modules[name] = module


# Stub the homeassistant namespaces used at module-import time by
# custom_components/hikvision_snmp/__init__.py, sensor.py, binary_sensor.py,
# coordinator.py, config_flow.py, device_info.py.
# This is needed only because Python loads parent packages when a sub-module
# is imported; running the actual integration still requires a real HA install.

_install_stub("homeassistant")
_install_stub("homeassistant.config_entries", {
    "ConfigEntry": object,
    "ConfigFlow": type("ConfigFlow", (), {}),
    "ConfigFlowResult": dict,
    "OptionsFlow": type("OptionsFlow", (), {}),
})
_install_stub("homeassistant.const", {
    "CONF_HOST": "host",
    "CONF_NAME": "name",
    "CONF_PORT": "port",
    "PERCENTAGE": "%",
    "UnitOfDataSize": types.SimpleNamespace(GIGABYTES="GB"),
    "UnitOfFrequency": types.SimpleNamespace(MEGAHERTZ="MHz"),
    "UnitOfInformation": types.SimpleNamespace(
        BYTES="B",
        KILOBITS_PER_SECOND="kbps",
        MEGABYTES="MB",
        GIGABYTES="GB",
    ),
    "UnitOfTemperature": types.SimpleNamespace(CELSIUS="°C"),
    "UnitOfTime": types.SimpleNamespace(SECONDS="s"),
})
_install_stub("homeassistant.core", {
    "HomeAssistant": object,
    "callback": lambda f: f,
})
_install_stub("homeassistant.helpers")
_install_stub("homeassistant.helpers.device_registry", {
    "DeviceInfo": type("DeviceInfo", (), {}),
})
_install_stub("homeassistant.helpers.entity_platform", {
    "AddEntitiesCallback": object,
})
_install_stub("homeassistant.helpers.update_coordinator", {
    "DataUpdateCoordinator": type("DataUpdateCoordinator", (), {}),
    # Generic subscriptable stub: ``CoordinatorEntity[X]`` is used in
    # sensor.py / binary_sensor.py. ``__class_getitem__`` makes the
    # bare class subscriptable at import time, and ``__init__``
    # matches real HA's signature (accepts the coordinator instance).
    "CoordinatorEntity": type(
        "CoordinatorEntity",
        (),
        {
            "__class_getitem__": classmethod(lambda cls, _x: cls),
            "__init__": lambda self, coordinator: setattr(self, "coordinator", coordinator),
        },
    ),
    "UpdateFailed": type("UpdateFailed", (Exception,), {}),
})
# v0.1.20 — sensor.py:async_setup_entry calls
# ``homeassistant.helpers.entity_registry.async_get(hass)`` followed by
# ``registry.async_update_entity(entity_id, name=None)`` to clear the
# cached name so HA's frontend can apply translation_key on the next
# render. Stub it with a minimal class that records the calls and
# returns success.
_er_module = types.ModuleType("homeassistant.helpers.entity_registry")


class _EntityRegistryStub:
    """Minimal entity_registry stub for v0.1.20's post-setup clearing hook."""

    def __init__(self):
        self.updates: list[tuple] = []

    def async_get(self, hass):  # noqa: ARG002 — matches real signature
        return self

    def async_update_entity(self, entity_id, **kwargs):
        self.updates.append((entity_id, kwargs))
        return True


_er_module.async_get = lambda hass: _EntityRegistryStub()
_er_module.async_update_entity = lambda entity_id, **kw: True
sys.modules["homeassistant.helpers.entity_registry"] = _er_module
_install_stub("homeassistant.components")
_SENSOR_ENTITY_DESCRIPTION_FIELDS = (
    "key", "translation_key", "name", "icon", "device_class",
    "native_unit_of_measurement", "state_class", "entity_registry_enabled_default",
    "entity_category", "options", "force_update", "unit_of_measurement",
)


@dataclasses.dataclass(frozen=True)
class _SensorEntityDescriptionStub:
    """Dataclass stub that mirrors the real ``SensorEntityDescription``.

    Real HA's ``SensorEntityDescription`` is itself a frozen dataclass
    with fields like ``key``, ``translation_key``, ``name``, ``icon``,
    ``device_class``, ``state_class``, ``native_unit_of_measurement``.
    The integration's ``HikvisionSensorDescription`` is a
    ``@dataclass(frozen=True)`` subclass that inherits those fields via
    dataclass inheritance — the dataclass-generated ``__init__``
    therefore knows about every parent field.

    In tests we replace HA's stub with this frozen dataclass stub that
    exposes the same field surface, so the dataclass subclass's
    auto-generated ``__init__`` accepts every kwarg the integration
    passes. ``frozen=True`` matches the real HA ``SensorEntityDescription``
    so a `@dataclass(frozen=True)` subclass doesn't trip Python's
    "cannot inherit frozen dataclass from a non-frozen one" check.
    """
    key: str | None = None
    translation_key: str | None = None
    name: str | None = None
    icon: str | None = None
    device_class: Any = None
    native_unit_of_measurement: Any = None
    state_class: Any = None
    entity_registry_enabled_default: bool = True
    entity_category: Any = None
    options: list | None = None
    force_update: bool = False
    unit_of_measurement: Any = None


_install_stub("homeassistant.components.sensor", {
    "SensorDeviceClass": types.SimpleNamespace(
        TEMPERATURE="temperature", DURATION="duration", POWER_FACTOR="power_factor"
    ),
    "SensorEntity": type("SensorEntity", (), {}),
    "SensorEntityDescription": _SensorEntityDescriptionStub,
    "SensorStateClass": types.SimpleNamespace(
        MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing"
    ),
})
_install_stub("homeassistant.components.binary_sensor", {
    "BinarySensorDeviceClass": types.SimpleNamespace(CONNECTIVITY="connectivity"),
    "BinarySensorEntity": type("BinarySensorEntity", (), {}),
})