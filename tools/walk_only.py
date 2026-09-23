"""Single-purpose walk probe — runs one GETBULK on a target OID root and
prints every entry it finds. Use this when the main snmp_probe.py walks
hit timeouts (rate-limit hypothesis) — gives the device time to recover
and runs a single, isolated walk.

Usage:
    python tools/walk_only.py --host 192.168.1.100 --oid .1.3.6.1.4.1.39165
    python tools/walk_only.py --host 192.168.1.100   # defaults to Hikvision root
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import types
from pathlib import Path

# ---- HA stub so the integration package can be imported ----
def _stub(name: str, attrs: dict[str, object] | None = None) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(module, k, v)
    sys.modules[name] = module


_stub("homeassistant")
_stub("homeassistant.config_entries", {
    "ConfigEntry": object, "ConfigFlow": type("ConfigFlow", (), {}),
    "ConfigFlowResult": dict, "OptionsFlow": type("OptionsFlow", (), {}),
})
_stub("homeassistant.const", {
    "CONF_HOST": "host", "CONF_NAME": "name", "CONF_PORT": "port",
    "PERCENTAGE": "%",
    "UnitOfDataSize": types.SimpleNamespace(GIGABYTES="GB"),
    "UnitOfInformation": types.SimpleNamespace(KILOBITS_PER_SECOND="kbps"),
    "UnitOfTemperature": types.SimpleNamespace(CELSIUS="°C"),
    "UnitOfTime": types.SimpleNamespace(SECONDS="s"),
})
_stub("homeassistant.core", {"HomeAssistant": object, "callback": lambda f: f})
_stub("homeassistant.helpers")
_stub("homeassistant.helpers.device_registry", {"DeviceInfo": type("DeviceInfo", (), {})})
_stub("homeassistant.helpers.entity_platform", {"AddEntitiesCallback": object})
_stub("homeassistant.helpers.update_coordinator", {
    "DataUpdateCoordinator": type("DataUpdateCoordinator", (), {}),
    "UpdateFailed": type("UpdateFailed", (Exception,), {}),
})
_stub("homeassistant.components")
_stub("homeassistant.components.sensor", {
    "SensorDeviceClass": types.SimpleNamespace(TEMPERATURE="temperature", DURATION="duration", POWER_FACTOR="power_factor"),
    "SensorEntity": type("SensorEntity", (), {}),
    "SensorEntityDescription": type("SensorEntityDescription", (), {}),
    "SensorStateClass": types.SimpleNamespace(MEASUREMENT="measurement", TOTAL_INCREASING="total_increasing"),
})
_stub("homeassistant.components.binary_sensor", {
    "BinarySensorDeviceClass": types.SimpleNamespace(CONNECTIVITY="connectivity"),
    "BinarySensorEntity": type("BinarySensorEntity", (), {}),
})

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components"))

from hikvision_snmp.snmp_client import HikvisionSnmpClient, HikvisionSnmpError  # noqa: E402
from hikvision_snmp.helpers import decode_octet_string, parse_int  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Single-OID GETBULK walk probe")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=161)
    parser.add_argument("--community", default="public")
    parser.add_argument("--version", choices=["v2c", "v3"], default="v2c")
    parser.add_argument("--username", default="")
    parser.add_argument("--auth-protocol", default="SHA")
    parser.add_argument("--auth-key", default="")
    parser.add_argument("--privacy-protocol", default="AES128")
    parser.add_argument("--privacy-key", default="")
    parser.add_argument("--oid", default="1.3.6.1.4.1.39165",
                        help="OID root to walk (default: Hikvision enterprise root)")
    parser.add_argument("--max-repetitions", type=int, default=25)
    parser.add_argument("--limit", type=int, default=120,
                        help="Max entries to print")
    args = parser.parse_args()

    if args.version == "v2c":
        auth = {"community": args.community}
    else:
        if not (args.username and args.auth_key and args.privacy_key):
            print("v3 requires --username, --auth-key, --privacy-key")
            return 2
        auth = {
            "username": args.username,
            "auth_protocol": args.auth_protocol,
            "auth_key": args.auth_key,
            "privacy_protocol": args.privacy_protocol,
            "priv_key": args.privacy_key,
        }

    client = HikvisionSnmpClient(
        host=args.host, port=args.port, version=args.version, auth=auth,
    )
    print(f"[walk] target={args.oid}  host={args.host}:{args.port}  ver={args.version}")
    try:
        results = await client.walk(args.oid, max_repetitions=args.max_repetitions)
        print(f"[walk] got {len(results)} entries")
        for oid_str, val in results[:args.limit]:
            # If value is a string, show decoded; otherwise show raw type
            if isinstance(val, bytes):
                print(f"  {oid_str:60s} = {decode_octet_string(val)!r}")
            elif isinstance(val, int):
                print(f"  {oid_str:60s} = {val}")
            elif val is None:
                print(f"  {oid_str:60s} = <NoSuchInstance>")
            else:
                print(f"  {oid_str:60s} = {val!r}")
        if len(results) > args.limit:
            print(f"  ... ({len(results) - args.limit} more, raise --limit to see)")
        return 0
    except HikvisionSnmpError as exc:
        print(f"[walk] FAILED: {exc}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))