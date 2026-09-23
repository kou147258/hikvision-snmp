# Tested devices

This integration has been verified end-to-end against the following 7 Hikvision
devices. All use SNMP v2c with community string `public`. Devices are split by
enterprise OID:

| Vendor / product line | Enterprise OID | Identifier scalar |
|-----------------------|---------------|-------------------|
| Hikvision IPC / PTZ   | `.1.3.6.1.4.1.39165` | `.39165.1.1.0` (model) |
| Hikvision NVR         | `.1.3.6.1.4.1.50001` | `.50001.1.3.0` (serial) |

The integration auto-detects the right OID subtree at setup time — no manual
"vendor" picker is required in the UI.

## IPC / PTZ (enterprise 39165)

| Device | Model | Firmware | IP | Notes |
|--------|-------|----------|-----|-------|
| DS-2DF8C832MX-ZDK PTZ | `DS-2DF8C832MX-ZDK` | V5.10.0 build 260519 | 10.18.176.x | Busiest device — needs GETBULK auto-disable + GETNEXT with 200 ms inter-request delay. 21/23 scalars reachable via pysnmp walk. |
| DS-2DE3A20IW-D/GLT/XM IPC | `DS-2DE3A20IW-D/GLT/XM` | V5.7.30 build 260326 | 10.18.176.x | Stable. Full scalar + channel + disk coverage via pysnmp walk. |
| DS-FCN8027-VIK | `DS-FCN8027-VIK` | V5.6.1 build 190809 | 10.18.176.x | Stable. Full scalar coverage. |
| DS-FB2127 | `DS-FB2127` | V5.2.2 build 150518 | 10.18.176.x | Oldest firmware in the set. Full scalar coverage; same MIB layout as V5.10. |

All four expose the **same V5.x flat MIB** under `.39165.1.<N>.0` — the scalar
OIDs used by this integration are stable from V5.2 (2015) through V5.10 (2026).

## NVR (enterprise 50001)

All three NVRs expose the **same flat MIB** under `.50001.1.<N>.0` plus a
per-channel sub-table at `.50001.1.241.1.<col>.<row>.0`. The `.230.0` /
`.231.0` / `.240.0` / `.241.1.<col>.<row>.0` columns used by this integration
are stable across production dates 2017–2025.

| IP | Model | Production date | Channels |
|----|-------|-----------------|----------|
| 192.168.10.x | Hikvision NVR (model code 8000) | 2025-10 | 8 |
| 192.168.10.x | Hikvision NVR (model code 8000) | 2019-03 | (channels_total from `.240.0`) |
| 192.168.10.x  | Hikvision NVR (model code 8000) | 2017-07 | 5 |

Verification of the NVRs was performed via Linux `snmpwalk` against
`.1.3.6.1.4.1.50001` (which produces clean output for all leaves) — see the
`docs/release-notes/` for the v0.1.2 entry where the walk output is
reproduced verbatim.

## MIB layout differences (IPC vs NVR)

The two product lines share no enterprise subtree — they live at different
arcs and use different column layouts:

| Aspect | IPC (39165) | NVR (50001) |
|--------|-------------|-------------|
| Scalar root | `.39165.1` | `.50001.1` |
| Channel sub-tree | `.39165.2.<col>.<row>` | `.50001.1.241.1.<col>.<row>.0` (note the extra `.0` instance suffix on NVR) |
| Disk sub-tree | `.39165.3` (IPC SD card) | *Not exposed* — NVR storage is reported per-channel as `bytes_used` (`.241.1.5.<row>.0`) |
| Online scalar | `.39165.1.24.0` (INTEGER 1/0) | *Not exposed* — derived from coordinator `last_update_success` |
| Recording scalar | `.39165.1.25.0` (INTEGER 1/0) | *Not exposed* — derived from per-channel `motion_flag > 0` or device `active_state` (`.230.0`) |
| Firmware version | `.39165.1.3.0` | *Not exposed* in this MIB subtree |
| MAC address | `.39165.1.4.0` | *Not exposed* — `serial` (`.50001.1.3.0`) is used instead |
| CPU usage | `.39165.1.7.0` (STRING "27 PERCENT") | *Not exposed* — `cpu_freq` (`.50001.1.201.0`) is exposed instead |
| Memory / storage | `.39165.1.9..11.0` | *Not exposed* — per-channel `bytes_used` reports used storage |

The integration's `coordinator._vendor` property (set at setup time by
`device_info.async_identify_device`) selects the right OID root + decode
function transparently.

## Probe verification

`tools/snmp_probe.py` auto-detects vendor and prints a vendor-aware summary
of system scalars + channel/disk sub-trees. Recommended pre-flight:

```bash
python tools/snmp_probe.py --host 192.168.10.x --community public
python tools/snmp_probe.py --host 10.18.176.x  --community public
```

If you have additional device variants (DVRs, firmware variants older than
V5.2, or third-party Hikvision OEM re-brands) that respond cleanly, please
open an issue or PR with the probe output and we'll add them here.
