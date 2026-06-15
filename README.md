# mdymcp

> ## ⬆️ 已装过的用户升级（0.3.0，重要）
>
> 0.3.0 起 **HAP 改用个人 PAT**，不再走旧的 `refresh_token / hap_key` 那套。两步搞定：
>
> **1) 升级程序**
> ```bash
> uv tool upgrade mdymcp
> ```
>
> **2) 换 HAP 凭据**：去 <https://www.mingdao.com/personal?type=pat> 生成一个 PAT（`pat_` 开头），然后任选其一：
> - **省事**：直接重跑 `mdymcp-install`，走到 HAP 步骤粘进去即可；
> - **手动**：编辑 `~/.mdymcp/.env`，**删掉** `MD_HAP_KEY` / `MD_HAP_REFRESH_TOKEN` / `MD_HAP_TOKEN`，**加上** `MD_HAP_PAT=pat_xxx`。
>
> 改完重启 IDE。只用 v1 工具、没配过 HAP 的用户：`uv tool upgrade mdymcp` 即可，无需改动。

## 一键安装

**macOS / Linux**
```bash
curl -LsSf https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/install.sh | sh
```

**Windows（PowerShell）**
```powershell
powershell -c "irm https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/install.ps1 | iex"
```

脚本做三件事：
1. 检测 `uv`，没装就从官方源装上（uv 会自己拉合适的 Python，你机器上是 3.14 / 3.9 还是没装都没关系）
2. `uv tool install mdymcp`
3. 启动 `mdymcp-install` 交互向导 —— 浏览器 OAuth 拿 v1 凭据 → 自动打开 HAP 个人 PAT 页粘 `MD_HAP_PAT` → 让你选范围（用户级/项目级/两个都要）+ 编号多选要注册的 IDE → 检测到 Claude Code 时自动安装 mdymcp skill（使用心智 + 故障 SOP）到 `~/.claude/skills/mdymcp/`

配置写在 `~/.mdymcp/.env`（Windows: `%USERPROFILE%\.mdymcp\.env`），跨目录都能用。

装完后想重跑：`mdymcp-install`

---

## 功能

**明道（Mingdao）统一 MCP Server** —— 一次安装，**98 个工具**：

- **v1 协作 API（50 个，本地实现）**：动态 / 日程 / 私信 / 收件箱 / 群组 / 用户 / 组织 / 个人账户
- **HAP 网关（48 个，透明代理 `api2.mingdao.com/mcp`）**：应用 / 工作表 / 记录 / 角色成员 / 工作流审批 / 图表 / 选项集 / 知识库 / 地区组织

HAP 工具由远端网关动态提供；具体参数 schema 以启动时 `tools/list` 返回的为准。

## 支持的 AI IDE

| IDE | 配置文件 | 支持范围 |
|-----|---------|---------|
| **Claude Code** | `~/.claude.json`（通过 `claude mcp add`） | 用户级 + 项目级 `.mcp.json` |
| **Codex CLI** | `~/.codex/config.toml` | 用户级 |
| **Cursor** | `~/.cursor/mcp.json` | 用户级 + 项目级 `.cursor/mcp.json` |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` | 用户级 |
| **Gemini Antigravity** | `~/.gemini/antigravity/mcp_config.json` | 用户级 |
| **Trae**（含国内版 Trae CN） | mac: `~/Library/Application Support/Trae/User/mcp.json`<br>win: `%APPDATA%\Trae\User\mcp.json`<br>linux: `~/.config/Trae/User/mcp.json` | 用户级 |
| **VS Code**（Copilot Chat） | `.vscode/mcp.json` | 项目级 |

`mdymcp-install` 会自动检测已装的 IDE，范围 + 客户端两个问题你挑完即可。手动指定：`mdymcp-install --client=cursor,windsurf,trae`（`--client=all` 全装）。

> **Antigravity**：写完后去 IDE 里「Manage MCP Servers → Refresh」一下才能看到 mdymcp。
>
> **Cursor / Windsurf / Trae / VS Code**：通常需要重启 IDE 或在 MCP 设置里手动刷新。

---

## 怎么拿 HAP 的 PAT

> `mdymcp-install` 走到 HAP 步骤时会**自动开浏览器**到 PAT 页，复制粘贴即可。

PAT 页：<https://www.mingdao.com/personal?type=pat>

- **已登录** → 直接在页面生成/管理个人 PAT（`pat_` 开头）。
- **未登录** → 先登录，会自动跳回该页。

复制 `pat_xxx`，在向导提示 `MD_HAP_PAT:` 时粘进去即可。PAT 本身就是 Bearer token，长期有效、你自己可随时吊销重发，无需服务端交换。留空 = 跳过 HAP，只用 v1 工具。

---

## 架构与 Token

```
┌──────────────────────┐ stdio ┌──────────────────────────────┐
│ Claude Code / Cursor │──────▶│        mdymcp.server         │
│ / Codex / Windsurf / │       ├──────────────────────────────┤
│ Antigravity / Trae / │       │ [静态注册] 50 个 v1 工具     │──┐
│ VS Code Copilot      │       ├──────────────────────────────┤  │HTTP
└──────────────────────┘       │ [动态注册] HapGateway        │──┤
                               │ 48 个 HAP 工具（透明代理）   │  │
                               └──────────────────────────────┘  ▼
                             ┌──────────────────────────────────────┐
                             │ api.mingdao.com/v1/*   (v1 API)      │
                             │ api2.mingdao.com/mcp   (HAP gateway) │
                             └──────────────────────────────────────┘
```

| | v1 access_token | HAP token |
|---|---|---|
| install 时 | 本地 OAuth → token 写入 `~/.mdymcp/v1_token.json` | 粘 PAT → `MD_HAP_PAT` 写入 `.env` |
| 运行时 | 本地 token 文件，过期用 refresh_token 本地续期 | 直接用 `MD_HAP_PAT`，无远端交换 |
| 缓存 TTL | 跟随明道下发的 expires_in（已发布应用 7 天） | 不需要（PAT 即 token） |

v1 token 全程本地：`mdymcp-auth` 授权一次拿 access_token + refresh_token 落盘（chmod 600），过期自动用 refresh_token（14 天有效）续期，refresh 也过期才需重新授权。app_key/app_secret 内嵌在包里（公共客户端模式，同 Google/GitHub CLI），零配置。已有旧凭据（MD_ACCOUNT_ID/MD_KEY）且未授权的机器回落老的远端 hook 链路。HAP 直接用 `.env` 里的 PAT 当 Bearer token。HAP 网关握手失败时**不崩 server**，仅跳过远端工具注册，v1 工具仍可用。

**多机共用同一账号？用 server 模式。** 多台机器/服务器持同一对 token 会互相抢刷（明道每次 refresh 都轮换 refresh_token），把对方顶成孤儿（`error_code 10101`）。把刷新集中到一台常驻服务器当唯一 owner：跑一次 `mdymcp-server-setup`（或 `bash server/provision.sh <IP> <user>`），其余机器只读、永不刷新。详见 [`server/README.md`](server/README.md)。

---

## 配置

`~/.mdymcp/.env`（或各 IDE 的 MCP JSON 里的 env 块）：

```env
# HAP 网关 PAT（在 https://www.mingdao.com/personal?type=pat 生成，pat_ 开头）
MD_HAP_PAT=  # install 时粘贴；留空 = 跳过 HAP

# 可选（通常不用动）
# MD_APP_KEY= / MD_APP_SECRET=<换成自己的 OAuth 应用>
# MD_CALLBACK_PORT=8080
# 旧链路回落（未配 MD_APP_SECRET 时才用）
# MD_ACCOUNT_ID= / MD_KEY= / MD_HOOK_URL=
```

---

## 故障排查

| 现象 | 解决 |
|------|------|
| `command not found: uv` | 重开终端；或 `export PATH="$HOME/.local/bin:$PATH"` |
| curl / irm 拉 astral.sh 失败 | 走代理；或从 <https://github.com/astral-sh/uv/releases> 下载 tarball 手动解压到 `~/.local/bin/` |
| Windows 下 `irm \| iex` 报执行策略错误 | 管理员 PowerShell：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `[v1] 本地无可用 token` / `刷新 token 失败` | 跑 `mdymcp-auth` 重新授权（refresh_token 14 天没用过会过期） |
| `缺 MD_HAP_PAT` / `PAT 无效或已过期` | 去 <https://www.mingdao.com/personal?type=pat> 重新生成 PAT，更新 `.env` 的 `MD_HAP_PAT` 或重跑 `mdymcp-install` |
| IDE 里看不到 mdymcp | 重启 IDE；或在 IDE 的 MCP 设置里点 Refresh。GUI 启动找不到 `uvx` 时改从终端启动 IDE（默认写绝对路径应该已规避这个） |
| 启动显示 `HAP 网关工具 0 个` | `/mcp` 握手失败（多半是网络）；v1 工具不受影响 |
| HAP 工具返回 `Http Headers verification failed` | HAP 后端既有问题（Node 版也有），非 mdymcp bug |

---

## API 参考

明道开放平台：<https://open.mingdao.com/document>

## License

MIT
