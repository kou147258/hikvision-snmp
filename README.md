# Hikvision SNMP

A Home Assistant custom component that monitors Hikvision NVRs and standalone IPCs over SNMP v2c or v3 — read-only sensors for device health (CPU, memory, temperature, uptime, firmware), per-channel status, and disk / SD-card state.

> **v1 scope: sensors and binary_sensors only.** Reboot / channel control / PTZ are not implemented (deferred to v2).

## Installation

### HACS (recommended)

1. Install [HACS](https://hacs.xyz/).
2. HACS → Integrations → ⋯ → **Custom repositories** → add `https://github.com/43457/hikvision-snmp` as **Integration**.
3. Refresh, find **Hikvision SNMP**, install.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/hikvision_snmp/` into your HA `config/custom_components/` directory.
2. Restart Home Assistant.

## Configure

1. **Settings → Devices & Services → Add Integration → Hikvision SNMP**.
2. Step 1 — enter a name, the device IP, port (default 161), and device type (`auto` / `nvr` / `ipc`). `auto` queries the device's `deviceType` OID.
3. Step 2 — pick SNMP v2c or v3 and enter credentials.
4. Step 3 — the integration runs a live `GET sysDescr` to confirm reachability. On success the entry is created.

### Hikvision device prep

SNMP is disabled by default on Hikvision firmware. Enable it:

1. Log into the device web UI.
2. **Configuration → Network → SNMP**.
3. Tick **Enable SNMP**.
4. Set SNMP version (v2c or v3) and community / v3 credentials.
5. **Save**.

The integration talks to UDP port 161. If the device is on a different VLAN, allow the path on your firewall.

## Entities

For each configured device:

| Entity | Type | Description |
|---|---|---|
| CPU Usage | sensor | % |
| Memory Usage | sensor | % |
| Temperature | sensor | °C |
| Uptime | sensor | duration (seconds; rendered as d h m in UI) |
| Firmware Version | sensor | text |
| Device Name | sensor | text |
| Model | sensor | text |
| Channels Total | sensor | int |
| Channels Online | sensor | int |
| Channels Recording | sensor | int |
| Online | binary_sensor | device reachable |
| Recording | binary_sensor | any channel recording |
| Disk N Name / Capacity / Free / Temperature | sensor | per detected disk / SD card |
| Channel N Name / Bitrate | sensor | per detected channel |

## Options

Settings → Devices & Services → Hikvision SNMP → ⋯ → **Configure**:

- **Poll interval (seconds)** — default 10, range 5–300. Shorter intervals increase HA event-loop load with many devices; for 6–20 devices 10–30s is recommended.

## Compatibility

- `pysnmp>=6.2.6,<7.0.0`
- Home Assistant 2025.4+
- Python 3.11+

## Known Limitations (v0.1.1)

### Hikvision V5.x firmware quirks

Verified across two V5.x devices in the same network (`DS-2DF8C832MX-ZDK` PTZ
on V5.10.0, `DS-2DE3A20IW-D/GLT/XM` IPC on V5.7.30):

1. **GETBULK times out** — bulkCmd packets get no response from the device.
   The integration detects this once per host and silently switches to
   GETNEXT for the remainder of the session.
2. **GETNEXT walk truncates mid-subtree** — the device starts dropping
   GETNEXT responses around leaf .11 under load. v0.1.1 compensates by
   issuing single-GET fallbacks (with retry + 500ms backoff) for every
   leaf index listed in `SYSTEM_OIDS` that the walk missed. Result:
   ~21/23 system scalars are reliably populated.
3. **Three INTEGER leaves consistently timeout even on single GET**
   (`.12.0` / `.24.0` / `.25.0`). These are exposed as `uptime_seconds`,
   `online`, and `recording`. The integration handles the gap gracefully:
   - `uptime_seconds` shows `unavailable` (informational only).
   - `online` (binary_sensor) falls back to `coordinator.last_update_success`.
   - `recording` (binary_sensor) returns `unknown` for IPCs without a
     channel table.
5. **Busy-device behaviour on V5.7.30 IPCs under load** — when the IPC is
   actively streaming video / recording, its SNMP daemon is starved by the
   video pipeline and many requests timeout. v0.1.1 mitigates this with:
   - 200ms inter-request delay in `walk_next` to give the daemon breathing
     room.
   - GETNEXT and single-GET retry on `RequestTimedOut` (500ms backoff).
   - 1s per-request timeout (down from 2s) so failures surface quickly.
   - For **initial sync** on a busy device, reboot the IPC and add it to
     Home Assistant while the device is idle — the daemon responds fully
     during the boot window. Subsequent updates may be partial; this is a
     firmware-level limitation.

### pysnmp + Windows quirk (affects the probe tool only)

The standalone probe (`tools/snmp_probe.py`) runs on Windows and may not
be able to complete a walk against a busy V5.7.30 IPC even with retries —
pysnmp's UDP transport on Windows drops packets that Linux net-snmp
successfully receives. This is a platform / library issue, not an
integration bug. Home Assistant itself runs on Linux in the vast
majority of installs; the integration behaves correctly there.

### Not supported (deferred to v0.2)

- ISAPI / HTTP fallback (when SNMP daemon is fully starved)
- Switch / control entities (reboot, channel on/off)
- PTZ control
- HACS default repository submission

## License

MIT © 2026 43457. See `LICENSE`.