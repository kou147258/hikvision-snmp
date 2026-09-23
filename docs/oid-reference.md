# OID Reference — Hikvision Private MIB

Hikvision devices expose monitoring data under their private enterprise OID:

```
iso.org.dod.internet.private.enterprise.hikvision = 1.3.6.1.4.1.39165
```

## System subtree — `1.3.6.1.4.1.39165.1.1.1`

Each scalar leaf has a `.0` instance suffix.

| Metric | OID | Return | Decoded |
|---|---|---|---|
| model | `.1.0` | OctetString | string |
| device_name | `.2.0` | OctetString | string |
| firmware | `.3.0` | OctetString | string |
| device_type_code | `.4.0` | Integer | enum (1 = NVR, 2 = DVR, 3 = IPC) |
| uptime | `.5.0` | TimeTicks | seconds = int / 100 |
| cpu | `.6.0` | Integer | percent |
| memory | `.7.0` | Integer | percent |
| temperature | `.8.0` | Integer | celsius |

## Channel subtree — `1.3.6.1.4.1.39165.1.2.1`

Each column has one row per channel index `X`.

| Metric | OID pattern | Return | Decoded |
|---|---|---|---|
| name | `.1.X` | OctetString | string |
| online | `.2.X` | Integer | 1 = online, 0 = offline |
| recording | `.3.X` | Integer | 1 = recording, 0 = not |
| bitrate | `.4.X` | Integer | kbps |
| resolution | `.5.X` | OctetString | e.g. "1920x1080" |

`X` is the channel index (1-based for NVRs; 1 for a standalone IPC).

## Disk subtree — `1.3.6.1.4.1.39165.1.3.1`

Each column has one row per disk index `X`.

| Metric | OID pattern | Return | Decoded |
|---|---|---|---|
| name | `.1.X` | OctetString | string |
| status | `.2.X` | Integer | enum (1 = normal, 2 = idle, 3 = warning) |
| capacity | `.3.X` | Integer | MB → GB (divided by 1024) |
| free | `.4.X` | Integer | MB → GB |
| temperature | `.5.X` | Integer | celsius |

`X` is the disk index. IPCs return a single SD-card entry under `X = 1`.

## Alarm subtree — `1.3.6.1.4.1.39165.1.5.1`

Walked but not currently mapped to entities in v1. Reserved for v2 alarm input / output support.

---

## Notes for firmware variants

Some older firmware (pre-2018) returns strings with `\x00` padding bytes after the actual value. The integration strips those automatically via `decode_octet_string` in `helpers.py`.

If your device returns no data under `1.3.6.1.4.1.39165`, it may be using an older enterprise OID. Hikvision has historically used `1.3.6.1.4.1.99` on very early firmware; please file an issue with a `snmpwalk` capture if you encounter this.