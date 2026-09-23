# Hikvision SNMP Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Home Assistant custom component (`hikvision_snmp`) that polls Hikvision NVRs and standalone IPCs over SNMP v2c / v3 and exposes read-only sensor and binary_sensor entities for device health, per-channel status, and disk / SD-card state.

**Architecture:** Per-device `DataUpdateCoordinator` issues four `GETBULK` walks over the Hikvision private enterprise MIB (`.1.3.6.1.4.1.39165`) once per `scan_interval` (default 10s). Coordinator parses returned subtrees into a flat dict; sensor and binary_sensor entities read from this dict. pysnmp v7 asyncio (`pysnmp.hlapi.v3arch.asyncio`) handles all SNMP transport. v2c and v3 auth are both supported at runtime via a config-flow branch.

**Tech Stack:** Python 3.11+, Home Assistant 2025.4+ core APIs, `pysnmp>=6.2.6,<7.0.0` (compatibility range, not single-point lock per user preference), `pytest` + `pytest-asyncio` for unit tests, `git`, `gh` CLI for GitHub push.

## Global Constraints

These apply to every task unless a task explicitly overrides them.

- **Project root**: `C:\Users\43457\Desktop\hikvision-snmp`
- **HA integration path**: `custom_components/hikvision_snmp/` (HA custom_component convention).
- **Domain**: `hikvision_snmp` (used as config key, manifest, entity unique-id prefix).
- **License**: MIT, copyright 2026 `43457`.
- **pysnmp dependency**: `pysnmp>=6.2.6,<7.0.0` — compatibility range, never single-point lock.
- **Python target**: 3.11+ (matches HA 2025.4 baseline).
- **Branch**: `main` (single branch, no develop/release split).
- **Commit cadence**: one commit per task; never commit a broken tree; run `python -m py_compile` on touched files before commit.
- **Strings / translations**: every UI string (config flow labels, error placeholders, entity names) must exist in **both** `en.json` and `zh.json`. Missing translation key is a build break.
- **No write paths**: v1 has zero SNMP SET / control surfaces. The `switch` and `button` platforms are NOT created.
- **Logging**: integration loggers are `custom_components.hikvision_snmp` and `pysnmp`. The latter is registered in `manifest.json` `loggers`.
- **Lint hygiene**: every Python file ends with exactly one trailing newline; no unused imports; type hints on public functions.

---

## File Structure (locked in by this plan)

```
hikvision-snmp/
├── .gitignore                                          # exists (Task 1 adds nothing new)
├── LICENSE                                             # MIT
├── README.md                                           # install + usage
├── hacs.json                                           # HACS schema (name, country, render_readme)
├── docs/
│   ├── superpowers/specs/2026-09-23-hikvision-snmp-design.md  # exists (committed)
│   ├── superpowers/plans/2026-09-23-hikvision-snmp.md        # this file (committed)
│   └── oid-reference.md                                 # public OID table
└── custom_components/hikvision_snmp/
    ├── __init__.py                                      # entry, entity registration
    ├── manifest.json                                    # HA integration manifest
    ├── const.py                                         # OIDs, enums, defaults
    ├── config_flow.py                                   # ConfigFlow + OptionsFlow
    ├── coordinator.py                                   # DataUpdateCoordinator
    ├── snmp_client.py                                   # pysnmp v7 async wrapper
    ├── device_info.py                                   # DeviceInfo factory
    ├── sensor.py                                        # SensorEntity subclasses
    ├── binary_sensor.py                                 # BinarySensorEntity subclasses
    ├── helpers.py                                       # value decoding, OID walk helpers
    ├── services.yaml                                    # empty (reserved)
    ├── strings.json                                     # English source-of-truth
    └── translations/
        ├── en.json                                      # English
        └── zh.json                                      # Simplified Chinese
```

---

## Task 1: Project Scaffolding (LICENSE + hacs.json + README skeleton)

**Files:**
- Create: `LICENSE`
- Create: `hacs.json`
- Create: `README.md`

**Interfaces:**
- Produces: a repo root that HA can validate (`hacs.json` shape) and that GitHub can render (`LICENSE`, `README.md`).

- [ ] **Step 1: Write `LICENSE` (MIT)**

Copy this verbatim into `LICENSE`:

```
MIT License

Copyright (c) 2026 43457

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Write `hacs.json`**

```json
{
  "name": "Hikvision SNMP",
  "render_readme": true,
  "country": ["CN"]
}
```

- [ ] **Step 3: Write `README.md` skeleton (placeholder, replaced in Task 12)**

```markdown
# Hikvision SNMP

Home Assistant custom component that polls Hikvision NVRs and IPCs over SNMP v2c / v3.

> Status: scaffolding in progress. Full content lands in Task 12.
```

- [ ] **Step 4: Verify files exist and commit**

Run from project root:
```bash
cd C:\Users\43457\Desktop\hikvision-snmp
ls LICENSE hacs.json README.md
git add LICENSE hacs.json README.md
git commit -m "chore: scaffold project LICENSE, hacs.json, README placeholder"
```

Expected: 3 files committed; `git log --oneline` shows 2 commits (this + the spec commit).

---

## Task 2: `manifest.json` + `const.py`

**Files:**
- Create: `custom_components/hikvision_snmp/manifest.json`
- Create: `custom_components/hikvision_snmp/const.py`

**Interfaces:**
- `const.py` exports:
  - `DOMAIN = "hikvision_snmp"`
  - `MANUFACTURER = "Hikvision"`
  - `DEFAULT_PORT = 161`
  - `DEFAULT_SCAN_INTERVAL = 10`
  - `MIN_SCAN_INTERVAL = 5`
  - `MAX_SCAN_INTERVAL = 300`
  - `DEFAULT_REQUEST_TIMEOUT = 2`
  - `DEFAULT_RETRIES = 2`
  - `BULK_MAX_REPETITIONS = 25`
  - `DEVICE_TYPE_AUTO = "auto"`, `DEVICE_TYPE_NVR = "nvr"`, `DEVICE_TYPE_IPC = "ipc"`, `DEVICE_TYPE_DVR = "dvr"`
  - `HIKVISION_PRIVATE_MIB_ROOT = "1.3.6.1.4.1.39165"`
  - All subtree roots as module-level `OID_*` constants (see code below)
  - `CONF_*` constants for every ConfigFlow field name
  - `V3_AUTH_PROTOCOLS`, `V3_PRIVACY_PROTOCOLS` (lists)
  - `HIKVISION_FAMILY_AUTO_NVR_TABLE`, `HIKVISION_FAMILY_AUTO_IPC_TABLE` — dicts mapping subtree root → list of leaf OID suffixes to extract (used by coordinator).
- These symbols are imported by `__init__.py`, `config_flow.py`, `coordinator.py`, `sensor.py`, `binary_sensor.py`, `device_info.py`.

- [ ] **Step 1: Write `manifest.json`**

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
  "loggers": ["pysnmp"],
  "requirements": ["pysnmp>=6.2.6,<7.0.0"]
}
```

- [ ] **Step 2: Write `const.py`**

```python
"""Constants for Hikvision SNMP integration."""

from __future__ import annotations

DOMAIN = "hikvision_snmp"
MANUFACTURER = "Hikvision"

# ---- Polling defaults ----

DEFAULT_PORT = 161
DEFAULT_SCAN_INTERVAL = 10  # seconds
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300
DEFAULT_REQUEST_TIMEOUT = 2  # seconds per request
DEFAULT_RETRIES = 2
BULK_MAX_REPETITIONS = 25

# ---- Device-type enum (ConfigFlow choices) ----

DEVICE_TYPE_AUTO = "auto"
DEVICE_TYPE_NVR = "nvr"
DEVICE_TYPE_IPC = "ipc"
DEVICE_TYPE_DVR = "dvr"
DEVICE_TYPES = [DEVICE_TYPE_AUTO, DEVICE_TYPE_NVR, DEVICE_TYPE_IPC, DEVICE_TYPE_DVR]

# ---- Hikvision enterprise OID root (private MIB) ----

HIKVISION_PRIVATE_MIB_ROOT = "1.3.6.1.4.1.39165"

# Subtrees walked each poll
OID_SYSTEM = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1"   # system info (name/model/firmware/uptime/cpu/mem/temp)
OID_CHANNEL = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.2.1"  # per-channel table
OID_DISK = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.3.1"     # disk / SD-card table
OID_ALARM = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.5.1"    # alarm input subtree (reserved for v2)

# ---- OID table: which leaf suffixes under each subtree hold which metric ----
# Format: {subtree_root: {metric_key: leaf_oid_prefix_under_subtree}}
# The full OID is constructed as f"{subtree_root}.{leaf_prefix}.{instance}" or
# f"{subtree_root}.{leaf_prefix}" for scalar leaves.

SYSTEM_OIDS: dict[str, str] = {
    "model": "1.1",            # .1.3.6.1.4.1.39165.1.1.1.1.x
    "device_name": "1.2",
    "firmware": "1.3",
    "device_type_code": "1.4", # integer enum code; 1=NVR, 2=DVR, 3=IPC
    "uptime": "1.5",           # TimeTicks (1/100 s)
    "cpu": "1.6",              # percent
    "memory": "1.7",           # percent
    "temperature": "1.8",      # celsius
}

CHANNEL_OIDS: dict[str, str] = {
    "name": "1.1",
    "online": "1.2",           # 1=online, 0=offline
    "recording": "1.3",        # 1=recording, 0=not
    "bitrate": "1.4",          # kbps
    "resolution": "1.5",
}

DISK_OIDS: dict[str, str] = {
    "name": "1.1",
    "status": "1.2",           # integer enum (1=normal, 2=idle, etc.)
    "capacity": "1.3",         # MB
    "free": "1.4",             # MB
    "temperature": "1.5",      # celsius
}

# ---- Config-flow field names ----

CONF_NAME = "name"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_DEVICE_TYPE = "device_type"
CONF_VERSION = "version"          # "v2c" or "v3"
CONF_COMMUNITY = "community"      # v2c only
CONF_USERNAME = "username"        # v3 only
CONF_AUTH_PROTOCOL = "auth_protocol"
CONF_AUTH_KEY = "auth_key"
CONF_PRIVACY_PROTOCOL = "privacy_protocol"
CONF_PRIVACY_KEY = "privacy_key"
CONF_SCAN_INTERVAL = "scan_interval"

SNMP_VERSIONS = ["v2c", "v3"]

V3_AUTH_PROTOCOLS = ["MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"]
V3_PRIVACY_PROTOCOLS = ["DES", "3DES", "AES128", "AES192", "AES256"]

# ---- Hikvision device-type code → string mapping (read from .1.1.1.4) ----

DEVICE_TYPE_CODE_MAP: dict[int, str] = {
    1: DEVICE_TYPE_NVR,
    2: DEVICE_TYPE_DVR,
    3: DEVICE_TYPE_IPC,
}
```

- [ ] **Step 3: Compile check**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m py_compile custom_components/hikvision_snmp/const.py
```

Expected: no output (success). If error, fix and rerun.

- [ ] **Step 4: Commit**

```bash
git add custom_components/hikvision_snmp/manifest.json custom_components/hikvision_snmp/const.py
git commit -m "feat: add manifest.json and const.py (OID tables, defaults)"
```

---

## Task 3: `helpers.py` + unit tests (pure-function module, easy to TDD)

**Files:**
- Create: `custom_components/hikvision_snmp/helpers.py`
- Create: `tests/test_helpers.py`

**Interfaces:**
- `decode_octet_string(value: object) -> str` — returns `value.decode("utf-8", errors="replace").strip("\x00 ")` if value is bytes; returns `str(value)` for str; returns `""` for None.
- `parse_uptime(value: int) -> timedelta` — value is TimeTicks in 1/100 s.
- `parse_int(value: object) -> int | None` — returns `int(value)` or None if conversion fails or value is None.
- `parse_bool(value: object) -> bool | None` — `1` → True, `0` → False, else None.
- `decode_walk_results(raw: list[tuple[str, object]], oid_root: str, oid_map: dict[str, str]) -> dict[str, dict[str, object]]` — given `(oid_string, value)` pairs from GETBULK, returns nested dict `{metric_key: {instance: value}}`. OIDs must start with `oid_root`; metric chosen by next component matching a key in `oid_map`. Anything outside `oid_root` is silently dropped.
- All functions must accept `None` input without raising; helpers must be usable from both sync tests and async coordinator code.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_helpers.py
from datetime import timedelta

from custom_components.hikvision_snmp.helpers import (
    decode_octet_string,
    decode_walk_results,
    parse_bool,
    parse_int,
    parse_uptime,
)


def test_decode_octet_string_bytes():
    assert decode_octet_string(b"Hello\x00World  ") == "HelloWorld"


def test_decode_octet_string_str():
    assert decode_octet_string("plain") == "plain"


def test_decode_octet_string_none():
    assert decode_octet_string(None) == ""


def test_decode_octet_string_bad_bytes():
    assert decode_octet_string(b"\xff\xfe\xfd")  # must not raise; returns something


def test_parse_uptime_seconds():
    # 100 * 1/100 s = 1 s
    assert parse_uptime(100) == timedelta(seconds=1)


def test_parse_uptime_days():
    # 8640000 = 1 day
    assert parse_uptime(8640000) == timedelta(days=1)


def test_parse_uptime_zero():
    assert parse_uptime(0) == timedelta(0)


def test_parse_int_valid():
    assert parse_int("42") == 42
    assert parse_int(42) == 42
    assert parse_int(42.0) == 42


def test_parse_int_invalid_returns_none():
    assert parse_int("abc") is None
    assert parse_int(None) is None


def test_parse_bool_truthy():
    assert parse_bool(1) is True
    assert parse_bool("1") is True


def test_parse_bool_falsy():
    assert parse_bool(0) is False
    assert parse_bool("0") is False


def test_parse_bool_unknown():
    assert parse_bool(7) is None
    assert parse_bool(None) is None


def test_decode_walk_results_basic():
    # Simulate a GETBULK over 1.3.6.1.4.1.39165.1.1.1 subtree
    raw = [
        ("1.3.6.1.4.1.39165.1.1.1.1.0", "DS-7608N-I2"),
        ("1.3.6.1.4.1.39165.1.1.1.3.0", "V3.4.106"),
        ("1.3.6.1.4.1.39165.1.1.1.6.0", 12),
    ]
    out = decode_walk_results(raw, "1.3.6.1.4.1.39165.1.1.1", {
        "model": "1.1",
        "firmware": "1.3",
        "cpu": "1.6",
    })
    assert out["model"]["0"] == "DS-7608N-I2"
    assert out["firmware"]["0"] == "V3.4.106"
    assert out["cpu"]["0"] == 12


def test_decode_walk_results_channel_table():
    raw = [
        ("1.3.6.1.4.1.39165.1.2.1.1.1", "Cam1"),
        ("1.3.6.1.4.1.39165.1.2.1.1.2", "Cam2"),
        ("1.3.6.1.4.1.39165.1.2.1.4.1", 2048),
        ("1.3.6.1.4.1.39165.1.2.1.4.2", 4096),
    ]
    out = decode_walk_results(raw, "1.3.6.1.4.1.39165.1.2.1", {
        "name": "1.1",
        "bitrate": "1.4",
    })
    assert out["name"] == {"1": "Cam1", "2": "Cam2"}
    assert out["bitrate"] == {"1": 2048, "2": 4096}


def test_decode_walk_results_filters_other_subtrees():
    raw = [
        ("1.3.6.1.4.1.39165.1.3.1.1.1", "HDD1"),  # disk subtree — must be dropped
        ("1.3.6.1.4.1.39165.1.1.1.3.0", "V1"),
    ]
    out = decode_walk_results(raw, "1.3.6.1.4.1.39165.1.1.1", {"firmware": "1.3"})
    assert out == {"firmware": {"0": "V1"}}
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m pytest tests/test_helpers.py -v
```

Expected: every test fails with `ModuleNotFoundError` or `ImportError` (helpers.py doesn't exist yet).

- [ ] **Step 3: Implement `helpers.py`**

```python
"""Pure helpers for decoding SNMP responses."""

from __future__ import annotations

from datetime import timedelta
from typing import Any


def decode_octet_string(value: Any) -> str:
    """Decode OctetString from pysnmp into a clean string.

    Handles bytes, str, and None without raising.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00 ")
    if isinstance(value, str):
        return value.strip("\x00 ")
    return str(value)


def parse_uptime(value: Any) -> timedelta:
    """Parse SNMP TimeTicks (1/100 s) into a timedelta."""
    if value is None:
        return timedelta(0)
    try:
        return timedelta(seconds=int(value) / 100)
    except (TypeError, ValueError):
        return timedelta(0)


def parse_int(value: Any) -> int | None:
    """Best-effort integer conversion; None on failure or None input."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value: Any) -> bool | None:
    """Map 1/0 to True/False; return None for unknown or None."""
    if value is None:
        return None
    parsed = parse_int(value)
    if parsed in (0, 1):
        return bool(parsed)
    return None


def decode_walk_results(
    raw: list[tuple[str, Any]],
    oid_root: str,
    oid_map: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Group GETBULK results by metric key.

    Each raw tuple is `(oid_string, value)`. OIDs not under `oid_root` are
    dropped. For each remaining OID, the next component (after the root)
    is matched against `oid_map` values; the trailing component is the
    instance index (e.g. channel number, disk number, or "0" for scalars).

    Returns: `{metric_key: {instance_str: value}}`.
    """
    root_parts = oid_root.split(".")
    out: dict[str, dict[str, Any]] = {}

    # Reverse map: leaf_prefix → metric_key, for fast lookup
    leaf_to_key = {prefix: key for key, prefix in oid_map.items()}

    for oid_str, value in raw:
        parts = oid_str.split(".")
        if parts[: len(root_parts)] != root_parts:
            continue
        rest = parts[len(root_parts):]
        # rest looks like ["1", "1", "0"] or ["1", "6", "0"]
        # The first component of rest matches a leaf prefix in oid_map;
        # the remainder is instance info (last element is the index for tables).
        if len(rest) < 2:
            continue
        leaf_prefix = rest[0]
        instance = ".".join(rest[1:])
        metric_key = leaf_to_key.get(leaf_prefix)
        if metric_key is None:
            continue
        out.setdefault(metric_key, {})[instance] = value

    return out
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m pytest tests/test_helpers.py -v
```

Expected: all 13 tests pass.

- [ ] **Step 5: Commit**

```bash
git add custom_components/hikvision_snmp/helpers.py tests/test_helpers.py
git commit -m "feat: add helpers.py with value-decode utilities (13 unit tests)"
```

---

## Task 4: `snmp_client.py` (pysnmp v7 async wrapper)

**Files:**
- Create: `custom_components/hikvision_snmp/snmp_client.py`

**Interfaces:**
- `class HikvisionSnmpClient`:
  - `__init__(self, hass, host, port, version, auth)` where `auth` is a dict:
    - v2c: `{"community": "..."}`
    - v3: `{"username": "...", "auth_protocol": "SHA", "auth_key": "...", "privacy_protocol": "AES128", "priv_key": "..."}`
  - `async def get(self, oid: str) -> Any | None` — single GET, returns decoded value or None on timeout / noSuchInstance.
  - `async def walk(self, oid_root: str, max_repetitions: int = BULK_MAX_REPETITIONS) -> list[tuple[str, Any]]` — GETBULK walk, returns `(oid_string, value)` pairs.
  - `async def close(self) -> None` — stops the underlying SnmpEngine dispatcher.
- Uses `pysnmp.hlapi.v3arch.asyncio` (PySNMP 7+ API).
- Auth-data factory: `usmHMACSHAAuthProtocol` / `usmAesCfb128Protocol` etc., mapping from string protocol names.

- [ ] **Step 1: Write `snmp_client.py`**

```python
"""Async pysnmp v7 wrapper for Hikvision devices."""

from __future__ import annotations

import logging
from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    bulk_cmd,
    get_cmd,
    usm3DESEDEPrivProtocol,
    usmAesCfb128Protocol,
    usmAesCfb192Protocol,
    usmAesCfb256Protocol,
    usmDESPrivProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmHMACSHAA2Protocol,
    usmHMACSHA224Protocol,
    usmHMACSHA256Protocol,
    usmHMACSHA384Protocol,
    usmHMACSHA512Protocol,
    usmNoAuthProtocol,
    usmNoPrivProtocol,
)
from pysnmp.proto.api import v2c as api_v2c
from pysnmp.proto.rfc1905 import NoSuchObject, NoSuchInstance

from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_PORT,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRIES,
)

_LOGGER = logging.getLogger(__name__)

# ---- Protocol name → pysnmp protocol-object maps ----

_AUTH_PROTOCOLS = {
    "MD5": usmHMACMD5AuthProtocol,
    "SHA": usmHMACSHAAuthProtocol,
    "SHA224": usmHMACSHA224Protocol,
    "SHA256": usmHMACSHA256Protocol,
    "SHA384": usmHMACSHA384Protocol,
    "SHA512": usmHMACSHA512Protocol,
    # SHA2 (alias used by some firmware)
    "SHA2": usmHMACSHAA2Protocol,
}

_PRIVACY_PROTOCOLS = {
    "DES": usmDESPrivProtocol,
    "3DES": usm3DESEDEPrivProtocol,
    "AES128": usmAesCfb128Protocol,
    "AES192": usmAesCfb192Protocol,
    "AES256": usmAesCfb256Protocol,
}


def _build_auth(version: str, auth: dict[str, str]):
    """Build pysnmp auth-data object from the dict stored in config entry."""
    if version == "v2c":
        return CommunityData(auth["community"], mpModel=1)
    if version == "v3":
        auth_proto = _AUTH_PROTOCOLS.get(auth.get("auth_protocol", "SHA"), usmHMACSHAAuthProtocol)
        priv_proto = _PRIVACY_PROTOCOLS.get(auth.get("privacy_protocol", "AES128"), usmAesCfb128Protocol)
        return UsmUserData(
            userName=auth["username"],
            authKey=auth["auth_key"],
            authProtocol=auth_proto,
            privKey=auth["priv_key"],
            privProtocol=priv_proto,
        )
    raise ValueError(f"Unsupported SNMP version: {version}")


class HikvisionSnmpError(Exception):
    """Raised when an SNMP request fails (timeout, decode error, etc.)."""


class HikvisionSnmpClient:
    """Per-host async SNMP client wrapping pysnmp v7."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int = DEFAULT_PORT,
        version: str = "v2c",
        auth: dict[str, str] | None = None,
    ) -> None:
        self._hass = hass
        self._host = host
        self._port = port
        self._version = version
        self._auth = auth or {}
        self._engine = SnmpEngine()
        self._auth_data = _build_auth(version, self._auth)
        self._target = UdpTransportTarget(
            (host, port), timeout=DEFAULT_REQUEST_TIMEOUT, retries=DEFAULT_RETRIES
        )

    @property
    def host(self) -> str:
        return self._host

    async def get(self, oid: str) -> Any | None:
        """Single GET. Returns decoded python value or None if OID missing/timeout."""
        var_bind_list = await self._do_get([ObjectType(ObjectIdentity(oid))])
        if not var_bind_list:
            return None
        return _decode_value(var_bind_list[0][1])

    async def walk(self, oid_root: str, max_repetitions: int = 25) -> list[tuple[str, Any]]:
        """GETBULK walk. Returns [(oid_str, value), ...] for OIDs under oid_root."""
        results: list[tuple[str, Any]] = []
        current = ObjectIdentity(oid_root)
        ctx = ContextData()
        while True:
            try:
                var_binds = await self._do_bulk(current, max_repetitions)
            except HikvisionSnmpError:
                break
            if not var_binds:
                break
            stop = True
            for var_bind in var_binds:
                oid_str = str(var_bind[0])
                value = _decode_value(var_bind[1])
                if not oid_str.startswith(oid_root):
                    return results
                results.append((oid_str, value))
                current = ObjectIdentity(oid_str)
                stop = False
            if stop:
                break
        return results

    async def close(self) -> None:
        """Tear down the SNMP engine dispatcher."""
        self._engine.close_dispatcher()

    # ---- internal ----

    async def _do_get(self, var_binds_in) -> list:
        try:
            error_indication, error_status, _, var_binds = await get_cmd(
                self._engine, self._auth_data, self._target, ContextData(), *var_binds_in
            )
        except Exception as exc:  # noqa: BLE001
            raise HikvisionSnmpError(f"get failed: {exc}") from exc
        if error_indication:
            raise HikvisionSnmpError(f"get indication: {error_indication}")
        if error_status:
            raise HikvisionSnmpError(f"get status: {error_status.prettyPrint()}")
        return [tuple(vb) for vb in var_binds]

    async def _do_bulk(self, base_oid: ObjectIdentity, max_repetitions: int) -> list:
        try:
            error_indication, error_status, _, var_binds = await bulk_cmd(
                self._engine,
                self._auth_data,
                self._target,
                ContextData(),
                0,  # non-repeaters
                max_repetitions,
                ObjectType(base_oid),
                lexicographicMode=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise HikvisionSnmpError(f"bulk failed: {exc}") from exc
        if error_indication:
            raise HikvisionSnmpError(f"bulk indication: {error_indication}")
        if error_status:
            raise HikvisionSnmpError(f"bulk status: {error_status.prettyPrint()}")
        return [tuple(vb) for vb in var_binds]


def _decode_value(value: Any) -> Any:
    """Convert pysnmp value objects to plain python types."""
    # NoSuchInstance / NoSuchObject → None
    if isinstance(value, (NoSuchInstance, NoSuchObject)):
        return None
    # Already a primitive
    if isinstance(value, (int, float, str, bytes, bool)) or value is None:
        return value
    # pysnmp OctetString, Integer, Counter64, etc. — use prettyPrint for readability
    try:
        return api_v2c.ObjectName(value) if False else value.prettyPrint()
    except Exception:  # noqa: BLE001
        return str(value)
```

- [ ] **Step 2: Compile-check and commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m py_compile custom_components/hikvision_snmp/snmp_client.py
git add custom_components/hikvision_snmp/snmp_client.py
git commit -m "feat: add snmp_client.py wrapping pysnmp v7 (v2c + v3 auth)"
```

Expected: compile passes; pysnmp is not installed at this point (HA installs it on first run via manifest requirements). If `python -m py_compile` fails on the `from pysnmp...` lines because pysnmp isn't installed locally, that's expected — skip the compile check (or `pip install pysnmp` for local dev).

---

## Task 5: `device_info.py`

**Files:**
- Create: `custom_components/hikvision_snmp/device_info.py`

**Interfaces:**
- `async def async_identify_device(client: HikvisionSnmpClient) -> dict[str, Any]` — runs a single GETBULK on the system subtree and returns a flat dict:
  ```python
  {
    "model": "DS-7608N-I2 / IPC",
    "device_name": "...",
    "firmware": "V3.4.106",
    "device_type_code": 1,  # raw int from OID; mapped by caller
    "uptime_raw": 123456,
    "cpu": 12,
    "memory": 30,
    "temperature": 45,
  }
  ```
  Missing values become `None`.
- `def build_device_info(entry_id: str, host: str, identification: dict) -> DeviceInfo` — returns HA `DeviceInfo` with manufacturer Hikvision, model from identification, name from config entry's title, sw_version from firmware.

- [ ] **Step 1: Write `device_info.py`**

```python
"""Identify a Hikvision device and build its DeviceInfo descriptor."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DOMAIN,
    HIKVISION_PRIVATE_MIB_ROOT,
    MANUFACTURER,
    SYSTEM_OIDS,
)
from .helpers import decode_octet_string, decode_walk_results, parse_int
from .snmp_client import HikvisionSnmpClient


async def async_identify_device(client: HikvisionSnmpClient) -> dict[str, Any]:
    """GETBULK the system subtree and return a flat dict of scalar values."""
    raw = await client.walk(f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1", max_repetitions=10)
    decoded = decode_walk_results(raw, f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1", SYSTEM_OIDS)
    scalar_keys = ["model", "device_name", "firmware", "device_type_code",
                   "uptime", "cpu", "memory", "temperature"]
    out: dict[str, Any] = {}
    for key in scalar_keys:
        entry = decoded.get(key, {})
        if not entry:
            out[key] = None
            continue
        # System scalars are typically instance "0"; take the first if "0" absent.
        raw_value = entry.get("0") or next(iter(entry.values()), None)
        if key in ("model", "device_name", "firmware"):
            out[key] = decode_octet_string(raw_value)
        else:
            out[key] = parse_int(raw_value)
    return out


def build_device_info(entry_id: str, host: str, identification: dict[str, Any], name: str) -> DeviceInfo:
    """Build an HA DeviceInfo for a Hikvision device."""
    model = identification.get("model") or "Hikvision Device"
    firmware = identification.get("firmware")
    return DeviceInfo(
        identifiers={(DOMAIN, host)},
        manufacturer=MANUFACTURER,
        model=model,
        name=name,
        sw_version=firmware,
        configuration_url=f"http://{host}",
    )
```

- [ ] **Step 2: Compile and commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m py_compile custom_components/hikvision_snmp/device_info.py
git add custom_components/hikvision_snmp/device_info.py
git commit -m "feat: add device_info.py (system subtree identification + DeviceInfo)"
```

---

## Task 6: `coordinator.py`

**Files:**
- Create: `custom_components/hikvision_snmp/coordinator.py`

**Interfaces:**
- `class HikvisionDataUpdateCoordinator(DataUpdateCoordinator[dict])`:
  - `__init__(self, hass, client, scan_interval, identification)` — stores client, sets update_interval.
  - `async def _async_update_data(self) -> dict[str, Any]`:
    - Walks OID_SYSTEM (scalars), OID_CHANNEL, OID_DISK subtrees.
    - Decodes each via `decode_walk_results`.
    - Returns a flat dict shaped like:
      ```python
      {
        "identification": { "model": ..., "firmware": ..., ... },
        "channels": { "name": {i: ...}, "online": {...}, "recording": {...}, "bitrate": {...}, "resolution": {...} },
        "disks":    { "name": {...}, "status": {...}, "capacity": {...}, "free": {...}, "temperature": {...} },
        "online": True,  # marker; coordinator.last_update_success also drives it
      }
      ```
    - On SNMP timeout/error: log warning and raise `UpdateFailed`.
  - `available` property — derived from `last_update_success` (HA core handles).

- [ ] **Step 1: Write `coordinator.py`**

```python
"""DataUpdateCoordinator that polls a Hikvision device every scan_interval."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BULK_MAX_REPETITIONS,
    CHANNEL_OIDS,
    DEFAULT_SCAN_INTERVAL,
    DISK_OIDS,
    HIKVISION_PRIVATE_MIB_ROOT,
)
from .helpers import decode_walk_results
from .snmp_client import HikvisionSnmpClient, HikvisionSnmpError

_LOGGER = logging.getLogger(__name__)


class HikvisionDataUpdateCoordinator(DataUpdateCoordinator):
    """Per-device coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: HikvisionSnmpClient,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        identification: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{client.host}_hikvision",
            update_interval=timedelta(seconds=scan_interval),
        )
        self._client = client
        self._identification = identification or {}

    @property
    def identification(self) -> dict[str, Any]:
        return self._identification

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            sys_raw = await self._client.walk(
                f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1", max_repetitions=BULK_MAX_REPETITIONS
            )
            ch_raw = await self._client.walk(
                f"{HIKVISION_PRIVATE_MIB_ROOT}.1.2.1", max_repetitions=BULK_MAX_REPETITIONS
            )
            disk_raw = await self._client.walk(
                f"{HIKVISION_PRIVATE_MIB_ROOT}.1.3.1", max_repetitions=BULK_MAX_REPETITIONS
            )
        except HikvisionSnmpError as exc:
            raise UpdateFailed(f"SNMP walk failed: {exc}") from exc

        sys_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1"
        ch_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.2.1"
        disk_root = f"{HIKVISION_PRIVATE_MIB_ROOT}.1.3.1"

        # Re-extract system scalars (they may have changed since first identification)
        sys_decoded = decode_walk_results(sys_raw, sys_root, {
            "model": "1.1", "device_name": "1.2", "firmware": "1.3",
            "device_type_code": "1.4", "uptime": "1.5",
            "cpu": "1.6", "memory": "1.7", "temperature": "1.8",
        })

        return {
            "identification": sys_decoded,
            "channels": decode_walk_results(ch_raw, ch_root, CHANNEL_OIDS),
            "disks": decode_walk_results(disk_raw, disk_root, DISK_OIDS),
        }
```

- [ ] **Step 2: Compile and commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m py_compile custom_components/hikvision_snmp/coordinator.py
git add custom_components/hikvision_snmp/coordinator.py
git commit -m "feat: add coordinator.py (DataUpdateCoordinator over 3 SNMP subtrees)"
```

---

## Task 7: `sensor.py` (static + dynamic per-disk + per-channel entities)

**Files:**
- Create: `custom_components/hikvision_snmp/sensor.py`

**Interfaces:**
- `async def async_setup_entry(hass, entry, async_add_entities)` — reads coordinator.data and creates entities:
  - 8 static entities: cpu_usage, memory_usage, temperature, uptime, firmware_version, device_name, model, channels_total, channels_online, channels_recording (10 total — see below).
  - 4 entities per detected disk: disk_{n}_name, disk_{n}_capacity, disk_{n}_free, disk_{n}_temperature.
  - 2 entities per detected channel: channel_{n}_name, channel_{n}_bitrate.
- Each entity inherits from `CoordinatorEntity[HikvisionDataUpdateCoordinator]` and `SensorEntity`. Reads from `coordinator.data` via `native_value`.
- Entity unique_id = `f"{entry.entry_id}_{metric_key}"` or `f"{entry.entry_id}_disk_{i}_name"` etc.

- [ ] **Step 1: Write `sensor.py`**

```python
"""Sensor platform for Hikvision SNMP."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfDataSize,
    UnitOfInformation,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HikvisionDataUpdateCoordinator
from .helpers import decode_octet_string, parse_int, parse_uptime


@dataclass(frozen=True)
class HikvisionSensorDescription(SensorEntityDescription):
    """Description with a value extractor."""

    value_fn: Callable[[dict[str, Any]], Any] = lambda _: None


# ---- Static sensors ----

SENSORS: tuple[HikvisionSensorDescription, ...] = (
    HikvisionSensorDescription(
        key="cpu_usage",
        name="CPU Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_int(d.get("identification", {}).get("cpu", {}).get("0")),
    ),
    HikvisionSensorDescription(
        key="memory_usage",
        name="Memory Usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_int(d.get("identification", {}).get("memory", {}).get("0")),
    ),
    HikvisionSensorDescription(
        key="temperature",
        name="Temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: parse_int(d.get("identification", {}).get("temperature", {}).get("0")),
    ),
    HikvisionSensorDescription(
        key="uptime",
        name="Uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: int(parse_uptime(
            parse_int(d.get("identification", {}).get("uptime", {}).get("0"))
        ).total_seconds()),
    ),
    HikvisionSensorDescription(
        key="firmware_version",
        name="Firmware Version",
        value_fn=lambda d: decode_octet_string(
            d.get("identification", {}).get("firmware", {}).get("0")
        ),
    ),
    HikvisionSensorDescription(
        key="device_name",
        name="Device Name",
        value_fn=lambda d: decode_octet_string(
            d.get("identification", {}).get("device_name", {}).get("0")
        ),
    ),
    HikvisionSensorDescription(
        key="model",
        name="Model",
        value_fn=lambda d: decode_octet_string(
            d.get("identification", {}).get("model", {}).get("0")
        ),
    ),
    HikvisionSensorDescription(
        key="channels_total",
        name="Channels Total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(d.get("channels", {}).get("name", {})),
    ),
    HikvisionSensorDescription(
        key="channels_online",
        name="Channels Online",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(
            1 for v in d.get("channels", {}).get("online", {}).values()
            if parse_int(v) == 1
        ),
    ),
    HikvisionSensorDescription(
        key="channels_recording",
        name="Channels Recording",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(
            1 for v in d.get("channels", {}).get("recording", {}).values()
            if parse_int(v) == 1
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator: HikvisionDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Wait for first refresh so we know what disks/channels exist
    await coordinator.async_config_entry_first_refresh()
    data = coordinator.data or {}

    entities: list[SensorEntity] = []

    # Static sensors
    for desc in SENSORS:
        entities.append(HikvisionSensor(coordinator, entry, desc))

    # Per-disk sensors
    for disk_idx in sorted(data.get("disks", {}).get("name", {}).keys()):
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "name", "Disk Name", None))
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "capacity", "Capacity", UnitOfDataSize.GIGABYTES))
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "free", "Free", UnitOfDataSize.GIGABYTES))
        entities.append(HikvisionDiskSensor(coordinator, entry, disk_idx, "temperature", "Temperature", UnitOfTemperature.CELSIUS))

    # Per-channel sensors
    for ch_idx in sorted(data.get("channels", {}).get("name", {}).keys(), key=lambda x: int(x)):
        entities.append(HikvisionChannelSensor(coordinator, entry, ch_idx, "name", "Name", None))
        entities.append(HikvisionChannelSensor(coordinator, entry, ch_idx, "bitrate", "Bitrate", UnitOfInformation.KILOBITS_PER_SECOND))

    async_add_entities(entities)


class HikvisionSensor(CoordinatorEntity[HikvisionDataUpdateCoordinator], SensorEntity):
    """Static sensor entity."""

    _attr_has_entity_name = True
    entity_description: HikvisionSensorDescription

    def __init__(self, coordinator, entry, description: HikvisionSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = coordinator.device_info  # set in __init__.py via hass.data

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class _DynamicTableSensor(CoordinatorEntity[HikvisionDataUpdateCoordinator], SensorEntity):
    """Base for per-row sensors (disk / channel)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, idx: str, metric_key: str, name_suffix: str, unit: str | None) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._metric_key = metric_key
        self._attr_name = name_suffix
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = f"{entry.entry_id}_{self._table_name}_{idx}_{metric_key}"
        self._attr_device_info = coordinator.device_info

    @property
    def _table_name(self) -> str:
        raise NotImplementedError

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        table = self.coordinator.data.get(self._table_name, {})
        raw = table.get(self._metric_key, {}).get(self._idx)
        return self._decode(raw)

    def _decode(self, raw):
        raise NotImplementedError


class HikvisionDiskSensor(_DynamicTableSensor):
    @property
    def _table_name(self) -> str:
        return "disks"

    def _decode(self, raw):
        if raw is None:
            return None
        if self._metric_key == "name":
            return decode_octet_string(raw)
        if self._metric_key in ("capacity", "free"):
            mb = parse_int(raw)
            return round(mb / 1024, 2) if mb is not None else None
        if self._metric_key == "temperature":
            return parse_int(raw)
        return None


class HikvisionChannelSensor(_DynamicTableSensor):
    @property
    def _table_name(self) -> str:
        return "channels"

    def _decode(self, raw):
        if raw is None:
            return None
        if self._metric_key == "name":
            return decode_octet_string(raw)
        if self._metric_key == "bitrate":
            return parse_int(raw)
        return None
```

- [ ] **Step 2: Compile and commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m py_compile custom_components/hikvision_snmp/sensor.py
git add custom_components/hikvision_snmp/sensor.py
git commit -m "feat: add sensor.py (10 static + per-disk + per-channel entities)"
```

---

## Task 8: `binary_sensor.py`

**Files:**
- Create: `custom_components/hikvision_snmp/binary_sensor.py`

**Interfaces:**
- `async def async_setup_entry(hass, entry, async_add_entities)` — registers 2 entities:
  - `online` — device_class `connectivity`, `is_on = coordinator.last_update_success`.
  - `recording` — `is_on = any(channel recording == 1)`.
- Both inherit `CoordinatorEntity[HikvisionDataUpdateCoordinator]` and `BinarySensorEntity`.

- [ ] **Step 1: Write `binary_sensor.py`**

```python
"""Binary sensor platform for Hikvision SNMP."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HikvisionDataUpdateCoordinator
from .helpers import parse_int


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HikvisionDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([
        HikvisionOnlineBinarySensor(coordinator, entry),
        HikvisionRecordingBinarySensor(coordinator, entry),
    ])


class _Base(CoordinatorEntity[HikvisionDataUpdateCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info


class HikvisionOnlineBinarySensor(_Base):
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_unique_id = "{}_online".format(entry.entry_id) if False else None

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_online"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.last_update_success


class HikvisionRecordingBinarySensor(_Base):
    _attr_name = "Recording"
    _attr_unique_id = None  # set in __init__

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_recording"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        rec = self.coordinator.data.get("channels", {}).get("recording", {})
        return any(parse_int(v) == 1 for v in rec.values())
```

- [ ] **Step 2: Compile and commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m py_compile custom_components/hikvision_snmp/binary_sensor.py
git add custom_components/hikvision_snmp/binary_sensor.py
git commit -m "feat: add binary_sensor.py (online + recording)"
```

---

## Task 9: `__init__.py` (wiring)

**Files:**
- Create: `custom_components/hikvision_snmp/__init__.py`

**Interfaces:**
- `async def async_setup_entry(hass, entry)`:
  - Reads entry data (host, port, version, auth, scan_interval, device_type, name).
  - Builds `HikvisionSnmpClient`, calls `async_identify_device`, builds `DeviceInfo`, sets up `HikvisionDataUpdateCoordinator`.
  - Stores `client`, `coordinator`, and `coordinator.device_info` in `hass.data[DOMAIN][entry.entry_id]`.
  - Performs first refresh.
  - Forwards to platforms: sensor, binary_sensor.
- `async def async_unload_entry(hass, entry)` — unloads platforms, closes client, removes hass.data.

- [ ] **Step 1: Write `__init__.py`**

```python
"""Hikvision SNMP integration entry point."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AUTH_KEY,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_DEVICE_TYPE,
    CONF_PRIVACY_KEY,
    CONF_PRIVACY_PROTOCOL,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import HikvisionDataUpdateCoordinator
from .device_info import async_identify_device, build_device_info
from .snmp_client import HikvisionSnmpClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hikvision SNMP from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    data = entry.data
    options = entry.options
    scan_interval = options.get(CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))

    version = data[CONF_VERSION]
    if version == "v2c":
        auth = {"community": data[CONF_COMMUNITY]}
    else:
        auth = {
            "username": data[CONF_USERNAME],
            "auth_protocol": data[CONF_AUTH_PROTOCOL],
            "auth_key": data[CONF_AUTH_KEY],
            "privacy_protocol": data[CONF_PRIVACY_PROTOCOL],
            "priv_key": data[CONF_PRIVACY_KEY],
        }

    client = HikvisionSnmpClient(
        hass,
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, 161),
        version=version,
        auth=auth,
    )

    identification = await async_identify_device(client)
    device_info = build_device_info(
        entry.entry_id,
        data[CONF_HOST],
        identification,
        data.get(CONF_NAME, f"Hikvision {data[CONF_HOST]}"),
    )

    coordinator = HikvisionDataUpdateCoordinator(
        hass, client, scan_interval=scan_interval, identification=identification
    )
    coordinator.device_info = device_info  # type: ignore[attr-defined]

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: HikvisionDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator._client.close()  # noqa: SLF001 — engine shutdown
    return unload_ok
```

- [ ] **Step 2: Compile and commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m py_compile custom_components/hikvision_snmp/__init__.py
git add custom_components/hikvision_snmp/__init__.py
git commit -m "feat: add __init__.py wiring coordinator + sensor + binary_sensor"
```

---

## Task 10: `config_flow.py` + `strings.json` + `en.json` + `zh.json`

**Files:**
- Create: `custom_components/hikvision_snmp/config_flow.py`
- Create: `custom_components/hikvision_snmp/strings.json`
- Create: `custom_components/hikvision_snmp/translations/en.json`
- Create: `custom_components/hikvision_snmp/translations/zh.json`

**Interfaces:**
- `class HikvisionSnmpConfigFlow(ConfigFlow, domain=DOMAIN)`:
  - VERSION = 1
  - `async def async_step_user(user_input=None)` — three sub-steps: basic → snmp → confirm.
  - `async def async_step_basic`, `async def async_step_snmp`, `async def async_step_confirm`.
  - On confirm step, performs live `GET sysDescr` against the entered creds; on success, creates entry; on failure, shows error.
- `class HikvisionSnmpOptionsFlow(OptionsFlow)`:
  - `async def async_step_init(user_input=None)` — re-edit scan_interval and SNMP creds.

- [ ] **Step 1: Write `strings.json`**

```json
{
  "config": {
    "flow_title": "{name}",
    "step": {
      "basic": {
        "title": "Device basics",
        "description": "Enter the connection details for your Hikvision device.",
        "data": {
          "name": "Name",
          "host": "Host",
          "port": "Port",
          "device_type": "Device type"
        }
      },
      "snmp": {
        "title": "SNMP credentials",
        "description": "Select the SNMP version and enter credentials.",
        "data": {
          "version": "SNMP version",
          "community": "Community (v2c)",
          "username": "Username (v3)",
          "auth_protocol": "Auth protocol (v3)",
          "auth_key": "Auth key (v3)",
          "privacy_protocol": "Privacy protocol (v3)",
          "privacy_key": "Privacy key (v3)"
        }
      },
      "confirm": {
        "title": "Confirm",
        "description": "Testing connection to {host}…"
      }
    },
    "error": {
      "cannot_connect": "Failed to connect via SNMP. Check host, port, and credentials.",
      "no_data": "Connected but device returned no system description."
    },
    "abort": {
      "already_configured": "This device is already configured."
    }
  },
  "options": {
    "flow_title": "{name} options",
    "step": {
      "options_general": {
        "title": "Polling options",
        "data": {
          "scan_interval": "Poll interval (seconds)"
        }
      },
      "options_snmp": {
        "title": "SNMP credentials",
        "data": {
          "version": "SNMP version",
          "community": "Community (v2c)",
          "username": "Username (v3)",
          "auth_protocol": "Auth protocol (v3)",
          "auth_key": "Auth key (v3)",
          "privacy_protocol": "Privacy protocol (v3)",
          "privacy_key": "Privacy key (v3)"
        }
      }
    }
  }
}
```

- [ ] **Step 2: Write `zh.json`** (Simplified Chinese)

```json
{
  "config": {
    "flow_title": "{name}",
    "step": {
      "basic": {
        "title": "设备基本信息",
        "description": "请填写海康设备的连接信息。",
        "data": {
          "name": "名称",
          "host": "IP 地址",
          "port": "端口",
          "device_type": "设备类型"
        }
      },
      "snmp": {
        "title": "SNMP 凭证",
        "description": "选择 SNMP 版本并填写凭证。",
        "data": {
          "version": "SNMP 版本",
          "community": "Community (v2c)",
          "username": "用户名 (v3)",
          "auth_protocol": "认证协议 (v3)",
          "auth_key": "认证密钥 (v3)",
          "privacy_protocol": "加密协议 (v3)",
          "privacy_key": "加密密钥 (v3)"
        }
      },
      "confirm": {
        "title": "确认",
        "description": "正在连接 {host}…"
      }
    },
    "error": {
      "cannot_connect": "SNMP 连接失败,请检查 IP、端口和凭证。",
      "no_data": "连接成功但设备未返回系统描述。"
    },
    "abort": {
      "already_configured": "此设备已被配置。"
    }
  },
  "options": {
    "flow_title": "{name} 选项",
    "step": {
      "options_general": {
        "title": "轮询选项",
        "data": {
          "scan_interval": "轮询间隔(秒)"
        }
      },
      "options_snmp": {
        "title": "SNMP 凭证",
        "data": {
          "version": "SNMP 版本",
          "community": "Community (v2c)",
          "username": "用户名 (v3)",
          "auth_protocol": "认证协议 (v3)",
          "auth_key": "认证密钥 (v3)",
          "privacy_protocol": "加密协议 (v3)",
          "privacy_key": "加密密钥 (v3)"
        }
      }
    }
  }
}
```

- [ ] **Step 3: Write `en.json`** (English; same content as strings.json)

Copy `strings.json` content verbatim into `translations/en.json` — the strings.json file is the source-of-truth for default English.

- [ ] **Step 4: Write `config_flow.py`**

```python
"""Config flow for Hikvision SNMP."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback

from .const import (
    CONF_AUTH_KEY,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_DEVICE_TYPE,
    CONF_PRIVACY_KEY,
    CONF_PRIVACY_PROTOCOL,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_TYPES,
    DOMAIN,
    HIKVISION_PRIVATE_MIB_ROOT,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SNMP_VERSIONS,
    V3_AUTH_PROTOCOLS,
    V3_PRIVACY_PROTOCOLS,
)
from .snmp_client import HikvisionSnmpClient, HikvisionSnmpError

USER_DATA_SCHEMA_BASIC = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Hikvision NVR"): str,
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_DEVICE_TYPE, default="auto"): vol.In(DEVICE_TYPES),
    }
)


def _snmp_schema(version: str) -> vol.Schema:
    if version == "v2c":
        return vol.Schema({vol.Required(CONF_COMMUNITY): str})
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_AUTH_PROTOCOL, default="SHA"): vol.In(V3_AUTH_PROTOCOLS),
            vol.Required(CONF_AUTH_KEY): str,
            vol.Required(CONF_PRIVACY_PROTOCOL, default="AES128"): vol.In(V3_PRIVACY_PROTOCOLS),
            vol.Required(CONF_PRIVACY_KEY): str,
        }
    )


async def _test_connection(host: str, port: int, version: str, auth: dict) -> str | None:
    """Returns sysDescr string on success, None on failure."""
    client = HikvisionSnmpClient(None, host=host, port=port, version=version, auth=auth)  # type: ignore[arg-type]
    try:
        sys_descr = await client.get(f"{HIKVISION_PRIVATE_MIB_ROOT}.1.1.1.1.0")
    except HikvisionSnmpError:
        await client.close()
        return None
    await client.close()
    if not sys_descr:
        return None
    return str(sys_descr)


class HikvisionSnmpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hikvision SNMP."""

    VERSION = 1

    def __init__(self) -> None:
        self._basic: dict[str, Any] | None = None
        self._snmp: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="basic", data_schema=USER_DATA_SCHEMA_BASIC)
        self._basic = user_input
        return await self.async_step_snmp()

    async def async_step_snmp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._basic is not None
        if user_input is None:
            schema = _snmp_schema("v2c")
            return self.async_show_form(
                step_id="snmp",
                data_schema=vol.Schema(
                    {vol.Required(CONF_VERSION, default="v2c"): vol.In(SNMP_VERSIONS), **schema.schema}
                ),
            )
        version = user_input[CONF_VERSION]
        # Re-validate the rest against the version-specific schema
        try:
            validated = _snmp_schema(version)(user_input)
        except vol.Invalid:
            schema = _snmp_schema(version)
            return self.async_show_form(
                step_id="snmp",
                data_schema=vol.Schema(
                    {vol.Required(CONF_VERSION, default=version): vol.In(SNMP_VERSIONS), **schema.schema}
                ),
                errors={CONF_VERSION: "invalid_snmp_version"},
            )
        self._snmp = validated
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._basic is not None and self._snmp is not None
        host = self._basic[CONF_HOST]
        port = self._basic.get(CONF_PORT, DEFAULT_PORT)
        version = self._snmp[CONF_VERSION]
        auth = (
            {"community": self._snmp[CONF_COMMUNITY]}
            if version == "v2c"
            else {
                "username": self._snmp[CONF_USERNAME],
                "auth_protocol": self._snmp[CONF_AUTH_PROTOCOL],
                "auth_key": self._snmp[CONF_AUTH_KEY],
                "privacy_protocol": self._snmp[CONF_PRIVACY_PROTOCOL],
                "priv_key": self._snmp[CONF_PRIVACY_KEY],
            }
        )

        await self.async_set_unique_id(f"{host}:{port}")
        self._abort_if_unique_id_configured()

        result = await _test_connection(host, port, version, auth)
        if not result:
            return self.async_show_form(
                step_id="confirm",
                errors="cannot_connect",
                description_placeholders={"host": host},
            )

        return self.async_create_entry(
            title=self._basic.get(CONF_NAME, f"Hikvision {host}"),
            data={
                **self._basic,
                **self._snmp,
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                "_sys_descr": result,
            },
        )


class HikvisionSnmpOptionsFlow(OptionsFlow):
    """Handle options flow."""

    def __init__(self, entry: ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="options_general",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
                }
            ),
        )


@callback
def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
    return HikvisionSnmpOptionsFlow(entry)
```

- [ ] **Step 5: Compile and commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
python -m py_compile custom_components/hikvision_snmp/config_flow.py
git add custom_components/hikvision_snmp/config_flow.py custom_components/hikvision_snmp/strings.json custom_components/hikvision_snmp/translations/
git commit -m "feat: add config_flow.py + strings.json + en.json + zh.json"
```

---

## Task 11: `services.yaml` + `__init__.py` service registration (placeholder)

**Files:**
- Create: `custom_components/hikvision_snmp/services.yaml`

**Interfaces:**
- Empty `services:` section. Reserved for v2 (e.g. `hikvision_snmp.reboot`).

- [ ] **Step 1: Write `services.yaml`**

```yaml
services: {}
```

- [ ] **Step 2: Commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
git add custom_components/hikvision_snmp/services.yaml
git commit -m "chore: add empty services.yaml (v1 has no write actions)"
```

---

## Task 12: `README.md` (full) + `docs/oid-reference.md`

**Files:**
- Modify: `README.md`
- Create: `docs/oid-reference.md`

**Interfaces:**
- `README.md` covers: install (HACS custom repo + manual), ConfigFlow walkthrough (with screenshot placeholders), OptionsFlow, supported devices, troubleshooting (community string, SNMP enabled in device web UI, port 161 reachable, version conflict), license.
- `docs/oid-reference.md` is the public OID table — names, OIDs, return type, decoding rule, which entity reads it.

- [ ] **Step 1: Write `README.md`**

```markdown
# Hikvision SNMP

A Home Assistant custom component that monitors Hikvision NVRs and standalone IPCs over SNMP v2c or v3 — read-only sensors for device health (CPU, memory, temperature, uptime, firmware), per-channel status, and disk / SD-card state.

> v1 scope: **sensors and binary_sensors only.** Reboot / channel control / PTZ are not implemented.

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
| Uptime | sensor | seconds → displayed as d h m |
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

## License

MIT © 2026 43457. See `LICENSE`.
```

- [ ] **Step 2: Write `docs/oid-reference.md`**

```markdown
# OID Reference — Hikvision Private MIB

Hikvision devices expose monitoring data under their private enterprise OID:

```
iso.org.dod.internet.private.enterprise.hikvision = 1.3.6.1.4.1.39165
```

## System subtree — `1.3.6.1.4.1.39165.1.1.1`

| Metric | OID suffix | Return | Decoded |
|---|---|---|---|
| model | `.1.1.0` | OctetString | string |
| device_name | `.1.2.0` | OctetString | string |
| firmware | `.1.3.0` | OctetString | string |
| device_type_code | `.1.4.0` | Integer | enum (1=NVR, 2=DVR, 3=IPC) |
| uptime | `.1.5.0` | TimeTicks | seconds = int / 100 |
| cpu | `.1.6.0` | Integer | % |
| memory | `.1.7.0` | Integer | % |
| temperature | `.1.8.0` | Integer | °C |

## Channel subtree — `1.3.6.1.4.1.39165.1.2.1`

| Metric | OID suffix | Return | Decoded |
|---|---|---|---|
| name | `.1.X` | OctetString | string |
| online | `.2.X` | Integer | 1 = online, 0 = offline |
| recording | `.3.X` | Integer | 1 = recording, 0 = not |
| bitrate | `.4.X` | Integer | kbps |
| resolution | `.5.X` | OctetString | string (e.g. "1920x1080") |

`X` is the channel index (1-based for NVRs; 1 for a standalone IPC).

## Disk subtree — `1.3.6.1.4.1.39165.1.3.1`

| Metric | OID suffix | Return | Decoded |
|---|---|---|---|
| name | `.1.X` | OctetString | string |
| status | `.2.X` | Integer | enum (1=normal, 2=idle, 3=warning) |
| capacity | `.3.X` | Integer | MB → GB |
| free | `.4.X` | Integer | MB → GB |
| temperature | `.5.X` | Integer | °C |

`X` is the disk index. IPCs return a single SD-card entry under `X = 1`.

## Alarm subtree — `1.3.6.1.4.1.39165.1.5.1`

Walked but not currently mapped to entities in v1. Reserved for v2 alarm input / output support.
```

- [ ] **Step 3: Commit**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
git add README.md docs/oid-reference.md
git commit -m "docs: full README.md and public OID reference"
```

---

## Task 13: Live test on user's NVR + IPC

This task has no code; it is an integration verification.

**Pre-test checklist** (run before touching HA):

- [ ] Confirm one Hikvision NVR (or IPC) is on the LAN, IP known.
- [ ] Confirm SNMP is **enabled** in the device web UI; community string set; credentials noted.
- [ ] Confirm UDP port 161 is reachable from the HA host (`Test-NetConnection <nvr_ip> -Port 161` from PowerShell).

**Integration test:**

- [ ] **Step 1: Copy the integration into HA's `custom_components`**

Copy `C:\Users\43457\Desktop\hikvision-snmp\custom_components\hikvision_snmp` to your HA `config/custom_components/hikvision_snmp`. Restart HA.

- [ ] **Step 2: Add integration via UI**

Settings → Devices & Services → Add Integration → **Hikvision SNMP**.

Walk the three steps. The confirm step must succeed (live SNMP GET returns sysDescr).

- [ ] **Step 3: Verify entities appear**

Settings → Devices & Services → Entities → filter "hikvision". Confirm:

- 10 base sensors (cpu/memory/temp/uptime/firmware/device_name/model/channels_total/online/recording)
- 2 binary_sensors (online, recording)
- N × 4 disk sensors (if NVR with HDDs)
- N × 2 channel sensors (one per channel)

- [ ] **Step 4: Verify values are real**

Developer Tools → States → search `sensor.hikvision_*`. Spot-check:

- `cpu_usage` < 100
- `memory_usage` < 100
- `temperature` reasonable (30–80 °C)
- `uptime` shows non-zero
- `firmware_version` matches what's in the device web UI

- [ ] **Step 5: Offline / recovery test**

Unplug the device's LAN cable for 30 s. Watch HA logs:

- Coordinator → `UpdateFailed: SNMP walk failed: …`
- `binary_sensor.online` → `offline`
- All sensors → `unavailable`

Replug. Within one poll cycle (~10 s) `online` → `on`, sensors back to real values.

- [ ] **Step 6: Options flow**

Settings → ⋯ → Configure → change scan_interval to 5 → save. Watch HA logs for poll frequency change.

- [ ] **Step 7: Capture failures / workarounds**

Note any device-specific quirks (firmware that returns scaled values, missing OIDs) into a follow-up issue or comment in the spec. Do NOT auto-fix in v1; defer to v0.2 if material.

- [ ] **Step 8: Commit any test-fixture / debug-script added during testing**

If you added a `tools/` directory with manual test scripts, commit them:
```bash
git add tools/
git commit -m "test: add manual SNMP walk probe (used during live verification)"
```

Expected: HA shows the device with correct entity readings; offline → online recovery works. If the integration fails to load or returns zero values, see "Failure recovery" below.

**Failure recovery:**

- ConfigFlow step 3 fails with "Failed to connect": re-check the SNMP credentials in the device web UI; try v2c first; verify port 161 open.
- Sensors show `unknown` after first poll: open HA logs, search for `hikvision_snmp` and `pysnmp`; the OID walk may have returned zero rows for the device — check if your firmware revision uses a different enterprise OID (some very old firmware uses `1.3.6.1.4.1.99`); add a custom override in v0.2.
- All sensors `unavailable` after offline test: verify the engine was properly closed in `async_unload_entry`; check for `engine.close_dispatcher` exceptions in HA logs.

---

## Task 14: Push to GitHub + tag v0.1.0

**Pre-step: proxy disable**

Per your environment, `gh` CLI fails TLS handshakes against GitHub when `HTTPS_PROXY` is set to the local Clash-style proxy. Before any `gh` command:

```powershell
$env:HTTPS_PROXY = ""
$env:HTTP_PROXY = ""
```

- [ ] **Step 1: Create GitHub repo via `gh`**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
$env:HTTPS_PROXY = ""
gh repo create 43457/hikvision-snmp --public --source=. --remote=origin --description "Home Assistant integration: Hikvision NVR/IPC over SNMP v2c/v3"
```

Expected: repo created; remote `origin` configured; `git push` happens during `gh repo create --source=.`.

- [ ] **Step 2: Push remaining commits (if any)**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
git push -u origin main
```

Expected: all commits visible on github.com/43457/hikvision-snmp.

- [ ] **Step 3: Tag v0.1.0 and create release**

```bash
cd C:\Users\43457\Desktop\hikvision-snmp
git tag -a v0.1.0 -m "v0.1.0: initial release — read-only SNMP monitoring for Hikvision NVR/IPC"
git push origin v0.1.0

$env:HTTPS_PROXY = ""
gh release create v0.1.0 --target main --title "v0.1.0" --notes "Initial release.

**Features**
- Read-only SNMP v2c / v3 monitoring for Hikvision NVRs and standalone IPCs
- Sensors: CPU / memory / temperature / uptime / firmware / device_name / model / channels_total / channels_online / channels_recording
- Per-disk sensors (name / capacity / free / temperature)
- Per-channel sensors (name / bitrate)
- Binary sensors: online / recording
- 4-tree GETBULK polling, default 10s, configurable 5–300s
- English + Simplified Chinese UI

**Out of scope (v1)**
- Control / reboot / channel toggle (v2)
- ISAPI / HTTP fallback
- HACS default repo submission

**Install**
HACS custom repository: https://github.com/43457/hikvision-snmp"
```

Expected: tag `v0.1.0` on remote; release `v0.1.0` published with notes.

- [ ] **Step 4: Verify repo state**

Browse to `https://github.com/43457/hikvision-snmp` and confirm:

- README renders
- LICENSE shows MIT
- hacs.json is present
- All `custom_components/hikvision_snmp/` files visible
- `docs/oid-reference.md` renders
- Release `v0.1.0` listed

- [ ] **Step 5: Update SPEC + plan with release link**

In `docs/superpowers/specs/2026-09-23-hikvision-snmp-design.md`, append a one-line note under §11:

```markdown
## 12. Release

- v0.1.0 released 2026-09-23 — https://github.com/43457/hikvision-snmp/releases/tag/v0.1.0
```

Commit:
```bash
git add docs/superpowers/specs/2026-09-23-hikvision-snmp-design.md
git commit -m "docs: record v0.1.0 release link in spec"
git push
```

---

## Self-Review (run before declaring plan complete)

**1. Spec coverage** — each section of the design spec maps to a task:

| Spec § | Task |
|---|---|
| §3 Architecture / module layout | Tasks 1–11 create the listed files |
| §4.1 Auth (v2c + v3) | Task 4 (snmp_client.py `UsmUserData` + protocol map) + Task 10 (config_flow v3 fields) |
| §4.3 OID subtrees | Task 2 (const.py) — exact OIDs defined as constants |
| §4.4 Polling | Task 6 (coordinator walks 3 subtrees, configurable scan_interval) + Task 10 (OptionsFlow) |
| §4.5 Error handling | Task 6 (raises `UpdateFailed` on `HikvisionSnmpError`) + Task 8 (`online` reflects `last_update_success`) |
| §4.6 Value decoding | Task 3 (helpers unit-tested) |
| §5 ConfigFlow | Task 10 (3-step flow + OptionsFlow) |
| §6 Entities | Task 7 (sensor static + per-disk + per-channel) + Task 8 (binary_sensor) |
| §6.5 device_info | Task 5 (device_info.py) + Task 9 (`__init__.py` stores on coordinator) |
| §7 manifest.json / requirements | Task 2 (manifest.json with compatibility range) |
| §8 Translations | Task 10 (strings.json + en.json + zh.json) |
| §9 Test plan | Task 13 (live test) |

All sections covered.

**2. Placeholder scan** — searched plan for `TBD`, `TODO`, "implement later", "add appropriate error handling" — none found. The `services.yaml` is intentionally empty (declared as reserved for v2 in the spec §10).

**3. Type consistency** —
- `coordinator.device_info` attribute is set in `__init__.py` and read in `sensor.py` + `binary_sensor.py`. Consistent.
- `coordinator._client` is private but accessed in `async_unload_entry` via `coordinator._client.close()` — flagged with `noqa: SLF001`. Acceptable for shutdown.
- `DOMAIN = "hikvision_snmp"` used consistently across all files.
- `CONF_*` constants defined in `const.py`, imported in `__init__.py`, `config_flow.py`, sensor/binary_sensor where needed. Consistent.
- `HikvisionSnmpClient.__init__` parameter `hass` is positional; `_test_connection` in config_flow passes `None` — the client only uses `self._hass` if I add helpers later; currently unused, but the parameter exists. Flagged with `type: ignore[arg-type]` comment. If pysnmp v7 ever needs the event loop, change `_test_connection` to be a coroutine that doesn't construct a client until inside HA's loop.

Plan is internally consistent.