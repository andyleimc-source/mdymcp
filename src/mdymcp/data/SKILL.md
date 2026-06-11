---
name: mdymcp
description: Andy 自研的明道统一 MCP（mdymcp）的使用心智与故障 SOP。当通过 mdymcp 工具查明道日程/动态/群组/成员/记录/应用/工作表/审批，或遇到 token 失效/600100/"token无效或过期"报错、`[HAP]`/`[v1]` 前缀错误、不知道某个 mdymcp 工具走哪套凭证时使用。
---

# mdymcp 使用指南

Andy 自研包（`andyleimc-source/mdymcp`，PyPI）。**两套独立凭证**，分别供两组工具用——这是绝大多数困惑的根源。

## 两套凭证心智模型

| | v1 协作 API | HAP 网关 |
|---|---|---|
| 凭证 | 本地 token 文件 `~/.mdymcp/v1_token.json`（OAuth 签发，`MD_APP_SECRET` 支撑刷新） | `MD_HAP_PAT`（个人 PAT，pat_ 开头，自助生成） |
| token 函数 | `ensure_access_token()`（本地文件 → 过期自动 refresh） | `ensure_hap_token()`（直接返回 PAT，无网络） |
| 稳定性 | 稳（access_token 约 7 天，refresh_token 14 天滚动续期，全本地） | 稳（PAT 长期有效、用户自管） |
| 覆盖工具 | 日程 `calendar_*`、组织 `company_*`、群组 `group_*`、动态 `post_*`、私信 `webchat_*`、用户 `user_*`/`find_member`(注：find_member 走 HAP)、消息 `message_*`、通行证 `passport_*` | 应用/工作表/记录/审批/角色：`get_app_list`、`get_worksheet_structure`、`get_record_list`、`create_record`、`update_record`、`find_member`、`find_department` 等 |

判断某工具走哪套：**操作"低代码应用/工作表/记录/审批/成员"= HAP；操作"协作动态/日程/群组/私信"= v1。** 拿不准就看报错前缀（`[HAP]` / `[v1]`）。

## 故障 SOP

**报 `[HAP]` / 600100 / "token无效或过期" / "PAT 已失效"** = HAP 的 `MD_HAP_PAT` 失效或缺失。

- 去 **https://www.mingdao.com/personal?type=pat** 重新生成 PAT（已登录直接生成；未登录先登录会自动跳回）。
- 把新 `pat_xxx` 更新到 `.env` 的 `MD_HAP_PAT`，或重跑 `mdymcp-install`。
- 不再有"自愈/register"——PAT 由用户自管，没有自动续期这一步。

**报 `[v1]`** = 本地 token 链路问题（0.4.0+ 全本地，无服务端 hook）：
- `本地无可用 token` / `刷新 token 失败` → refresh_token 过期（14 天没用过）或 token 文件损坏，跑 **`mdymcp-auth`** 重新授权（开浏览器点一下）。
- `缺 MD_APP_SECRET` → 开放平台「我的应用」查 app_secret，写入 `~/.mdymcp/.env`。
- token 文件可直接看过期时间：`python3 -c "import json,time;d=json.load(open('/Users/andy/.mdymcp/v1_token.json'));print('expires in',round((d['expires_at']-time.time())/3600,1),'h')"`

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
