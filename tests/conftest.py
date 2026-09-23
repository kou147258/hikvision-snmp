"""Pytest config — stub homeassistant modules so unit tests can import helpers
without a full HA install.

Integration / device tests inside HA are NOT done here; they happen in Task 13
against the user's live NVR / IPC.
"""

from __future__ import annotations

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
    "UnitOfInformation": types.SimpleNamespace(KILOBITS_PER_SECOND="kbps"),
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
    "UpdateFailed": type("UpdateFailed", (Exception,), {}),
})
_install_stub("homeassistant.components")
_install_stub("homeassistant.components.sensor", {
    "SensorDeviceClass": types.SimpleNamespace(
        TEMPERATURE="temperature", DURATION="duration", POWER_FACTOR="power_factor"
    ),
    "SensorEntity": type("SensorEntity", (), {}),
    "SensorEntityDescription": type("SensorEntityDescription", (), {}),
    "SensorStateClass": types.SimpleNamespace(
        MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing"
    ),
})
_install_stub("homeassistant.components.binary_sensor", {
    "BinarySensorDeviceClass": types.SimpleNamespace(CONNECTIVITY="connectivity"),
    "BinarySensorEntity": type("BinarySensorEntity", (), {}),
})