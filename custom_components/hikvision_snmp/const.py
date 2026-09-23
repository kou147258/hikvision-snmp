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

# Subtree root that holds device scalars on DS-2DF8 series V5.x firmware.
# Verified against DS-2DF8C832MX-ZDK firmware V5.10.0 build 260519
# via `snmpwalk -v2c -c public .1.3.6.1.4.1.39165.1` (returns 34 leaves
# numbered .1.0 through .34.0). Other firmware variants may differ.
OID_SYSTEM = f"{HIKVISION_PRIVATE_MIB_ROOT}.1"

# Per-subtree OID definitions are kept as dicts keyed by metric name, with
# values being the LEAF index under the subtree root. The full OID is
# reconstructed as ``f"{subtree_root}.{leaf}.0"`` for scalar leaves.
#
# Values returned by the device on V5.x IPC firmware are mostly STRING with
# embedded units (e.g. ``"27 PERCENT"``, ``"116.5 GB"``). Integer / IpAddress
# leaves are decoded as-is. Helpers in helpers.py strip units from the
# string-form values.
#
# NOTE: NVR firmware likely exposes additional sub-trees for per-channel
# status and per-disk metrics. v1 only ships the system subtree map below;
# per-channel / per-disk entities are wired but will simply be empty for
# devices that don't expose those sub-trees.

SYSTEM_OIDS: dict[str, str] = {
    "model": "1",                     # STRING "DS-2DF8C832MX-ZDK"
    "device_name": "2",               # STRING "0"  (some firmwares put device name here)
    "firmware": "3",                  # STRING "V5.10.0 build 260519"
    "mac": "4",                       # STRING "08-cc-81-fe-f7-d8"
    "device_count": "5",              # STRING "88"
    "manufacturer": "6",              # STRING "Hikvision"
    "cpu": "7",                       # STRING "27 PERCENT"  -> 27
    "storage_total": "8",             # STRING "116.5 GB"    -> 116.5
    "memory_used_pct": "9",           # STRING "0 PERCENT"   -> 0
    "memory_total": "10",             # STRING "0 MB"        -> 0
    "storage_used_pct": "11",         # STRING "97 PERCENT"  -> 97
    "uptime_seconds": "12",           # INTEGER
    "ip_addr_alt1": "13",             # IpAddress
    "ip_addr_alt2": "14",             # IpAddress
    "ip_addr_alt3": "15",             # IpAddress
    "ip_addr": "16",                  # IpAddress 10.18.176.10
    "subnet_mask": "17",              # IpAddress 255.255.255.0
    "gateway": "18",                  # IpAddress
    "device_time": "19",              # STRING "2026-09-23 14:58:17"
    "video_codec_primary": "21",      # STRING "H.264"
    "video_codec_secondary": "22",    # STRING "H.264"
    "online": "24",                   # INTEGER 1 = online, 0 = offline
    "recording": "25",                # INTEGER 1 = recording, 0 = not
    "network_type": "29",             # STRING "ETHERNET"
}

# Channel subtree — placeholders for NVRs. IPCs do not expose these.
OID_CHANNEL = f"{HIKVISION_PRIVATE_MIB_ROOT}.2"

CHANNEL_OIDS: dict[str, str] = {
    "name": "1",
    "online": "2",
    "recording": "3",
    "bitrate": "4",
    "resolution": "5",
}

# Disk subtree — placeholders for NVRs. IPCs do not expose these.
OID_DISK = f"{HIKVISION_PRIVATE_MIB_ROOT}.3"

DISK_OIDS: dict[str, str] = {
    "name": "1",
    "status": "2",
    "capacity": "3",
    "free": "4",
    "temperature": "5",
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

SNMP_VERSIONS = ["v2c", "v3"]

V3_AUTH_PROTOCOLS = ["MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"]
V3_PRIVACY_PROTOCOLS = ["DES", "3DES", "AES128", "AES192", "AES256"]

# ---- Hikvision device-type code → string mapping (legacy MIB; not used on V5.x) ----

DEVICE_TYPE_CODE_MAP: dict[int, str] = {
    1: DEVICE_TYPE_NVR,
    2: DEVICE_TYPE_DVR,
    3: DEVICE_TYPE_IPC,
}