# Hikvision SNMP Integration for Home Assistant — Design Spec

**Date**: 2026-09-23
**Status**: Approved (user sign-off 2026-09-23)
**Author**: Mavis (brainstorming session)
**Target repo**: `https://github.com/43457/hikvision-snmp` (public, HACS-compatible)

---

## 1. Goal

Provide a Home Assistant custom component that polls Hikvision NVRs and standalone IPCs over SNMP v2c or v3, exposing read-only **sensor** and **binary_sensor** entities for device health (CPU / memory / temperature / uptime / firmware), per-channel status (online / recording / bitrate), and disk / SD-card state. No write / control surfaces in v1.

The integration is intended for 6–20 devices on a single HA instance (medium deployment).

---

## 2. Non-Goals (v1)

- Switch / control entities (reboot, channel on/off, PTZ) — deferred to v2.
- ISAPI / HTTP fallback — out of scope for v1. SNMP only.
- Discovery / auto-LAN-scan — manual config entry only.
- HACS default repository submission — code conforms to HACS schema but is **not** submitted to default HACS store in v1; install via custom repository.
- Historical recording query / playback — out of scope (ISAPI domain, not SNMP).

---

## 3. Architecture

```
┌────────────────────────────────────────────────────────┐
│ HA Core  ← one config entry per device                 │
└─────────────┬──────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────────┐
│ HikvisionDataUpdateCoordinator (per device, default 10s) │
│   - GETBULK 4 subtrees → parse → coordinator.data dict  │
└─────────────┬──────────────────────────────────────────┘
              ↓
┌────────────────────────────────────────────────────────┐
│ HikvisionSnmpClient (per host, v2c/v3 runtime switch)   │
│   - async get(oid)                                      │
│   - async walk_bulk(subtree_root, max_repetitions=...)   │
└─────────────┬──────────────────────────────────────────┘
              ↓ pysnmp.hlapi.v3arch.asyncio (UDP/161)
        NVR / IPC 设备
```

### 3.1 Module Layout

```
hikvision-snmp/
├── .gitignore
├── LICENSE                                  # MIT
├── README.md                                # install + usage
├── hacs.json                                # HACS schema
├── docs/
│   ├── superpowers/specs/2026-05-23-hikvision-snmp-design.md
│   └── oid-reference.md                     # public OID table
└── custom_components/hikvision_snmp/
    ├── __init__.py                          # entry, entity registration
    ├── manifest.json                        # pysnmp>=6.2.6,<7.0.0
    ├── const.py                             # OIDs, device_type enums, defaults
    ├── config_flow.py                       # ConfigFlow + OptionsFlow
    ├── coordinator.py                       # DataUpdateCoordinator
    ├── snmp_client.py                       # pysnmp v7 asyncio wrapper
    ├── device_info.py                       # device identification
    ├── sensor.py                            # SensorEntity subclasses
    ├── binary_sensor.py                     # BinarySensorEntity subclasses
    ├── helpers.py                           # OID walk / value decode
    ├── services.yaml                        # reserved (empty)
    ├── strings.json
    └── translations/
        ├── en.json
        └── zh.json
```

### 3.2 Lifecycle

1. User opens "Add Integration" → Hikvision SNMP → ConfigFlow.
2. ConfigFlow performs live SNMP `GET sysDescr` as confirmation step.
3. On success, HA Core creates the entry; `__init__.py::async_setup_entry` instantiates `HikvisionSnmpClient` + `HikvisionDataUpdateCoordinator`.
4. Coordinator's `async_config_entry_first_refresh` runs an initial GETBULK over the 4 subtrees.
5. On success, sensors and binary_sensors register; their `available` property reads `coordinator.last_update_success` + presence of their key in `coordinator.data`.
6. On coordinator `UpdateFailed`, all entities become unavailable and the `online` binary_sensor reports `offline`.
7. On entry removal, coordinator is unregistered and pysnmp engine task is stopped.

---

## 4. SNMP Protocol Details

### 4.1 Auth

- **v2c**: `community` string only. ConfigFlow field `community` (default placeholder; user must set; no default like "public" — security).
- **v3** full auth + privacy:
  - `username`
  - `auth_protocol`: `MD5` / `SHA` / `SHA224` / `SHA256` / `SHA384` / `SHA512`
  - `auth_key` (≥ 8 chars)
  - `privacy_protocol`: `DES` / `3DES` / `AES128` / `AES192` / `AES256`
  - `privacy_key` (≥ 8 chars)
- `version` selector at top of v3 step.

### 4.2 Targets

- UDP transport, default port `161`, timeout `2s`, retries `2`. Constants in `const.py`.
- pysnmp v7 (`pysnmp>=6.2.6,<7.0.0`) used via `pysnmp.hlapi.v3arch.asyncio`.

### 4.3 OID Subtrees Walked

All under Hikvision private enterprise OID `1.3.6.1.4.1.39165`:

| Subtree root | Purpose | Used by |
|---|---|---|
| `.1.1.1` | System info (name, model, firmware, type, uptime, CPU, memory, temperature) | both NVR and IPC |
| `.1.2.1` | Channel table (per-channel name, online, recording, bitrate, resolution) | NVR (multi-channel) + IPC (single channel) |
| `.1.3.1` | Disk table (name, status, capacity, free, temperature) | NVR (HDD) + IPC (SD card) |
| `.1.5.1` | Alarm input state | both |

`device_type` is read from `.1.1.1.4.x` (or set explicitly in ConfigFlow); `auto` mode queries this OID first and uses it to decide which subtrees to walk.

### 4.4 Polling Strategy

- One `GETBULK` per subtree, `max_repetitions=25` (pysnmp v7 default).
- All 4 subtrees polled per coordinator cycle.
- Default `scan_interval = 10s` (configurable 5–300s in OptionsFlow).
- 6–20 hosts × 4 GETBULK / 10s ≈ 1.6 query/s average; trivially within HA capacity.

### 4.5 Error Handling

- `pysnmp` raises `TimeoutError` / `NoSuchInstanceError` / generic `SnmpError` → coordinator logs warning and marks `UpdateFailed`.
- After **3 consecutive failures** coordinator logs a warning (no escalation; out-of-scope for v1).
- After first success following failures, coordinator recovers automatically — `online` binary_sensor transitions to `on`.
- Per-OID missing values (some IPCs omit temperature): the entity registers as `unavailable` rather than failing the whole update.

### 4.6 Value Decoding

| OID return type | Decoded to |
|---|---|
| `OctetString` (model, name, firmware) | `str.decode("utf-8", errors="replace").strip("\x00 ")` |
| `Integer` / `Counter32` (CPU %, memory %, bitrate) | `int(...)` |
| `TimeTicks` (uptime in 1/100s) | `timedelta(seconds = int(value) / 100)` |
| `DisplayString` (rare in Hikvision MIB) | same as OctetString |
| Unknown type | `str(value)` fallback, log debug-level marker |

---

## 5. ConfigFlow (UI Steps)

Step 1: **Device basics**
- `name` (free text, defaults to hostname)
- `host` (IPv4, validated)
- `port` (default 161)
- `device_type`: `auto` / `nvr` / `ipc` (radio)

Step 2: **SNMP credentials**
- `version`: `v2c` / `v3` (radio)
- If v2c: `community` (text, password field, no default)
- If v3: cascade of fields per §4.1

Step 3: **Confirmation**
- Run live `GET sysDescr` against host with entered creds.
- Display result. On failure show error and allow back-nav.

## 5.1 OptionsFlow

- `scan_interval` (int, 5–300, default 10)
- All ConfigFlow Step 2 fields re-editable (community or v3 fields, version can change).
- `device_type` re-editable.

---

## 6. Entity Design

### 6.1 Sensor Entities (per device)

| Entity key | SensorDeviceClass | Unit | Source OID | Both |
|---|---|---|---|---|
| `cpu_usage` | `power_factor` (or custom "%") | % | `.1.1.1.6.x` | ✅ |
| `memory_usage` | same | % | `.1.1.1.7.x` | ✅ |
| `temperature` | `temperature` | °C | `.1.1.1.8.x` | ✅ |
| `uptime` | `duration` | d h m | `.1.1.1.5.x` (TimeTicks) | ✅ |
| `firmware_version` | (none) | text | `.1.1.1.3.x` | ✅ |
| `device_name` | (none) | text | `.1.1.1.2.x` | ✅ |
| `model` | (none) | text | `.1.1.1.1.x` | ✅ |
| `channels_total` | (none) | int | derived from channel table length | ✅ |
| `channels_online` | (none) | int | derived from channel online count | ✅ |
| `channels_recording` | (none) | int | derived from channel recording count | ✅ |

### 6.2 Sensor Entities (per disk / SD card)

Dynamically registered when disk table non-empty. One entity set per disk index.

| Entity key | SensorDeviceClass | Unit | Source OID |
|---|---|---|---|
| `disk_{i}_name` | (none) | text | `.1.3.1.1.x.i` |
| `disk_{i}_capacity` | data_size | GB | `.1.3.1.3.x.i` |
| `disk_{i}_free` | data_size | GB | `.1.3.1.4.x.i` |
| `disk_{i}_temperature` | temperature | °C | `.1.3.1.5.x.i` |

### 6.3 Sensor Entities (per channel)

Dynamically registered when channel table non-empty. One entity set per channel index.

| Entity key | SensorDeviceClass | Unit | Source OID |
|---|---|---|---|
| `channel_{i}_name` | (none) | text | `.1.2.1.1.x.i` |
| `channel_{i}_bitrate` | data_rate | kbps | `.1.2.1.4.x.i` |

### 6.4 Binary Sensor Entities

| Entity key | Meaning | Source |
|---|---|---|
| `online` | Device reachable (any SNMP GET succeeded within last cycle) | derived from coordinator `last_update_success` |
| `recording` | Any channel is recording | derived from channel recording count > 0 |

Note: `motion_detected` was originally planned but the Hikvision MIB does **not** expose per-channel motion flags in the `.1.2.1` channel subtree (motion events are typically delivered via ISAPI HTTP events, not SNMP). Defer to v2 if needed.

### 6.5 device_info

Each entity binds to a `DeviceInfo` constructed in `device_info.py`:

- `identifiers`: `{(DOMAIN, host)}` 
- `manufacturer`: `"Hikvision"`
- `model`: from sysDescr parsed or raw
- `name`: from user-set name + suffix of model
- `sw_version`: from firmware OID

`device_info` shared across all entities of a config entry.

---

## 7. Configuration Defaults

In `const.py`:

```python
DEFAULT_PORT = 161
DEFAULT_SCAN_INTERVAL = 10      # seconds
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300
DEFAULT_REQUEST_TIMEOUT = 2     # seconds, per GETBULK
DEFAULT_RETRIES = 2
SNMP_BULK_MAX_REPETITIONS = 25
DOMAIN = "hikvision_snmp"

# Device type enum (from Hikvision MIB)
DEVICE_TYPE_AUTO = "auto"
DEVICE_TYPE_NVR = "nvr"
DEVICE_TYPE_IPC = "ipc"
DEVICE_TYPE_DVR = "dvr"  # not targeted but tolerated

# v3 auth protocol enum
V3_AUTH_PROTOCOLS = ["MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"]
V3_PRIVACY_PROTOCOLS = ["DES", "3DES", "AES128", "AES192", "AES256"]
```

### 7.1 manifest.json Requirements

Per user preference (stable cross-project rule): use a compatibility range, not a single-point lock.

```json
{
  "domain": "hikvision_snmp",
  "name": "Hikvision SNMP",
  "version": "0.1.0",
  "documentation": "https://github.com/43457/hikvision-snmp",
  "issue_tracker": "https://github.com/43457/hikvision-snmp/issues",
  "codeowners": ["@43457"],
  "config_flow": true,
  "iot_class": "local_polling",
  "integration_type": "device",
  "requirements": ["pysnmp>=6.2.6,<7.0.0"]
}
```

---

## 8. Translation Files

### 8.1 strings.json / en.json

All English text used by config_flow, options_flow, entity names, errors.

### 8.2 zh.json

Chinese (Simplified) translations — required since user's HA locale is `zh`. All UI strings, entity names, error messages, step labels, descriptions mirrored from en.json.

### 8.3 Coverage

- `config.step.basic.title`, `data.name`, `data.host`, `data.port`, `data.device_type`
- `config.step.snmp.title`, `data.version`, `data.community`, `data.username`, `data.auth_protocol`, `data.auth_key`, `data.privacy_protocol`, `data.privacy_key`
- `config.step.confirm.title`, `description`, error placeholders
- `options.step.options_general`, `data.scan_interval`
- `entity.sensor.cpu_usage.name` etc. (one per entity)

---

## 9. Testing & Verification Plan

### 9.1 Pre-deploy Checks

- `python -m py_compile custom_components/hikvision_snmp/*.py` — no syntax errors.
- `python -c "import ast; ast.parse(open(p).read())"` for every Python file.
- Import-time check: `python -c "from custom_components.hikvision_snmp import HIKVISION_SNMP_PLATFORMS"` should succeed against HA Core container (out-of-scope for v1 in CI; manual test).

### 9.2 Live Test (against user's NVR + IPC)

| Step | Expected |
|---|---|
| Add integration → enter NVR IP + v2c community | ConfigFlow step 3 shows sysDescr |
| ConfigFlow completes | Coordinator registers, initial refresh succeeds within 10s |
| HA → Developer Tools → States | NVR device shows sensor.* entities with non-null values |
| HA → Entities → NVR `online` | `on` |
| Disconnect NVR from LAN for 30s | `online` → `offline`, all sensors → `unavailable`, coordinator → `UpdateFailed` |
| Reconnect | Within one cycle `online` → `on`, sensors recover |
| Repeat for one IPC | Same outcomes, single `channel_1` entity |
| OptionsFlow: set scan_interval=5 | Apply; verify polling frequency changes in HA logs |

### 9.3 Failure Path Tests

| Step | Expected |
|---|---|
| ConfigFlow with wrong community | Step 3 error, can re-edit |
| ConfigFlow with wrong v3 key | Step 3 error, can re-edit |
| Add 24 invalid hosts (network unreachable) | ConfigFlow step 3 fails each time, no entry created |

### 9.4 Release Criteria

- All §9.2 and §9.3 pass.
- README.md documents install + ConfigFlow steps + OptionsFlow.
- `docs/oid-reference.md` published with the OID table.
- LICENSE (MIT) present.
- GitHub repo `43457/hikvision-snmp` created and pushed (public, initial tag `v0.1.0`).

---

## 10. Out of Scope (Explicit)

- HTTPS / ISAPI fallback (only when SNMP is unreachable — defer to v2).
- Switch / control entities (reboot, channel on/off).
- PTZ control / preset calls.
- Motion / alarm event history.
- Multi-host dashboards / Lovelace card.
- HACS default repo submission (install via "Custom Repository" only in v1).

---

## 11. Open Questions

None — all blocking decisions resolved 2026-09-23 via brainstorming questionnaire.