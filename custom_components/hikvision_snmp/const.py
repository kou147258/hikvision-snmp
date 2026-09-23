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