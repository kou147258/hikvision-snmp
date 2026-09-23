# OID Reference — Hikvision Private MIBs

Two private enterprise OIDs are in use depending on Hikvision product line:

| Product line | Enterprise OID |
|---|---|
| IPC / PTZ (firmware V5.x) | `1.3.6.1.4.1.39165` |
| NVR / enterprise recorder | `1.3.6.1.4.1.50001` |

The integration auto-detects which subtree the device responds under.

---

## IPC / PTZ — `1.3.6.1.4.1.39165` (firmware V5.x flat MIB)

### System scalars — `.39165.1.<N>.0`

Each scalar leaf has a `.0` instance suffix. The integration reads these via
GETBULK (with GETNEXT fallback) starting at `.39165.1`.

| Metric | OID | Return | Decoded |
|---|---|---|---|
| model | `.1.0` | OctetString | string (e.g. `DS-2DF8C832MX-ZDK`) |
| device_name | `.2.0` | OctetString | string |
| firmware | `.3.0` | OctetString | string (e.g. `V5.10.0 build 260519`) |
| mac | `.4.0` | OctetString | string |
| device_count | `.5.0` | OctetString | string |
| manufacturer | `.6.0` | OctetString | string |
| cpu | `.7.0` | OctetString | `"<pct> PERCENT"` → float |
| storage_total | `.8.0` | OctetString | `"<gb> GB"` → float |
| memory_used_pct | `.9.0` | OctetString | `"<pct> PERCENT"` → float |
| memory_total | `.10.0` | OctetString | `"<mb> MB"` → float |
| storage_used_pct | `.11.0` | OctetString | `"<pct> PERCENT"` → float |
| uptime_seconds | `.12.0` | Integer | seconds (often times out on busy V5.x — see README) |
| ip_addr_alt1 | `.13.0` | OctetString | string |
| ip_addr_alt2 | `.14.0` | OctetString | string |
| ip_addr_alt3 | `.15.0` | OctetString | string |
| ip_addr | `.16.0` | IpAddress | dotted-quad |
| subnet_mask | `.17.0` | IpAddress | dotted-quad |
| gateway | `.18.0` | IpAddress | dotted-quad |
| device_time | `.19.0` | OctetString | string |
| video_codec_primary | `.21.0` | OctetString | string |
| video_codec_secondary | `.22.0` | OctetString | string |
| online | `.24.0` | Integer | 1 = online, 0 = offline (often times out — coordinator heartbeat is the fallback) |
| recording | `.25.0` | Integer | 1 = recording, 0 = not (often times out) |
| network_type | `.29.0` | OctetString | string |

### Channel sub-tree — `.39165.2.<col>.<row>`

Each column has one row per channel. The row index is bare (no `.0` suffix).

| Metric | OID pattern | Return | Decoded |
|---|---|---|---|
| name | `.2.1.<row>` | OctetString | string |
| online | `.2.2.<row>` | Integer | 1 = online, 0 = offline |
| recording | `.2.3.<row>` | Integer | 1 = recording, 0 = not |
| bitrate | `.2.4.<row>` | Integer | kbps |
| resolution | `.2.5.<row>` | OctetString | e.g. `1920x1080` |

Standalone IPCs typically report a single channel at row `1`. Multi-channel
IPC firmware reports rows `1..N`.

### Disk sub-tree — `.39165.3.<col>.<row>`

| Metric | OID pattern | Return | Decoded |
|---|---|---|---|
| name | `.3.1.<row>` | OctetString | string |
| status | `.3.2.<row>` | Integer | enum |
| capacity | `.3.3.<row>` | Integer | MB → GB (÷1024) |
| free | `.3.4.<row>` | Integer | MB → GB |
| temperature | `.3.5.<row>` | Integer | celsius |

IPCs return a single SD-card row at index `1`.

---

## NVR — `1.3.6.1.4.1.50001`

### System scalars — `.50001.1.<N>.0`

22 scalar leaves; same instance convention (`.0`) as the IPC subtree.

| Metric | OID | Return | Decoded |
|---|---|---|---|
| ip_addr | `.1.0` | IpAddress | NVR's own IP |
| model_code | `.2.0` | Integer | product code (e.g. `8000`) |
| serial | `.3.0` | OctetString | device serial |
| type_code_a | `.100.0` | Integer | device-specific enum |
| type_code_b | `.101.0` | Integer | device-specific enum |
| type_code_c | `.102.0` | Integer | device-specific enum |
| type_code_d | `.103.0` | Integer | device-specific enum |
| type_code_e | `.104.0` | Integer | device-specific enum |
| type_code_f | `.105.0` | Integer | device-specific enum |
| label_or_status | `.106.0` | OctetString | string (often empty) |
| trap_target | `.110.0` | OctetString | NTP / trap destination IP |
| presence_a | `.200.0` | Integer | 1 = present |
| cpu_freq | `.201.0` | OctetString | `"1000MHZ"` → float MHz |
| temperature_or_load | `.220.0` | Integer | device-specific (temp ×10 or load) |
| traffic_or_iops | `.221.0` | Integer | device-specific (kbps or IOPS) |
| active_state | `.230.0` | Integer | 1 = ≥1 channel active |
| online_state | `.231.0` | Integer | count of online channels |
| channel_count | `.240.0` | Integer | total channels (drives per-channel entity creation) |

### Per-channel sub-table — `.50001.1.241.1.<col>.<row>.0`

Unlike the IPC channel sub-tree, the NVR one lives at `.1.241.1` (one extra
sub-table level) and uses a `.0` instance suffix per row.

| Metric | OID pattern | Return | Decoded |
|---|---|---|---|
| row_index | `.241.1.1.<row>.0` | Integer | 1, 2, 3, … |
| label | `.241.1.2.<row>.0` | OctetString | string (e.g. `lable01`) |
| motion_flag | `.241.1.3.<row>.0` | Integer | 0 or 10 (10 indicates motion) |
| sub_stream_size | `.241.1.4.<row>.0` | Integer | kbps (units unconfirmed) |
| bytes_used | `.241.1.5.<row>.0` | Integer | bytes (storage used by this channel) |

`<row>` is the channel index (1-based, `1..channel_count`).

---

## Notes for firmware variants

- **Older IPC firmware (pre-V5)** uses a non-flat MIB at `.39165.1.1.1`,
  `.39165.1.2.1`, etc. — see commit history before v0.1.0 for the legacy
  mapping. The current integration only supports the V5.x flat layout.
- **Very early IPC firmware** (pre-2015) reports under `.1.3.6.1.4.1.99`
  instead. The integration does not auto-detect this; file an issue with
  a `snmpwalk` capture if you encounter it.
- **OctetString padding** — some firmware appends `\x00` after the value.
  `decode_octet_string` in `helpers.py` strips those automatically.
- **NVR `.220` and `.221` interpretation** — these are device-specific.
  On the three NVRs we verified, `.220` ranges `290..1130` (likely
  temperature ×10) and `.221` ranges `0..60` (likely kbps or IOPS).
  Both are exposed as raw int sensors.
