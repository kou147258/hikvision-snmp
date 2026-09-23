"""Standalone SNMP probe for Hikvision devices — no Home Assistant needed.

Auto-detects both Hikvision product lines:

- IPC / PTZ (enterprise 39165) — V5.x flat MIB under ``.39165.1.<N>.0`` plus
  optional channel/disk sub-trees at ``.39165.2`` / ``.39165.3``.
- NVR (enterprise 50001) — ~22 scalars under ``.50001.1.<N>.0`` plus a
  per-channel sub-table at ``.50001.1.241.1.<col>.<row>.0``.

Run this BEFORE copying the integration into HA to validate SNMP works
and the OIDs return data.

Usage (PowerShell or bash):
    python tools/snmp_probe.py --host 192.0.2.1 --community public
    python tools/snmp_probe.py --host 192.0.2.1 --version v3 \\
        --username admin --auth-protocol SHA --auth-key 'mykey123' \\
        --privacy-protocol AES128 --privacy-key 'mypriv123'

Output: prints sysDescr + vendor auto-detect + system subtree scalars +
channel/disk/table summaries so you can confirm the device responds.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import types
from pathlib import Path


# ---- HA stubs (so the integration package imports outside HA) ----

def _stub(name: str, attrs: dict[str, object] | None = None) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(module, k, v)
    sys.modules[name] = module


# Enable debug logging when --debug is in sys.argv (must happen before argparse)
log_level = logging.DEBUG if "--debug" in sys.argv else logging.INFO
logging.basicConfig(
    level=log_level,
    format="[%(name)s %(levelname)s] %(message)s",
)


_stub("homeassistant")
_stub("homeassistant.config_entries", {
    "ConfigEntry": object, "ConfigFlow": type("ConfigFlow", (), {}),
    "ConfigFlowResult": dict, "OptionsFlow": type("OptionsFlow", (), {}),
})
_stub("homeassistant.const", {
    "CONF_HOST": "host", "CONF_NAME": "name", "CONF_PORT": "port",
    "PERCENTAGE": "%",
    "UnitOfDataSize": types.SimpleNamespace(GIGABYTES="GB"),
    "UnitOfInformation": types.SimpleNamespace(
        KILOBITS_PER_SECOND="kbps", MEGAHERTZ="MHz", BYTES="B"
    ),
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

from hikvision_snmp.helpers import (  # noqa: E402
    decode_octet_string,
    decode_walk_results,
    parse_int,
    parse_value_with_unit,
)
from hikvision_snmp.const import (  # noqa: E402
    CHANNEL_OIDS,
    DISK_OIDS,
    HIKVISION_IPC_MIB_ROOT,
    HIKVISION_NVR_MIB_ROOT,
    NVR_CHANNEL_OIDS,
    NVR_SYSTEM_OIDS,
    SYSTEM_OIDS,
    VENDOR_HIKVISION_IPC,
    VENDOR_HIKVISION_NVR,
)
from hikvision_snmp.snmp_client import HikvisionSnmpClient, decode_value  # noqa: E402


async def _probe_one(
    client: HikvisionSnmpClient, oid: str, label: str
) -> str | None:
    """Single GET against ``oid``; return decoded string or None on any failure."""
    try:
        err_ind, err_stat, vbs = await client.get_raw(oid)
        if err_ind or err_stat:
            return None
        val = decode_value(vbs[0][1])
        if val is None:
            return None
        decoded = decode_octet_string(val)
        return decoded or None
    except Exception as exc:  # noqa: BLE001
        if "--debug" in sys.argv:
            print(f"[probe] {label} get failed: {exc}")
        return None


async def _detect_vendor(client: HikvisionSnmpClient) -> tuple[str | None, str | None]:
    """Auto-detect vendor; return (vendor_id, sys_descr_string).

    Tries IPC model scalar first; falls back to NVR serial scalar.
    """
    # Try IPC .39165.1.1.0 (model)
    descr = await _probe_one(client, f"{HIKVISION_IPC_MIB_ROOT}.1.1.0", "IPC")
    if descr:
        return VENDOR_HIKVISION_IPC, descr
    # Fall back to NVR .50001.1.3.0 (serial)
    descr = await _probe_one(client, f"{HIKVISION_NVR_MIB_ROOT}.1.3.0", "NVR")
    if descr:
        return VENDOR_HIKVISION_NVR, descr
    return None, None


def _print_ipc_scalars(sys_dec: dict) -> None:
    for key in SYSTEM_OIDS:
        entry = sys_dec.get(key, {})
        if not entry:
            print(f"  {key:20s}: (missing)")
            continue
        raw = entry.get("0") or next(iter(entry.values()), None)
        if key in ("cpu", "memory_used_pct", "storage_total", "storage_used_pct",
                   "memory_total"):
            num, unit = parse_value_with_unit(raw)
            print(f"  {key:20s}: raw={decode_octet_string(raw)!r}  parsed={num} {unit}")
        elif key in ("model", "device_name", "firmware", "manufacturer", "mac",
                     "device_time", "video_codec_primary", "video_codec_secondary",
                     "network_type"):
            print(f"  {key:20s}: {decode_octet_string(raw)!r}")
        else:
            print(f"  {key:20s}: {raw!r}")


def _print_nvr_scalars(sys_dec: dict) -> None:
    for key in NVR_SYSTEM_OIDS:
        entry = sys_dec.get(key, {})
        if not entry:
            print(f"  {key:24s}: (missing)")
            continue
        raw = entry.get("0") or next(iter(entry.values()), None)
        if key in ("cpu_freq",):
            num, unit = parse_value_with_unit(raw)
            print(f"  {key:24s}: raw={decode_octet_string(raw)!r}  parsed={num} {unit}")
        elif key in ("serial", "trap_target", "ip_addr", "label_or_status"):
            print(f"  {key:24s}: {decode_octet_string(raw)!r}")
        else:
            print(f"  {key:24s}: {raw!r}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Hikvision SNMP probe (dual-vendor auto-detect)")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=161)
    parser.add_argument("--version", choices=["v2c", "v3"], default="v2c")
    parser.add_argument("--community", default="public")
    parser.add_argument("--username", default="")
    parser.add_argument("--auth-protocol", default="SHA")
    parser.add_argument("--auth-key", default="")
    parser.add_argument("--privacy-protocol", default="AES128")
    parser.add_argument("--privacy-key", default="")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
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
        # 0) Diagnostic — standard RFC1213 sysDescr to verify SNMP works at all
        try:
            err_ind, err_stat, std_vbs = await client.get_raw("1.3.6.1.2.1.1.1.0")
            if err_ind:
                print(f"[probe] RFC1213 error_indication: {err_ind}")
            elif err_stat:
                print(f"[probe] RFC1213 error_status: {err_stat.prettyPrint()}")
            else:
                std_val = decode_value(std_vbs[0][1])
                print(f"[probe] RFC1213 sysDescr: {decode_octet_string(std_val)!r}")
                if std_val is None:
                    print(f"[probe]   (raw value type: {type(std_vbs[0][1]).__name__})")
        except Exception as exc:  # noqa: BLE001
            print(f"[probe] RFC1213 get failed: {exc}")

        # 1) Vendor auto-detect
        vendor, sys_descr = await _detect_vendor(client)
        if not vendor:
            print("[probe] could not detect Hikvision vendor — neither .39165 nor .50001 responded.")
            print("[probe] diagnostic: dumping any data under .39165.1 / .50001.1...")
            for label, root in (("IPC .39165.1", HIKVISION_IPC_MIB_ROOT + ".1"),
                                ("NVR .50001.1", HIKVISION_NVR_MIB_ROOT + ".1")):
                try:
                    print(f"[probe] walking {label}...")
                    walk = await client.walk(root, max_repetitions=20)
                    if walk:
                        print(f"[probe]   found {len(walk)} entries:")
                        for oid_str, val in walk[:60]:
                            print(f"     {oid_str:60s} = {val!r}")
                        if len(walk) > 60:
                            print(f"     ... ({len(walk) - 60} more)")
                    else:
                        print(f"[probe]   no entries under {label}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[probe]   walk failed: {exc}")
            return 1

        vendor_label = {
            VENDOR_HIKVISION_IPC: "Hikvision IPC / PTZ (enterprise 39165)",
            VENDOR_HIKVISION_NVR: "Hikvision NVR (enterprise 50001)",
        }.get(vendor, vendor)
        print(f"[probe] detected vendor: {vendor_label}")
        print(f"[probe] sysDescr: {sys_descr!r}")

        # 2) System subtree walk (vendor-aware)
        if vendor == VENDOR_HIKVISION_NVR:
            mib_root = HIKVISION_NVR_MIB_ROOT
            sys_oids = NVR_SYSTEM_OIDS
            sys_label = ".50001.1 (NVR system scalars)"
            print_fn = _print_nvr_scalars
        else:
            mib_root = HIKVISION_IPC_MIB_ROOT
            sys_oids = SYSTEM_OIDS
            sys_label = ".39165.1 (IPC system scalars)"
            print_fn = _print_ipc_scalars

        print(f"[probe] walking {sys_label}...")
        sys_root = f"{mib_root}.1"
        sys_raw = await client.walk(
            sys_root,
            known_leaves=list(sys_oids.values()),
        )
        sys_dec = decode_walk_results(sys_raw, sys_root, sys_oids)
        print(f"[probe] system subtree scalars ({len(sys_dec)} keys):")
        print_fn(sys_dec)

        # 3) Channel / disk subtree walks (vendor-aware)
        if vendor == VENDOR_HIKVISION_NVR:
            # NVR channel sub-table at .50001.1.241.1.<col>.<row>.0
            ch_root = f"{mib_root}.1.241.1"
            print(f"[probe] walking {ch_root} (NVR channel sub-table)...")
            try:
                ch_raw = await client.walk(ch_root, max_repetitions=10)
                ch_dec = decode_walk_results(ch_raw, ch_root, NVR_CHANNEL_OIDS)
                n_channels = len(ch_dec.get("label", {}))
                n_motion = sum(1 for v in ch_dec.get("motion_flag", {}).values() if (parse_int(v) or 0) > 0)
                print(f"[probe] channels: {n_channels} total, {n_motion} with motion_flag>0")
                for idx in sorted(ch_dec.get("label", {}).keys(), key=lambda x: int(x.split(".")[0])):
                    print(
                        f"  channel {idx}: label={decode_octet_string(ch_dec['label'].get(idx))!r} "
                        f"motion={parse_int(ch_dec.get('motion_flag', {}).get(idx))} "
                        f"substream={parse_int(ch_dec.get('sub_stream_size', {}).get(idx))} "
                        f"bytes_used={parse_int(ch_dec.get('bytes_used', {}).get(idx))}"
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[probe] channels: skipped ({exc})")
            # NVRs do not expose a separate disk sub-tree in this MIB
            print("[probe] disks: NVR does not expose a separate disk subtree; "
                  "storage is reported per-channel via bytes_used.")
        else:
            # IPC channel + disk subtrees
            ch_root = f"{mib_root}.2"
            print(f"[probe] walking {ch_root} (IPC channels)...")
            try:
                ch_raw = await client.walk(ch_root)
                ch_dec = decode_walk_results(ch_raw, ch_root, CHANNEL_OIDS)
                n_channels = len(ch_dec.get("name", {}))
                n_online = sum(1 for v in ch_dec.get("online", {}).values() if parse_int(v) == 1)
                n_recording = sum(1 for v in ch_dec.get("recording", {}).values() if parse_int(v) == 1)
                print(f"[probe] channels: {n_channels} total, {n_online} online, {n_recording} recording")
                for idx in sorted(ch_dec.get("name", {}).keys(), key=lambda x: int(x.split(".")[0])):
                    print(
                        f"  channel {idx}: name={decode_octet_string(ch_dec['name'].get(idx))!r} "
                        f"online={parse_int(ch_dec.get('online', {}).get(idx))} "
                        f"rec={parse_int(ch_dec.get('recording', {}).get(idx))} "
                        f"bitrate={parse_int(ch_dec.get('bitrate', {}).get(idx))} kbps"
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[probe] channels: skipped ({exc})")

            disk_root = f"{mib_root}.3"
            print(f"[probe] walking {disk_root} (IPC disks)...")
            try:
                disk_raw = await client.walk(disk_root)
                disk_dec = decode_walk_results(disk_raw, disk_root, DISK_OIDS)
                n_disks = len(disk_dec.get("name", {}))
                print(f"[probe] disks: {n_disks} total")
                for idx in sorted(disk_dec.get("name", {}).keys(), key=lambda x: int(x.split(".")[0])):
                    cap_mb = parse_int(disk_dec.get("capacity", {}).get(idx))
                    free_mb = parse_int(disk_dec.get("free", {}).get(idx))
                    cap_gb = round(cap_mb / 1024, 2) if cap_mb else None
                    free_gb = round(free_mb / 1024, 2) if free_mb else None
                    print(
                        f"  disk {idx}: name={decode_octet_string(disk_dec['name'].get(idx))!r} "
                        f"capacity={cap_gb} GB free={free_gb} GB "
                        f"temp={parse_int(disk_dec.get('temperature', {}).get(idx))}°C"
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[probe] disks: skipped ({exc})")

        print("[probe] OK — integration should work against this device.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[probe] FAILED: {exc}")
        return 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
