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

Verified across three NVRs (`192.168.10.x` / `192.168.10.x` / `192.168.10.x`,
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

---

## 简体中文

一个用于监控海康威视 NVR 和独立 IPC 的 Home Assistant 自定义集成，通过 SNMP v2c 或 v3 通信。只读 sensor，监控设备健康（CPU、内存、温度、运行时长、固件版本）、每通道状态、磁盘 / SD 卡状态。

通过自动检测支持两条产品线（无需手动选择）：

- **海康 IPC / PTZ** — enterprise OID `.1.3.6.1.4.1.39165`（V5.x flat MIB）
- **海康 NVR** — enterprise OID `.1.3.6.1.4.1.50001`（不同的 MIB 布局，有 per-channel 子表）

集成在 setup 时自动选择正确的 OID 子树。详见 [`docs/tested-devices.md`](docs/tested-devices.md) 列出的 7 台已验证设备。

> **v1 范围：仅 sensor 和 binary_sensor。** 重启 / 通道控制 / 云台控制未实现（推迟到 v2）。

### 安装

#### HACS（推荐）

1. 安装 [HACS](https://hacs.xyz/)。
2. HACS → Integrations → ⋯ → **Custom repositories** → 添加 `https://github.com/kou147258/hikvision-snmp`，类型选择 **Integration**。
3. 刷新列表，找到 **Hikvision SNMP**，安装。
4. 重启 Home Assistant。

#### 手动安装

1. 复制 `custom_components/hikvision_snmp/` 目录到 HA 的 `config/custom_components/` 目录下。
2. 重启 Home Assistant。

### 配置

1. **设置 → 设备与服务 → 添加集成 → Hikvision SNMP**。
2. 步骤 1 — 输入名称、设备 IP、端口（默认 161）、设备类型（`auto` / `nvr` / `ipc`）。`auto` 会同时查询 `.39165` 和 `.50001` 子树并选择有响应的那个。
3. 步骤 2 — 选择 SNMP v2c 或 v3 并输入凭证。
4. 步骤 3 — 集成会执行一次 `GET sysDescr` 确认可达性。成功后会创建 entry，检测到的厂商信息存在 coordinator 上。

#### 海康设备端准备

海康固件默认禁用 SNMP，需要手动开启：

1. 登录设备 web 界面。
2. **配置 → 网络 → SNMP**。
3. 勾选 **启用 SNMP**。
4. 设置 SNMP 版本（v2c 或 v3）和 community / v3 凭证。
5. **保存**。

集成通过 UDP 端口 161 通信。如果设备在不同的 VLAN，需要在防火墙放行。

### 实体

#### IPC / PTZ（enterprise 39165）

| 实体 | 类型 | 说明 |
|---|---|---|
| 型号 | sensor | 文本（来自 `.39165.1.1.0`）|
| 设备名称 | sensor | 文本 |
| 固件版本 | sensor | 文本 |
| MAC 地址 | sensor | 文本 |
| 制造商 | sensor | 文本 |
| CPU 使用率 | sensor | % |
| 内存使用率 | sensor | % |
| 内存总量 | sensor | MB |
| 存储总量 | sensor | GB |
| 存储使用率 | sensor | % |
| 运行时长 | sensor | duration |
| 设备时间 | sensor | 文本 |
| 网络类型 | sensor | 文本 |
| IP 地址 | sensor | 文本（v0.1.18+）|
| 子网掩码 | sensor | 文本（v0.1.18+）|
| 默认网关 | sensor | 文本（v0.1.18+）|
| 主码流编码 | sensor | 文本（v0.1.18+）|
| 副码流编码 | sensor | 文本（v0.1.18+）|
| 通道 N 名称 | sensor | 文本（每个检测到的通道）|
| 通道 N 码率 | sensor | kbps（每个检测到的通道）|
| 磁盘 N 名称 | sensor | 文本（每个检测到的 SD 卡）|
| 磁盘 N 容量 | sensor | GB（每个检测到的 SD 卡）|
| 在线状态 | binary_sensor | 设备可达（`.39165.1.24.0`，回退到 coordinator 心跳）|
| 录像状态 | binary_sensor | 任一通道录像中（`.39165.1.25.0` 或 per-channel）|

#### NVR（enterprise 50001）

| 实体 | 类型 | 说明 |
|---|---|---|
| 序列号 | sensor | 文本（`.50001.1.3.0`）|
| IP 地址 | sensor | 文本（`.50001.1.1.0`）|
| Trap 目标 | sensor | 文本（`.50001.1.110.0`）|
| CPU 频率 | sensor | MHz（`.50001.1.201.0`）|
| 温度 / 负载 | sensor | 原始 int（`.50001.1.220.0` — 设备相关，可能是温度 ×10 或负载计数）|
| 流量 / IOPS | sensor | 原始 int（`.50001.1.221.0`）|
| 通道总数 | sensor | int（`.50001.1.240.0`）|
| 活动状态 | sensor | int（`.50001.1.230.0` — 1 表示至少 1 个通道活跃）|
| 在线状态 | sensor | int（`.50001.1.231.0` — 在线通道数）|
| 通道 N 标签 | sensor | 文本（每个检测到的通道）|
| 通道 N 动态检测 | sensor | int（0 或 10 — 10 表示检测到动态）|
| 通道 N 子码流大小 | sensor | kbps（单位待确认）|
| 通道 N 已用字节 | sensor | bytes（该通道已用存储）|
| 在线状态 | binary_sensor | coordinator 心跳（NVR 没有 `.24` scalar）|
| 录像状态 | binary_sensor | 任一通道 `motion_flag > 0`，或设备 `active_state == 1` |

> NVR 在这个 MIB 子树里没有 per-disk 子表；per-channel `已用字节` 是最接近的存储指标。

### 选项

设置 → 设备与服务 → Hikvision SNMP → ⋯ → **配置**：

- **轮询间隔（秒）** — 默认 10，范围 5–300。间隔越短 HA event-loop 负担越重；6-20 台设备推荐 10-30s。

### 兼容性

- `pysnmp>=6.2.6,<7.0.0`
- Home Assistant 2025.4+
- Python 3.11+

### 海康 V5.x 固件特性

集成在四种 V5.x IPC（`DS-2DF8C832MX-ZDK` PTZ V5.10.0、`DS-2DE3A20IW-D/GLT/XM` IPC V5.7.30、`DS-FCN8027-VIK` V5.6.1、`DS-FB2127` V5.2.2）和三台 NVR 上验证通过：

1. **GETBULK 在繁忙设备上超时** — bulkCmd 包无响应。集成每台主机检测一次后自动切换到 GETNEXT。
2. **GETNEXT walk 中途截断** — 设备在负载下从 .11 附近开始丢 GETNEXT 响应。v0.1.1+ 用 single-GET fallback 补齐（500 ms backoff + retry）。结果：~21/23 system scalars 稳定获取。
3. **三个 INTEGER leaf 在 single GET 也超时** (`.12.0` / `.24.0` / `.25.0`)：分别对应 `运行时长` / `在线状态` / `录像状态`。集成优雅处理：runtime 显示 `unavailable`，`在线状态` 回退到 coordinator 心跳，IPC 没通道表时 `录像状态` 返回 `unknown`。
4. **繁忙设备下请求超时** — IPC 主动流媒体 / 录像时，SNMP 守护进程被视频管线抢占。v0.1.1+ 缓解：walk_next 中 200 ms 间隔；GETNEXT 和 single-GET 在 RequestTimedOut 时 retry（500 ms backoff）；单请求 timeout 降到 1s。**首次同步**时建议重启 IPC 后立即添加（守护进程在启动窗口响应完整）。

NVR 的 quirks：
- NVR 不暴露 `.24` (online) / `.25` (recording) / `.3` (firmware) / `.4` (MAC) / `.7` (CPU%) / `.9` (memory%) / `.8` (storage) 标量。集成在 `NVR_SENSORS` 中替代为最接近的字段。
- **per-channel 存储** 通过 `bytes_used` (`.50001.1.241.1.5.<row>.0`) 报告，没有独立的 disk 子表。
- **`.220` 和 `.221` 是设备特定指标** — `.220` 可能是温度 ×10 或负载计数，`.221` 可能是流量或 IOPS。两者作为 raw int sensor 暴露，用户可自行重命名 / 改单位。

### 不支持（推迟到 v0.2）

- ISAPI / HTTP fallback（SNMP 完全被饿死时）
- 开关 / 控制实体（重启、通道开关）
- 云台控制
- 提交 HACS 默认仓库

### 许可证

MIT © 2026 43457. 详见 `LICENSE`。
