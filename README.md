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

## License

MIT © 2026 43457. See `LICENSE`.