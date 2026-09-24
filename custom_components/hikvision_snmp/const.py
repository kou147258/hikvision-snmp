"""Constants for Hikvision SNMP integration.

Two enterprise OIDs are supported (Hikvision uses one or the other depending on
product line):

- ``.1.3.6.1.4.1.39165`` — IPC / PTZ product line. 34 scalar leaves under
  ``.39165.1.<N>.0``. Verified on firmware V5.2.2 (2015) through V5.10.0 (2026).
- ``.1.3.6.1.4.1.50001`` — NVR / enterprise recorder line. ~22 scalar leaves under
  ``.50001.1.<N>.0`` plus a per-channel table at ``.50001.1.241.1.<col>.<row>.0``.

Auto-detection: ``device_info.async_identify_device`` tries the IPC root first,
falls back to the NVR root if no sysDescr-equivalent is returned.
"""

from __future__ import annotations

DOMAIN = "hikvision_snmp"
MANUFACTURER = "Hikvision"

# ---- Polling defaults ----

DEFAULT_PORT = 161
DEFAULT_SCAN_INTERVAL = 10  # seconds
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300
DEFAULT_REQUEST_TIMEOUT = 1  # seconds per request (reduced for fast probe failure)
DEFAULT_RETRIES = 1
BULK_MAX_REPETITIONS = 25
INTER_REQUEST_DELAY = 0.2  # seconds between GETNEXT iterations (busy V5.x devices)

# ---- Device-type enum (ConfigFlow choices) ----

DEVICE_TYPE_AUTO = "auto"
DEVICE_TYPE_NVR = "nvr"
DEVICE_TYPE_IPC = "ipc"
DEVICE_TYPE_DVR = "dvr"
DEVICE_TYPES = [DEVICE_TYPE_AUTO, DEVICE_TYPE_NVR, DEVICE_TYPE_IPC, DEVICE_TYPE_DVR]

# ---- Vendor identifiers (used internally; not exposed in UI) ----

VENDOR_HIKVISION_IPC = "hikvision_ipc"  # enterprise 39165
VENDOR_HIKVISION_NVR = "hikvision_nvr"  # enterprise 50001
VENDORS = [VENDOR_HIKVISION_IPC, VENDOR_HIKVISION_NVR]

# ---- Hikvision IPC / PTZ enterprise OID (private MIB) ----

HIKVISION_IPC_MIB_ROOT = "1.3.6.1.4.1.39165"
OID_SYSTEM_IPC = f"{HIKVISION_IPC_MIB_ROOT}.1"

SYSTEM_OIDS: dict[str, str] = {
    "model": "1",              # .1.3.6.1.4.1.39165.1.1.0  STRING "DS-2DF8C832MX-ZDK"
    "device_name": "2",        # STRING "0"
    "firmware": "3",           # STRING "V5.10.0 build 260519"
    "mac": "4",                # STRING MAC
    "device_count": "5",       # STRING "88"
    "manufacturer": "6",       # STRING "Hikvision"
    "cpu": "7",                # STRING "27 PERCENT"  -> 27.0
    "storage_total": "8",      # STRING "116.5 GB"    -> 116.5
    "memory_used_pct": "9",    # STRING "0 PERCENT"   -> 0
    "memory_total": "10",      # STRING "0 MB"        -> 0
    "storage_used_pct": "11",  # STRING "97 PERCENT"  -> 97
    "uptime_seconds": "12",    # INTEGER
    "ip_addr_alt1": "13",
    "ip_addr_alt2": "14",
    "ip_addr_alt3": "15",
    "ip_addr": "16",           # IpAddress
    "subnet_mask": "17",       # IpAddress
    "gateway": "18",           # IpAddress
    "device_time": "19",       # STRING "2026-09-24 08:18:02"
    "device_type_code": "20",  # INTEGER (Hikvision-internal — not exposed in v0.1.18)
    "video_codec_primary": "21",  # STRING "H.264"
    "video_codec_secondary": "22",  # STRING "H.264"
    "media_mode": "23",        # INTEGER (Hikvision-internal — not exposed)
    "online": "24",            # INTEGER 1 = online, 0 = offline
    "recording": "25",         # INTEGER 1 = recording, 0 = not
    "ptz_status_a": "26",      # INTEGER (Hikvision-internal — not exposed)
    "ptz_status_b": "27",      # INTEGER (Hikvision-internal — not exposed)
    "ptz_status_c": "28",      # INTEGER (Hikvision-internal — not exposed)
    "network_type": "29",      # STRING "ETHERNET"
}

OID_CHANNEL_IPC = f"{HIKVISION_IPC_MIB_ROOT}.2"
CHANNEL_OIDS: dict[str, str] = {
    "name": "1",
    "online": "2",
    "recording": "3",
    "bitrate": "4",
    "resolution": "5",
}

OID_DISK_IPC = f"{HIKVISION_IPC_MIB_ROOT}.3"
DISK_OIDS: dict[str, str] = {
    "name": "1",
    "status": "2",
    "capacity": "3",
    "free": "4",
    "temperature": "5",
}

# ---- Hikvision NVR enterprise OID (private MIB, product-line 50001) ----

HIKVISION_NVR_MIB_ROOT = "1.3.6.1.4.1.50001"
OID_SYSTEM_NVR = f"{HIKVISION_NVR_MIB_ROOT}.1"

# 22 scalar leaves under .50001.1.<N>.0
NVR_SYSTEM_OIDS: dict[str, str] = {
    "ip_addr": "1",            # IpAddress — device's own IP
    "model_code": "2",          # INTEGER 8000 — product code
    "serial": "3",             # STRING "0420251017CCRRGH1770265WCVU"
    "type_code_a": "100",       # INTEGER 2
    "type_code_b": "101",       # INTEGER 200 / 240
    "type_code_c": "102",       # INTEGER 1
    "type_code_d": "103",       # INTEGER 255
    "type_code_e": "104",       # INTEGER 255
    "type_code_f": "105",       # INTEGER 0
    "label_or_status": "106",   # STRING "" (often empty)
    "trap_target": "110",       # STRING IP — NTP / trap destination
    "presence_a": "200",        # INTEGER 1
    "cpu_freq": "201",          # STRING "1000MHZ"
    "temperature_or_load": "220",  # INTEGER 290..1130 — device-specific metric
    "traffic_or_iops": "221",   # INTEGER 0..60
    "active_state": "230",      # INTEGER 1 — at-least-one-channel-active flag
    "online_state": "231",      # INTEGER 2 — count of online channels
    "channel_count": "240",     # INTEGER 5 — number of channels / disks
}

# Per-channel / per-disk table at .50001.1.241.1.<col>.<row>.0
# column 1 = row index, column 2 = label, column 3 = motion flag (0/10),
# column 4 = sub-stream size?, column 5 = bytes used / stored
OID_CHANNEL_NVR = f"{HIKVISION_NVR_MIB_ROOT}.1.241.1"
NVR_CHANNEL_OIDS: dict[str, str] = {
    "row_index": "1",           # INTEGER 1, 2, 3, ...
    "label": "2",              # STRING "lable01"
    "motion_flag": "3",        # INTEGER 0 or 10
    "sub_stream_size": "4",    # INTEGER 0 or 1024 (units unconfirmed)
    "bytes_used": "5",         # INTEGER bytes
}

# ---- Config-flow field names ----

CONF_NAME = "name"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_DEVICE_TYPE = "device_type"
CONF_VERSION = "version"
CONF_COMMUNITY = "community"
CONF_USERNAME = "username"
CONF_AUTH_PROTOCOL = "auth_protocol"
CONF_AUTH_KEY = "auth_key"
CONF_PRIVACY_PROTOCOL = "privacy_protocol"
CONF_PRIVACY_KEY = "privacy_key"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_VENDOR = "vendor"  # auto / hikvision_ipc / hikvision_nvr — advanced

SNMP_VERSIONS = ["v2c", "v3"]

V3_AUTH_PROTOCOLS = ["MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"]
V3_PRIVACY_PROTOCOLS = ["DES", "3DES", "AES128", "AES192", "AES256"]