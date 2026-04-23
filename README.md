# mdymcp

**明道（Mingdao）统一 MCP Server** — 一次安装，获得 **v1 协作 API 50 个工具 + HAP 网关 48 个工具**，共计 ~98 个工具。

由 [雷码工坊](https://github.com/andyleimc-source) 维护。取代早期的 [`md-cloud`](https://github.com/andyleimc-source/md-cloud)（只含 v1）和 [`hap-mcp-cloud-refresh`](https://github.com/andyleimc-source/hap-mcp-cloud-refresh)（Node.js 只含 HAP）。

---

## 一键安装

支持 **macOS / Linux / Windows** + **Intel / Apple Silicon**。底层用 [uv](https://docs.astral.sh/uv/) 管理 Python 解释器，你机器上装的是 3.14、3.9 还是没装 Python 都不影响 —— uv 会自己拉一个合适的。

### macOS / Linux

```bash
curl -LsSf https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/install.sh | sh
```

### Windows（PowerShell）

```powershell
powershell -c "irm https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/install.ps1 | iex"
```

脚本会：
1. 检测 uv，没装就从官方源装上
2. `uv tool install mdymcp`（如果以前装过老版本 pipx 的 `mdymcp`，先 `pipx uninstall mdymcp`）
3. 启动 `mdymcp-install` 交互向导 —— 浏览器 OAuth 拿 v1 凭据 → 自动跳出 HAP 授权页拿 HAP token → 自动检测已装的 AI IDE 并注册

配置写在 `~/.mdymcp/.env`（Windows: `%USERPROFILE%\.mdymcp\.env`），跨目录都能用。旧版 `~/.mdmcp/` 会在首次运行时自动迁移过来。

### 装完后想重跑配置

```bash
mdymcp-install              # 已通过 uv tool install 装过的话
uvx --from mdymcp mdymcp-install   # 临时跑一次，不持久安装
```

## 支持的 AI IDE

| IDE | 配置文件 | 用户级 / 项目级 |
|-----|---------|----------------|
| **Claude Code** | `~/.claude.json`（通过 `claude mcp add`） | 用户级 + 可选项目级 `.mcp.json` |
| **Codex CLI** | `~/.codex/config.toml` | 用户级 |
| **Cursor** | `~/.cursor/mcp.json` | 用户级 |
| **Windsurf** | `~/.codeium/windsurf/mcp_config.json` | 用户级 |
| **Gemini Antigravity** | `~/.gemini/antigravity/mcp_config.json` | 用户级 |
| **Trae** | `~/Library/Application Support/Trae/User/mcp.json`（mac）`%APPDATA%\Trae\User\mcp.json`（win）`~/.config/Trae/User/mcp.json`（linux），国内版替换为 `Trae CN` | 用户级 |
| **VS Code** (Copilot Chat) | `.vscode/mcp.json` | 项目级 |

`mdymcp-install` 会自动检测装了哪些 IDE 并询问是否批量注册。手动指定：`mdymcp-install --client=cursor,windsurf,trae`（逗号分隔任意组合；`--client=all` 全装）。

> **Antigravity**：写完后去 IDE 里「Manage MCP Servers → Refresh」一下才能看到 mdymcp。
>
> **Cursor / Windsurf / Trae / VS Code**：通常需要重启 IDE 或在 MCP 设置里手动刷新。

---

## 老路径（仍然可用）

### pipx 安装

```bash
pipx install mdymcp
mdymcp-install
```

### Clone 仓库（开发者 / 跟代码）

> 项目目录**不要放 iCloud 同步路径**（如 `~/Desktop`、`~/Documents`），建议放 `~/Downloads`、`~/code` 等本地目录。

```bash
git clone https://github.com/andyleimc-source/mdymcp.git
cd mdymcp
python3 install.py
```

装完重启任一 AI IDE，直接对话即可：

- "帮我看看最近公司动态" → `post_get_all_posts`（v1）
- "列出我的全部应用" → `get_app_list`（HAP）
- "在 XX 工作表新增一行记录" → `create_record`（HAP）

> 调试模式：`MDYMCP_INSTALL_DEBUG=1 python3 install.py` 或 `python3 install.py --debug`，会逐步显示每个 hook 的请求体/响应并 y/n 拦截，仅开发者用。

---

## 怎么拿 HAP 的 refresh_token 和 access token

> 装好之后，`mdymcp-install` 的 HAP 步骤会**自动打开授权页**（下面的 URL），你按截图走一遍复制粘贴即可，**下面的截图教程是备份参考**。

HAP 网关需要在明道**集成中心**做一次个人授权，拿到一对 `refresh_token` + `access_token` 喂给 install 脚本。

授权页：<https://www.mingdao.com/integrationConnect/69bcae07257900ec41aa2733>

### 第 1 步：集成中心 → API 库 → HAP API（个人授权）→ 立即授权

![step1](https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/docs/images/hap-step1-authorize.png)

进入「集成 → API 库」，找到 **HAP API（个人授权）**，点右上角「立即授权」走完 OAuth 流程。

### 第 2 步：「我的连接 → 授权」tab，找到刚授权的连接

![step2](https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/docs/images/hap-step2-connections.png)

### 第 3 步：进入连接，在账户行点 `...` → 查看日志

![step3](https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/docs/images/hap-step3-account-menu.png)

### 第 4 步：在日志列表中找一条「获取 token」→ 点查看详情

![step4](https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/docs/images/hap-step4-log-list.png)

### 第 5 步：在「返回值」标签里复制 `access_token` 和 `refresh_token`

![step5](https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/docs/images/hap-step5-tokens.png)

在 `mdymcp-install` 提示时分别粘到：
- `MD_HAP_TOKEN:` ← 粘 `access_token`
- `MD_HAP_REFRESH_TOKEN:` ← 粘 `refresh_token`

> 这两个 token 只在装机时用一次（用于把你的账号绑定到服务端，换出长期 `hap_key`）。绑定完成后 IDE 里的 mdymcp 只用 `hap_key` + `account_id` 调 token hook 拿当天的 HAP token，不再需要它们。

---

## 功能总览

### 一、v1 协作 API 工具（50 个，本地实现）

| 模块 | 数量 | 主要能力 |
|------|-----|---------|
| 动态 (post) | 9 | 全公司/我的/用户/群组动态、详情、评论、发布、删除 |
| 日程 (calendar) | 8 | 列表、详情、邀请、搜索、创建、编辑、删除 |
| 私信 (webchat) | 6 | 会话、消息、未读、发送 |
| 收件箱 (message) | 2 | 系统通知、动态相关通知 |
| 群组 (group) | 10 | 详情、成员、加入/创建、管理员管理 |
| 用户 (user) | 6 | 联系人、组织成员、@搜索、按手机/邮箱查找 |
| 组织 (company) | 3 | 组织、部门、按 ID 查询 |
| 个人账户 (passport) | 4 | 当前用户详情、设置、未读、名片 |

工具签名与 `md-cloud` / `mdold` 完全一致，drop-in 可替换。

### 二、HAP 网关工具（48 个，透明代理）

启动时自动拉取 `api2.mingdao.com/mcp` 的工具清单并注册到本地 MCP。覆盖：

- **应用管理**：`get_app_list` / `get_app_info` / `create_app` / `update_app` / `delete_app`
- **工作表**：`get_app_worksheets_list` / `get_worksheet_structure` / `create_worksheet` / `update_worksheet` / `delete_worksheet`
- **记录**：`get_record_list` / `get_record_details` / `create_record` / `update_record` / `delete_record` / 批量增删改 / `get_record_logs` / `get_record_relations` / `get_record_discussions` / `get_record_share_link` / `get_record_pivot_data`
- **角色/成员**：`get_role_list` / `create_role` / `delete_role` / `add_member_to_role` / `remove_member_from_role` / `find_member` / `find_department` / `leave_all_roles`
- **工作流 / 审批**：`get_workflow_list` / `get_workflow_details` / `trigger_workflow` / `get_approval_list_by_row` / `get_approval_detail`
- **图表 / 自定义页**：`create_chart` / `save_custom_page`
- **选项集 / 知识库 / 地区 / 组织**：`create_optionset` / `update_optionset` / `delete_optionset` / `get_optionset_list` / `knowledge_search` / `get_app_knowledge_list` / `get_regions` / `get_org_list`
- **工具**：`get_time`

HAP 工具由远端网关动态提供；具体参数 schema 以启动时 `tools/list` 返回的为准。

---

## 架构与 Token 机制

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

**Token 刷新**：

| | v1 access_token | HAP token |
|---|---|---|
| install 时 | OAuth → `MD_KEY` 写入 `.env` | register（一次性）→ `MD_HAP_KEY` 写入 `.env` |
| 运行时拉 token | 1 次请求：v1 token hook | 1 次请求：HAP token hook |
| 缓存 TTL | 到本地次日 00:00 | 到本地次日 00:00 |
| 每天 token 请求数 | 1 | 1 |

每天首次调用时拉一次 token、缓存到本地次日 00:00；不持久化到磁盘。HAP 网关握手失败时**不崩 server**，仅跳过远端工具注册，v1 工具仍可用。

---

## 配置

`~/.mdymcp/.env`（或 IDE 的 MCP JSON 的 env 块）：

```env
# 必填：v1 协作 API
MD_ACCOUNT_ID=你的明道账号 UUID
MD_KEY=你的接入 key

# HAP 网关（mdymcp-install 走完后自动写入）
MD_HAP_REFRESH_TOKEN=  # install 时粘贴
MD_HAP_TOKEN=          # install 时粘贴
MD_HAP_KEY=            # mdymcp-install 自动写入

# 可选（通常不用动）
# MD_HOOK_URL=<自部署 v1 token hook>
# MD_HAP_REGISTER_HOOK=<自部署 HAP register hook>
# MD_HAP_TOKEN_HOOK=<自部署 HAP token hook>
# MD_APP_KEY=<自定义 OAuth app_key>
# MD_REGISTER_URL=<自定义 v1 OAuth 注册 hook>
# MD_CALLBACK_PORT=8080
```

---

## 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| `command not found: uv` | 装完 uv 但新 shell 没继承 PATH | 重开终端；或 `export PATH="$HOME/.local/bin:$PATH"` |
| curl 或 irm 拉 astral.sh 失败 | 公司网络 / 国内网络拦截 | 走代理；或从 <https://github.com/astral-sh/uv/releases> 下载 tarball 手动解压到 `~/.local/bin/` |
| Windows 下 `irm \| iex` 报执行策略错误 | 企业 GPO 限制 PowerShell 脚本执行 | 在管理员 PowerShell 跑 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`；或联系 IT |
| `Missing MD_ACCOUNT_ID or MD_KEY` | .env 没配 | 重跑 `mdymcp-install` |
| `Missing MD_ACCOUNT_ID or MD_HAP_KEY` | HAP 没注册 | 重跑 `mdymcp-install` 走 HAP 步骤 |
| `SSL: CERTIFICATE_VERIFY_FAILED` | macOS 上 python.org 安装的 Python 没装根证书 | 一次性执行 `/Applications/Python\ 3.x/Install\ Certificates.command`（3.x 填你的版本号）；或者干脆用 uv 安装路径，uv 拉的 Python 自带证书 |
| Antigravity / Cursor / Windsurf 里看不到 mdymcp | 配置文件已写但 IDE 未刷新 | 重启 IDE；或在 IDE 的 MCP 设置里点 Refresh。如果 IDE 从 macOS GUI 启动又找不到 `uvx`，改为从终端启动 IDE（GUI 继承不到 shell 的 PATH），或让 `mdymcp-install` 把 uvx 绝对路径写进配置（默认就是这样做的） |
| `HAP token 接口返回空` | hap_key 在服务端失效（refresh_token 过期等） | 按上面文档重新拿一对 token + refresh_token，重跑 `mdymcp-install` |
| 启动显示 `HAP 网关工具 0 个` | `/mcp` 握手失败 | 网络问题；v1 工具不受影响 |
| HAP 工具返回 `Http Headers verification failed` | HAP 后端对该工具有额外鉴权要求 | HAP 侧既有问题（Node 版也有），非 mdymcp bug |
| Python 3.14 / 3.9 报错 | 系统 Python 版本太新或太老 | 用 uv 安装路径，uv 会自动挑合适的 Python，不受系统 Python 影响 |

---

## 与前代项目

| 项目 | 覆盖 | 状态 |
|------|-----|------|
| `mdold` | v1 + 本地 OAuth | 已停止维护 |
| `md-cloud` | v1 + 云端 token | 已由 mdymcp 取代 |
| `hap-mcp-cloud-refresh` | HAP 代理（Node） | 已由 mdymcp 取代 |
| **mdymcp** | v1 + HAP + 多 IDE | **推荐使用** |

---

## API 参考

明道开放平台：<https://open.mingdao.com/document>

## License

MIT
