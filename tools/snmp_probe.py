"""Standalone SNMP probe for Hikvision devices — no Home Assistant needed.
Run this BEFORE copying the integration into HA to validate SNMP works
and the OIDs return data.

Usage (PowerShell or bash):
    python tools/snmp_probe.py --host 192.168.10.100 --community public
    python tools/snmp_probe.py --host 192.168.10.100 --version v3 \
        --username admin --auth-protocol SHA --auth-key 'mykey123' \
        --privacy-protocol AES128 --privacy-key 'mypriv123'

Output: prints sysDescr + system subtree scalars + channel/disk table
summaries so you can confirm the device responds.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import types
from pathlib import Path

# Stub homeassistant so the integration package's __init__.py can be loaded
# without a full HA install. The probe only uses helpers / const / snmp_client,
# none of which actually need HA at runtime — the HA imports in __init__.py
# are just type hints and decorators.
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

# Make the integration package importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components"))

from hikvision_snmp.helpers import decode_octet_string, decode_walk_results, parse_int  # noqa: E402
from hikvision_snmp.const import (  # noqa: E402
    CHANNEL_OIDS,
    DISK_OIDS,
    HIKVISION_PRIVATE_MIB_ROOT,
    SYSTEM_OIDS,
)
from hikvision_snmp.snmp_client import HikvisionSnmpClient  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Hikvision SNMP probe")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=161)
    parser.add_argument("--version", choices=["v2c", "v3"], default="v2c")
    parser.add_argument("--community", default="public")
    parser.add_argument("--username", default="")
    parser.add_argument("--auth-protocol", default="SHA")
    parser.add_argument("--auth-key", default="")
    parser.add_argument("--privacy-protocol", default="AES128")
    parser.add_argument("--privacy-key", default="")
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

    client = HikvisionSnmpClient(host=args.host, port=args.port, version=args.version, auth=auth)
    print(f"[probe] connecting to {args.host}:{args.port} via {args.version}...")

    try:
        # 0) Diagnostic — try standard RFC1213 sysDescr to verify SNMP works at all
        try:
            std_descr = await client.get("1.3.6.1.2.1.1.1.0")
            print(f"[probe] RFC1213 sysDescr (standard OID): {decode_octet_string(std_descr)!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"[probe] RFC1213 sysDescr failed: {exc}")

        # 1) sysDescr scalar GET on Hikvision private MIB
        sys_descr = await client.get(f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1.1.0")
        print(f"[probe] Hikvision sysDescr (private OID): {decode_octet_string(sys_descr)!r}")
        if not sys_descr:
            print()
            print("[probe] === DIAGNOSTICS ===")
            print("[probe] Hikvision private MIB did not respond. Possible causes:")
            print("[probe] 1. Device is not actually Hikvision (try --community private)")
            print("[probe]    - Hikvision ships with default community 'private', not 'public'")
            print("[probe]    - Some firmwares refuse unknown community strings without trap setup")
            print("[probe] 2. SNMP is disabled in device web UI")
            print("[probe]    - Configuration → Network → SNMP → Enable SNMP")
            print("[probe] 3. UDP port 161 is blocked by firewall or ACL on this VLAN")
            print("[probe] 4. Very old firmware (pre-2018) uses different enterprise OID")
            print()
            print("[probe] Try one of:")
            print(f"[probe]   python tools/snmp_probe.py --host {args.host} --community private")
            print(f"[probe]   Test-NetConnection {args.host} -Port 161")
            print("[probe] If the RFC1213 line above is empty too, the device is unreachable")
            print("[probe] or the credentials are wrong. If RFC1213 returned a string but")
            print("[probe] Hikvision did not, the device is on the network but either not")
            print("[probe] Hikvision or its private MIB is disabled.")
            return 1

        # 2) System subtree walk
        sys_raw = await client.walk(f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1")
        sys_dec = decode_walk_results(sys_raw, f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1", SYSTEM_OIDS)
        print("[probe] system subtree scalars:")
        for key in SYSTEM_OIDS:
            entry = sys_dec.get(key, {})
            if not entry:
                print(f"  {key:20s}: (missing)")
                continue
            raw = entry.get("0") or next(iter(entry.values()), None)
            if key in ("model", "device_name", "firmware"):
                print(f"  {key:20s}: {decode_octet_string(raw)!r}")
            else:
                print(f"  {key:20s}: {parse_int(raw)}")

        # 3) Channel subtree walk
        ch_raw = await client.walk(f"{HIKVISION_PRIVATE_MIB_ROOT}.1.2.1")
        ch_dec = decode_walk_results(ch_raw, f"{HIKVISION_PRIVATE_MIB_ROOT}.1.2.1", CHANNEL_OIDS)
        n_channels = len(ch_dec.get("name", {}))
        n_online = sum(1 for v in ch_dec.get("online", {}).values() if parse_int(v) == 1)
        n_recording = sum(1 for v in ch_dec.get("recording", {}).values() if parse_int(v) == 1)
        print(f"[probe] channels: {n_channels} total, {n_online} online, {n_recording} recording")
        for idx in sorted(ch_dec.get("name", {}).keys(), key=lambda x: int(x)):
            print(f"  channel {idx}: name={decode_octet_string(ch_dec['name'].get(idx))!r} "
                  f"online={parse_int(ch_dec.get('online', {}).get(idx))} "
                  f"rec={parse_int(ch_dec.get('recording', {}).get(idx))} "
                  f"bitrate={parse_int(ch_dec.get('bitrate', {}).get(idx))} kbps")

        # 4) Disk subtree walk
        disk_raw = await client.walk(f"{HIKVISION_PRIVATE_MIB_ROOT}.1.3.1")
        disk_dec = decode_walk_results(disk_raw, f"{HIKVISION_PRIVATE_MIB_ROOT}.1.3.1", DISK_OIDS)
        n_disks = len(disk_dec.get("name", {}))
        print(f"[probe] disks: {n_disks} total")
        for idx in sorted(disk_dec.get("name", {}).keys(), key=lambda x: int(x)):
            cap_mb = parse_int(disk_dec.get("capacity", {}).get(idx))
            free_mb = parse_int(disk_dec.get("free", {}).get(idx))
            cap_gb = round(cap_mb / 1024, 2) if cap_mb else None
            free_gb = round(free_mb / 1024, 2) if free_mb else None
            print(f"  disk {idx}: name={decode_octet_string(disk_dec['name'].get(idx))!r} "
                  f"capacity={cap_gb} GB free={free_gb} GB "
                  f"temp={parse_int(disk_dec.get('temperature', {}).get(idx))}°C")

        print("[probe] OK — integration should work against this device.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[probe] FAILED: {exc}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))