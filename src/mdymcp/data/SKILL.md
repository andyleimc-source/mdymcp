---
name: mdymcp
description: Andy 自研的明道统一 MCP（mdymcp）的使用心智与故障 SOP。当通过 mdymcp 工具查明道日程/动态/群组/成员/记录/应用/工作表/审批，或遇到 token 失效/600100/"token无效或过期"报错、`[HAP]`/`[v1]` 前缀错误、不知道某个 mdymcp 工具走哪套凭证时使用。
---

# mdymcp 使用指南

Andy 自研包（`andyleimc-source/mdymcp`，PyPI）。**两套独立凭证**，分别供两组工具用——这是绝大多数困惑的根源。

## 两套凭证心智模型

| | v1 协作 API | HAP 网关 |
|---|---|---|
| 凭证 | **server 模式**：access_token 从腾讯云常驻服务器现取（见下） | `MD_HAP_PAT`（个人 PAT，pat_ 开头，自助生成） |
| token 函数 | `ensure_access_token()`（按 `MD_V1_TOKEN_MODE` 分流：server / local / 旧 hook） | `ensure_hap_token()`（直接返回 PAT，无网络） |
| 稳定性 | 稳（服务器单点 refresh-daemon 刷，客户端只读，不抢刷） | 稳（PAT 长期有效、用户自管） |
| 覆盖工具 | 日程 `calendar_*`、组织 `company_*`、群组 `group_*`、动态 `post_*`、私信 `webchat_*`、用户 `user_*`/`find_member`(注：find_member 走 HAP)、消息 `message_*`、通行证 `passport_*` | 应用/工作表/记录/审批/角色：`get_app_list`、`get_worksheet_structure`、`get_record_list`、`create_record`、`update_record`、`find_member`、`find_department` 等 |

判断某工具走哪套：**操作"低代码应用/工作表/记录/审批/成员"= HAP；操作"协作动态/日程/群组/私信"= v1。** 拿不准就看报错前缀（`[HAP]` / `[v1]`）。

### v1 token 怎么来（v0.5.1 默认 server 模式）

Andy 三台 mac 现在都跑 **server 模式**（`.env` 里 `MD_V1_TOKEN_MODE=server`）：

- `ensure_access_token()` → `_ensure_server_token()`：用**受限 SSH key** 远程读常驻服务器上的 token 文件，取出 `access_token`。
- 服务器：`ubuntu@101.43.4.46`（腾讯云内地）。SSH host/user/key/远程路径配在 `~/.mdymcp/.env`（`MD_V1_TOKEN_SSH_HOST/SSH_USER/SSH_KEY/REMOTE_PATH`）。
- 客户端**不写本地 token 文件、不持有 refresh_token、绝不本地 refresh**；取到的 token 只进内存缓存，缓存到当地午夜。
- 真正的刷新由**服务器上的 refresh-daemon 单点负责**。
- **为什么**：明道 oauth2 每次 refresh 都轮换 refresh_token，多个端各自本地刷会互相把对方顶成孤儿 → token 失效。集中到服务器单点刷、客户端只读，才稳。
- 配置/重配：`mdymcp-server-setup`。

另两条只是回落路径，正常用不到：
- `MD_V1_TOKEN_MODE=local`：`mdymcp-auth` 浏览器授权 → 本地 `~/.mdymcp/v1_token.json`，本地 refresh（access ~7 天、refresh 14 天滚动）。**多端共用同一账号时不要用**（会抢刷）。
- 旧 hook（`MD_ACCOUNT_ID+MD_KEY`）：未迁移机器的远端 hook 换 token，迁完即弃。

## 故障 SOP

**报 `[HAP]` / 600100 / "token无效或过期" / "PAT 已失效"** = HAP 的 `MD_HAP_PAT` 失效或缺失。

- 去 **https://www.mingdao.com/personal?type=pat** 重新生成 PAT（已登录直接生成；未登录先登录会自动跳回）。
- 把新 `pat_xxx` 更新到 `.env` 的 `MD_HAP_PAT`，或重跑 `mdymcp-install`。
- 不再有"自愈/register"——PAT 由用户自管，没有自动续期这一步。

**报 `[v1]`**（server 模式）= 取不到服务器上的 token：
- `server 模式取 token 失败（SSH 连不上 …）` → 腾讯云 `101.43.4.46` 不通 / SSH key 失效，先 `ssh ubuntu@101.43.4.46` 验连通；连不上查服务器和受限 key。
- `server 模式缺配置` / `SSH key 不存在` → `~/.mdymcp/.env` 缺 `MD_V1_TOKEN_*`，跑 **`mdymcp-server-setup`** 重配。
- `服务器 token 文件里没有 access_token` → 服务器上的 refresh-daemon 挂了，登服务器查 daemon（见仓库 `server/` 与 `handoff-mdymcp-server-refresh.md`）。

**报 `[v1]`**（local 模式回落，正常不用）= `本地无可用 token` / `刷新 token 失败` → 跑 **`mdymcp-auth`** 重新授权（开浏览器点一下）。

**一行自查**（只打印 token 长度，不泄漏值，遵 `secrets-handling`）：
```
/Users/andy/.local/share/uv/tools/mdymcp/bin/python3 -c "from mdymcp.auth import ensure_access_token,ensure_hap_token as h; print('v1',len(ensure_access_token()),'hap',len(h()))"
```
两个都打出长度 = 两套都通。

## 日历（`calendar_get_events`）约定

- **数据基于日历订阅 feed，通常只到当天**——查未来日期基本返回空，不是 bug。
- **看某人日程**：用 `organizer=` 参数（邮箱或姓名子串），例 `calendar_get_events(organizer="phil.ren")` 查任向晖。**不要**自己拉全量再 jq 过滤。
- **不传日期**：默认 `[今天-30, 今天]`（0.2.7+），不会再拉全量 2600+ 条爆上下文。要更早的显式传 `start_date`。
- 结果超 `limit`（默认 200）会按时间倒序截断并带 `truncated: true`。

## 版本/发布

源码 `~/code/mdymcp`（clone），改完 bump version → 发 PyPI → 三台 mac `uv tool upgrade mdymcp`（不动 `~/.mdymcp/.env`）。skill 走 dotfiles 同步（见 skill `mac-sync`）。
