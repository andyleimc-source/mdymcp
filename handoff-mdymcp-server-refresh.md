# Handoff · mdymcp v1 Token 服务器集中刷新

> 目标：**彻底解决 mdymcp v1 协作 token 的授权问题**——让任意机器/服务器都不再各自持有、各自刷新 v1 token，改由一个常驻服务器单点刷新，客户端按需取用。
>
> 这份 handoff 写在 weekly-md 项目里只是临时落脚；**改造对象是 `mdymcp` 包本身**，下一轮请把它移到 mdymcp 源码仓库再开工。

---

## 1. 背景：今天踩的坑 + 已确认的真因

发布周刊时 v1 token 失效，报 `error_code: 10101 / refresh_token对应的access_token不存在`。排查结论（**已读源码 + token 文件确认**）：

- v1 **access_token 寿命 24h**（`expires_in` 默认 86400，见 `auth.py:_exchange_token`）。
- v1 **refresh_token 有效期 ~14 天**，但关键不是它过期——
- **明道 oauth2 每次 refresh 都会轮换 refresh_token**（铁证：`auth.py` 的跨进程锁注释原文“防止同机多个 MCP 进程同时 refresh 把 refresh_token 轮换两次”，且 `_exchange_token` 每次都从响应里读新的 `refresh_token` 落盘）。
- 推论：**任意两个持有同一对 token 的端，谁先刷新，就把另一个顶成孤儿**。我有三台 Mac + 今天还有并行进程，互相顶掉 → 孤儿 token 刷不动 → `access_token不存在`。

> 所以这不是“授权太短”，是“**多个 owner 抢着刷新**”。Andy 的方案（集中到一个常驻 owner）是对症下药。

本会话已在 weekly-md 侧加了**发布前 token 预检**（commit `47f41c4`，`publisher.preflight_token`），那只是兜底——让失效在发布前一行报清楚。本改造落地后，预检退化成廉价健康检查即可。

---

## 2. 核心设计（Andy 的方案，原话保留）

1. 安装 mdymcp 时让用户选：**本地刷新**（现状）或 **服务器刷新**（新增）。
2. 选服务器刷新 → 用户提供服务器登录信息（登录名 / IP / 密码）。
3. 刷新工作放在 Andy 的**腾讯云内地服务器**（见 skill `personal-servers`）。
4. 服务器常驻，每 ~23h 用 refresh_token 自动刷新。
5. mdymcp 要 v1 token 时直接去服务器拿，不再本地保存。

---

## 3. 设计决策（Andy 已拍板 ✅）

### ✅ 方向正确
单一 owner 刷新 = 唯一对症解。只要这台服务器持续运行（刷新间隔 < 14d），**rolling refresh 会让 token 链无限续命**（每次刷新拿到新 refresh_token 并持久化）；其余所有端只读、永不刷新、永不孤儿。

### ✅ 决策 1：客户端**不留缓存，每次都去服务器拿**
理由（Andy）：mdymcp 取 v1 token 的频率很低，不用为缓存增加复杂度。
- 含义：`ensure_access_token()` 在 server 模式下，每次调用都现取。
- 接受的代价：取 token **硬依赖服务器在线 + 网络通**（频率低，可接受）。失败时给清晰报错（指向服务器/网络），别静默。

### ✅ 决策 2：取 token 走 **SSH**（不上 HTTP broker）
理由（Andy）：自用、自己的机器和服务器，SSH 简单、熟悉。
- **安全做法（必做）**：用一把**专用、受限的 SSH key**——在服务器 `authorized_keys` 里给这把 key 配 **forced command**（`command="cat /path/to/token.json"`），并加 `no-pty,no-port-forwarding` 等限制。这样这把 key **只能读 token 那一个文件，开不了 shell**，等于“SSH 的简单 + broker 的窄泄漏面”都拿到。
- **不要在客户端存明文登录密码**；安装时收集的“登录名/IP/密码”只用于**一次性 provision**（部署 daemon、布受限 key、种 seed），之后日常取 token 只用那把受限 key。
- HTTP broker 方案**搁置**，等将来真要对外开放给陌生用户时再上（那时窄泄漏面才值得多维护一个 web 服务）。

### ✅ 决策 3：作用域 = **每个用户用自己的服务器**
用户自带 login/IP/密码，mdymcp 帮他把 refresher 部署到**他自己的**服务器。**Andy 不托管任何人的明道 token**，不当别人凭证的保管人。多租户/托管模型不做。

### ⚠️ 实现注意：刷新间隔按返回的 expires_in 动态调度，别写死 23h
`expires_in` 服务端可能给非 86400 的值。daemon 应按“`expires_at - 安全余量(如1h)`”动态定时，而不是硬编码 23h。

### ⚠️ 仍绕不开：初始授权要一次浏览器 OAuth
拿第一个 refresh_token 种子免不了浏览器授权一次。流程：本地 `mdymcp-auth` 浏览器授权 → 把 seed token 推到服务器 → 服务器接管轮换。一次性，无法消除。

---

## 4. 目标架构

```
┌─ 用户自己的服务器（常驻 owner；Andy 用腾讯云内地，见 skill personal-servers）─┐
│  refresh-daemon  每周期（按 expires_in 动态，约 23h）：                       │
│     POST {BASE_API_URL}/oauth2/access_token  grant_type=refresh_token        │
│     → 持久化新的 {access_token, refresh_token, expires_at}（0600）            │
│     → 刷新失败重试 + 告警（否则 14 天后静默死亡）                             │
│  token 文件落在固定路径，例：/opt/mdymcp/v1_token.json（0600，专用用户）       │
└─────────────────────────────────────────────────────────────────────────┘
        ▲ 安装时一次性 SSH provision（部署 daemon、布受限 key、种 seed）
        │ 日常：受限 SSH key 远程读 token 文件（forced command 只允许 cat）
┌─ 客户端（任意 Mac / 服务器，mdymcp）──────────────────────────────────────┐
│  MD_V1_TOKEN_MODE=server                                                   │
│  ensure_access_token():                                                    │
│     每次都现取：ssh -i <受限key> user@ip  → 拿到 {access_token,expires_at}  │
│     不缓存、不落本地、永不 refresh / 永不持有 refresh_token                  │
│     取失败 → 明确报错（指向服务器/网络），不静默                             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 5. mdymcp 改造点（具体到文件/函数）

源码现状（venv 装的副本，仅供参考路径）：
`…/site-packages/mdymcp/auth.py`。**真正要改的是 mdymcp 的 git 仓库**（任务 0：先找到它，PyPI 名 `mdymcp`，疑似 andyleimc-source 下，待确认）。

关键现有符号：
- `ensure_access_token()`（≈ `auth.py:248`）：当前分发 local / legacy hook。**在这里加 `server` 分支。**
- `_ensure_local_token()`（`:185`）：本地链路（读文件→过期则 refresh）。server 模式**不走它**。
- `_exchange_token(grant_type, **params)`（`:139`）：调 oauth2 换 token。**daemon 复用这段逻辑。**
- `_write_token_file` / `_read_token_file` / `_TokenFileLock`（`:111-123`、`:86`）：token 持久化与锁。
- token 文件结构：`{access_token, refresh_token, expires_at, obtained_at}`，`~/.mdymcp/v1_token.json`，0600。

要新增：
- `_ensure_server_token()`：**每次**用受限 SSH key 远程读 token 文件、解析出 access_token 返回。**不缓存、不写本地、不持有 refresh_token。** 取失败抛带指引的错误（指向服务器/网络/重新种子）。
- 配置键（`~/.mdymcp/.env`）：
  - `MD_V1_TOKEN_MODE=local|server`（默认 local，向后兼容）
  - server 模式：`MD_V1_TOKEN_SSH_HOST`、`MD_V1_TOKEN_SSH_USER`、`MD_V1_TOKEN_SSH_KEY`（受限 key 路径）、`MD_V1_TOKEN_REMOTE_PATH`（服务器上 token 文件路径，可选/有默认）。
- 安装引导：扩展 `mdymcp-auth`（或新增 `mdymcp setup`）——交互选 local/server；选 server 则收集 SSH 登录信息（一次性）→ provision → 种 seed → 写客户端配置（host/user/受限 key 路径）。

服务器端新增组件（建议放进 mdymcp 仓库的 `server/` 子目录，可独立部署）：
- `refresh-daemon`：systemd timer 或常驻进程；按 expires_in 动态定时；失败重试 + 告警（邮件/server酱/明道动态皆可）。复用 `_exchange_token` 逻辑，持久化新 token 对（含新 refresh_token）。
- token 文件：固定路径 0600、专用用户；受限 SSH key 的 forced command 只允许 `cat` 这个文件。
- **provision 脚本**：用一次性 SSH 登录把 daemon 装上、生成并安装受限 key（`authorized_keys` 配 `command="cat <path>",no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding`）、种入 seed token、起 timer。

---

## 6. 风险 & 失败模式（务必覆盖）

| 风险 | 处理 |
|---|---|
| 服务器宕机 > 14 天 → token 链断 | 刷新成功率监控 + 告警；提供一键重新种子（本地 `mdymcp-auth` → 推服务器）|
| refresh 接口偶发失败 | daemon 重试（指数退避）；连续失败 N 次告警 |
| 取 token 硬依赖服务器/网络（无缓存，Andy 已接受） | 失败时明确报错指向服务器/网络；频率低，影响可控 |
| 受限 SSH key 泄漏 | forced command 锁死成只读 token 一个文件 + no-pty 等；key 可单独轮换、不影响服务器其它访问 |
| 客户端误在 server 模式下 refresh | 代码层硬禁用：server 模式只读远程 token，绝不本地 refresh / 不持有 refresh_token |
| 时钟漂移 | daemon 用 expires_at 绝对时间 + 安全余量；服务器 NTP |
| 仍有别的端在 local 模式抢刷同一账号 | 切 server 后，**所有端**都要切 server；文档强调“一个账号只能有一个 owner” |

---

## 7. 验收标准

- 三台 Mac + 任意服务器全部切到 server 模式后，**连续 ≥7 天零手动 `mdymcp-auth`** 仍能稳定拿 token。
- 人为让某客户端“抢刷”不再可能（代码禁用 + 测试覆盖）。
- 服务器刷新失败能在 1 个周期内告警，不静默。
- local 模式行为完全不变（向后兼容）。

---

## 8. 下一轮起步清单（按顺序）

> §3 决策已定（不缓存 / SSH+受限key / 各自服务器），可直接开工。

0. ✅ **找到 mdymcp 源码 git 仓库** → `/Users/andy/code/mdymcp`（GitHub: andyleimc-source/mdymcp）。
1. ✅ 通读 `auth.py`，确认 refresh 轮换行为 + `ensure_access_token` 现有分发（local / legacy hook）。
2. ✅ **已部署到腾讯云内地 101.43.4.46**（2026-06-15）：daemon + systemd timer active；首跑 `OK: 无需刷新 23h59m`；受限 key 自测能 cat、`no-pty` 挡 shell 生效；install 步骤 2 用 server 模式实际 SSH 取 token 验证通过（`v1 凭据有效`）。本机 Mac 已切 server。（Mac 对该服务器本就免密 key 登录、sudo 免密，故 provision 全程无需输密码。）
3. ✅ `ensure_access_token` 加 server 分支 + `_ensure_server_token`（受限 SSH key 远程读、每次现取、只进程内存缓存、绝不本地 refresh）。`auth.py`。
4. ✅ 写 provision + 向导：`server/provision.sh`（一次性部署）+ `mdymcp-server-setup`（`cli_server_setup.py`，交互向导）+ `server/refresh_daemon.py` + systemd `.service`/`.timer` + `server/README.md`。
5. ✅ **已发版 + 全量部署验证**（2026-06-15，最终版 PyPI `mdymcp 0.5.1`）。详见下方「当前状态」。

---

## 当前状态（2026-06-15，截至 0.5.1）

### 版本线
- `0.5.0`：新增 server 集中刷新模式（client server 分支 + provision 工具链 + `mdymcp-server-setup`）。
- `0.5.1`：**修 `_load_env` 屏蔽 bug**——改为合并所有 .env（先出现键优先，后补缺失），项目自带 .env（如 meta 的 META_*）不再屏蔽 `~/.mdymcp/.env` 的 MD 凭据。**这是当前线上版本。**

### 服务器（唯一 owner）
- 腾讯云内地 `101.43.4.46`：`server/refresh_daemon.py` + systemd timer active，每小时检查、快过期才刷。token 在 `/opt/mdymcp/v1_token.json`（0600）。
- 受限 key：ubuntu `authorized_keys` 配 forced command `cat /opt/mdymcp/v1_token.json` + `no-pty` 等，只读一个文件。
- 运维：`journalctl -u mdymcp-refresh`、`systemctl status mdymcp-refresh.timer`。

### 三台 Mac × 三个项目（v1 走 server，HAP 走全局 PAT）
| 机器 | 全局 mdymcp | weekly-md .venv | 切 server |
|---|---|---|---|
| work `100.82.108.123` | ✅ 0.5.1 | ✅ 0.5.1 | ✅ |
| m1pro `100.86.179.75` | ✅ 0.5.1 | ✅ 0.5.1 | ✅ |
| air `100.120.85.2` | ⏳ 待开机切（离线） | ⏳ | ⏳ |

- 项目：`~/Desktop/dailymd`（只走全局 binary）、`~/Documents/running/hap/weekly-md`（全局 + 自有 .venv import 调用，**venv 是第二份 mdymcp 需单独升**）、`~/Documents/running/meta`（自带 .env 只有 META_*，靠 0.5.1 的合并修复才能拿到 MD 凭据）。
- work + m1pro 上 3×2=6 处「项目目录下取 v1+HAP」已全部验证通过（v1=64位 server token，HAP=pat_…）。

### air 开机后切 server（一条命令）
```
curl -fsSL https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/scripts/switch-to-server.sh | bash
```
脚本（VERSION=0.5.1）：拉受限 key（默认从 work，`PEER=100.86.179.75` 可改 m1pro）+ 装全局 0.5.1 + 写 4 个 MD_V1_TOKEN_* + 升 weekly-md venv + 验证。⚠️ **别在 air 上 `mdymcp-auth` 重授权**（会轮换种子顶孤儿）。

### 两个踩过的坑（已修，复盘）
1. **`.env` 屏蔽**：`_load_env` 旧实现读到第一个 .env 就 return → 带自有 .env 的项目里 mdymcp 完全拿不到 MD 凭据。0.5.1 改合并已修。新项目随便放自己的 .env，不影响。
2. **项目第二份 mdymcp**：`.mcp.json` 走全局 binary，但项目若 venv 里 `import mdymcp`（如 weekly-md），那份独立、需单独 `uv pip install -U mdymcp` 升级。

### 下一轮起步 / 待办
- air 开机切 server（上面那条命令）。
- 跑满一周看服务器 `journalctl -u mdymcp-refresh`：每天应有 1 次成功 refresh、不再 10101 → 验收过。
- 若新增用 mdymcp 的项目且带自有 venv，记得 `uv pip install -U mdymcp` 升级那份。

### 历史（0.5.0 本轮已落地的实现）
- 客户端：`auth.py` 的 `_ensure_server_token` + `MD_V1_TOKEN_MODE=server` 分支；配置键 `MD_V1_TOKEN_SSH_HOST/USER/KEY` + 可选 `MD_V1_TOKEN_REMOTE_PATH`。
- 服务器 kit：`server/`（daemon one-shot + systemd timer + provision.sh + README，零三方依赖）。
- 安装向导：`mdymcp-install` 步骤1 必选 本地/服务器（强制选，无默认）；`mdymcp-server-setup` 直达服务器部署。
- `scripts/switch-to-server.sh`：一键把任意 Mac 切 server 只读客户端。

---

## 9. 参考

- skill `personal-servers` —— 腾讯云内地服务器 IP / SSH。
- skill `mdymcp` —— 凭证心智、token 失效 SOP。
- `~/.mdymcp/.env`（MD_ACCOUNT_ID / MD_KEY / MD_HAP_PAT）、`~/.mdymcp/v1_token.json`。
- weekly-md commit `47f41c4` —— 已加发布前 token 预检（兜底，本改造落地后退化为健康检查）。
- 本会话已确认：access_token 24h、refresh_token ~14d 且**每刷新必轮换**——这是整个设计成立的前提。
