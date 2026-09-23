# Hikvision SNMP

A Home Assistant custom component that monitors Hikvision NVRs and standalone IPCs over SNMP v2c or v3 — read-only sensors for device health (CPU, memory, temperature, uptime, firmware), per-channel status, and disk / SD-card state.

Two product lines are supported transparently via auto-detect:

- **Hikvision IPC / PTZ** — enterprise OID `.1.3.6.1.4.1.39165` (V5.x flat MIB).
- **Hikvision NVR** — enterprise OID `.1.3.6.1.4.1.50001` (different MIB layout, per-channel sub-table).

The integration picks the right subtree at setup time — no manual "vendor" picker is required in the UI. See [`docs/tested-devices.md`](docs/tested-devices.md) for the 7 verified devices.

> **v1 scope: sensors and binary_sensors only.** Reboot / channel control / PTZ are not implemented (deferred to v2).

## Installation

### HACS (recommended)

1. Install [HACS](https://hacs.xyz/).
2. HACS → Integrations → ⋯ → **Custom repositories** → add `https://github.com/kou147258/hikvision-snmp` as **Integration**.
3. Refresh, find **Hikvision SNMP**, install.
4. Restart Home Assistant.

### Manual

1. Copy `custom_components/hikvision_snmp/` into your HA `config/custom_components/` directory.
2. Restart Home Assistant.

## Configure

1. **Settings → Devices & Services → Add Integration → Hikvision SNMP**.
2. Step 1 — enter a name, the device IP, port (default 161), and device type (`auto` / `nvr` / `ipc`). `auto` queries both `.39165` and `.50001` subtrees and picks whichever responds.
3. Step 2 — pick SNMP v2c or v3 and enter credentials.
4. Step 3 — the integration runs a live `GET sysDescr` to confirm reachability. On success the entry is created with the detected vendor stored on the coordinator.

### Hikvision device prep

SNMP is disabled by default on Hikvision firmware. Enable it:

1. Log into the device web UI.
2. **Configuration → Network → SNMP**.
3. Tick **Enable SNMP**.
4. Set SNMP version (v2c or v3) and community / v3 credentials.
5. **Save**.

The integration talks to UDP port 161. If the device is on a different VLAN, allow the path on your firewall.

## Entities

### IPC / PTZ (enterprise 39165)

| Entity | Type | Description |
|---|---|---|
| Model | sensor | text (from `.39165.1.1.0`) |
| Device Name | sensor | text |
| Firmware Version | sensor | text |
| MAC Address | sensor | text |
| Manufacturer | sensor | text |
| CPU Usage | sensor | % |
| Memory Usage | sensor | % |
| Memory Total | sensor | MB |
| Storage Total | sensor | GB |
| Storage Used | sensor | % |
| Uptime | sensor | duration |
| Device Time | sensor | text |
| Network Type | sensor | text |
| Channel N Name | sensor | text (per detected channel) |
| Channel N Bitrate | sensor | kbps (per detected channel) |
| Disk N Name | sensor | text (per detected SD card) |
| Disk N Capacity | sensor | GB (per detected SD card) |
| Online | binary_sensor | device reachable (`.39165.1.24.0`, falls back to coordinator heartbeat) |
| Recording | binary_sensor | any channel recording (`.39165.1.25.0` or per-channel) |

### NVR (enterprise 50001)

| Entity | Type | Description |
|---|---|---|
| Serial Number | sensor | text (`.50001.1.3.0`) |
| IP Address | sensor | text (`.50001.1.1.0`) |
| Trap Target | sensor | text (`.50001.1.110.0`) |
| CPU Frequency | sensor | MHz (`.50001.1.201.0`) |
| Temperature / Load | sensor | int raw value (`.50001.1.220.0` — device-specific, may be temperature ×10 or load counter) |
| Traffic / IOPS | sensor | int raw value (`.50001.1.221.0`) |
| Channels Total | sensor | int (`.50001.1.240.0`) |
| Active State | sensor | int (`.50001.1.230.0` — 1 means ≥1 channel is active) |
| Online State | sensor | int (`.50001.1.231.0` — count of online channels) |
| Channel N Label | sensor | text (per detected channel) |
| Channel N Motion | sensor | int (0 or 10 — 10 indicates motion detected) |
| Channel N Sub-stream Size | sensor | kbps (units unconfirmed) |
| Channel N Bytes Used | sensor | bytes (storage used by this channel) |
| Online | binary_sensor | coordinator heartbeat (NVR has no `.24` scalar) |
| Recording | binary_sensor | any channel `motion_flag > 0`, or device `active_state == 1` |

> NVRs do not expose a per-disk sub-table in this MIB subtree; per-channel
> `Bytes Used` is the closest storage indicator available.

## Options

Settings → Devices & Services → Hikvision SNMP → ⋯ → **Configure**:

- **Poll interval (seconds)** — default 10, range 5–300. Shorter intervals increase HA event-loop load with many devices; for 6–20 devices 10–30s is recommended.

## Compatibility

- `pysnmp>=6.2.6,<7.0.0`
- Home Assistant 2025.4+
- Python 3.11+

## Known Limitations (v0.1.2)

### Hikvision V5.x firmware quirks (IPC / PTZ)

Verified across four V5.x devices in the same network (`DS-2DF8C832MX-ZDK`
PTZ on V5.10.0, `DS-2DE3A20IW-D/GLT/XM` IPC on V5.7.30, `DS-FCN8027-VIK` on
V5.6.1, `DS-FB2127` on V5.2.2):

1. **GETBULK times out on busy devices** — bulkCmd packets get no response.
   The integration detects this once per host and silently switches to
   GETNEXT for the remainder of the session.
2. **GETNEXT walk truncates mid-subtree** — the device starts dropping
   GETNEXT responses around leaf .11 under load. v0.1.1+ compensates by
   issuing single-GET fallbacks (with retry + 500 ms backoff) for every
   leaf index listed in `SYSTEM_OIDS` that the walk missed. Result:
   ~21/23 system scalars are reliably populated.
3. **Three INTEGER leaves consistently timeout even on single GET**
   (`.12.0` / `.24.0` / `.25.0`). These are exposed as `uptime_seconds`,
   `online`, and `recording`. The integration handles the gap gracefully:
   - `uptime_seconds` shows `unavailable` (informational only).
   - `online` (binary_sensor) falls back to `coordinator.last_update_success`.
   - `recording` (binary_sensor) returns `unknown` for IPCs without a
     channel table.
4. **Busy-device behaviour under load** — when the IPC is actively streaming
   video / recording, its SNMP daemon is starved by the video pipeline and
   many requests timeout. v0.1.1+ mitigates this with:
   - 200 ms inter-request delay in `walk_next` to give the daemon breathing room.
   - GETNEXT and single-GET retry on `RequestTimedOut` (500 ms backoff).
   - 1 s per-request timeout (down from 2 s) so failures surface quickly.
   - For **initial sync** on a busy device, reboot the IPC and add it to
     Home Assistant while the device is idle — the daemon responds fully
     during the boot window. Subsequent updates may be partial; this is a
     firmware-level limitation.

### Hikvision NVR (enterprise 50001) quirks

Verified across three NVRs (`192.168.10.17` / `192.168.10.10` / `192.168.10.9`,
production dates 2017–2025). All three expose the same flat MIB layout.

1. **NVRs do not expose** `.24` (online) / `.25` (recording) / `.3`
   (firmware) / `.4` (MAC) / `.7` (CPU%) / `.9` (memory%) / `.8` (storage)
   scalars. The integration substitutes the closest equivalent in
   `NVR_SENSORS`.
2. **Per-channel storage is reported in `bytes_used`** (`.50001.1.241.1.5.<row>.0`),
   not via a separate disk sub-table.
3. **`.220` and `.221` are device-specific metrics** — `.220` may be
   temperature ×10 or a load counter depending on NVR model; `.221` is
   either traffic rate or IOPS. Both are exposed as raw int sensors and
   the user can rename / re-unit them in HA.

### pysnmp + Windows quirk (affects the probe tool only)

The standalone probe (`tools/snmp_probe.py`) runs on Windows and may not
be able to complete a walk against a busy V5.x device even with retries —
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
