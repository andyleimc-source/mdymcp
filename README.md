# mdmcp

**明道（Mingdao）统一 MCP Server** — 一次安装，获得 **v1 协作 API 50 个工具 + HAP 网关 48 个工具**，共计 ~98 个工具。

由 [雷码工坊](https://github.com/andyleimc-source) 维护。取代早期的 [`md-cloud`](https://github.com/andyleimc-source/md-cloud)（只含 v1）和 [`hap-mcp-cloud-refresh`](https://github.com/andyleimc-source/hap-mcp-cloud-refresh)（Node.js 只含 HAP）。

---

## 一键安装

> 要求：macOS / Linux，Python ≥ 3.10（推荐 Homebrew `python@3.12` 或更高），项目目录**不要放 iCloud 同步路径**（如 `~/Desktop`、`~/Documents`），建议放 `~/Downloads`、`~/code` 等本地目录。

```bash
git clone https://github.com/andyleimc-source/mdmcp.git
cd mdmcp
python3 install.py
```

交互脚本会自动：

1. 建 `.venv` 并装依赖
2. 浏览器 OAuth 拿 v1 凭据 → 写入 `.env`
3. **提示你粘贴 HAP 凭据**（refresh_token + access token，下面教你怎么拿）→ 自动 register 拿 `hap_key` → 写入 `.env`
4. **自动检测**你装的 MCP 客户端，注册到 **Claude Code** 和/或 **Codex CLI**（用户级，全局生效）
5. 验证 token 可拉

> **多客户端支持**：脚本会扫 `claude` 和 `codex` 两个 CLI，**装哪个就自动注册到哪个**，都装就都配。要手动指定：`python3 install.py --client=claude` / `--client=codex` / `--client=both`。要额外写一份 `.mcp.json` 到当前仓库（项目级 Claude）：加 `--project`。

装完重启 Claude Code，直接对话即可：

- "帮我看看最近公司动态" → `post_get_all_posts`（v1）
- "列出我的全部应用" → `get_app_list`（HAP）
- "在 XX 工作表新增一行记录" → `create_record`（HAP）

> 调试模式：`MDMCP_INSTALL_DEBUG=1 python3 install.py` 或 `python3 install.py --debug`，会逐步显示每个 hook 的请求体/响应并 y/n 拦截，仅开发者用。

---

## 怎么拿 HAP 的 refresh_token 和 access token

HAP 网关需要在明道**集成中心**做一次个人授权，拿到一对 `refresh_token` + `access_token` 喂给 install 脚本。

### 第 1 步：集成中心 → API 库 → HAP API（个人授权）→ 立即授权

![step1](docs/images/hap-step1-authorize.png)

进入「集成 → API 库」，找到 **HAP API（个人授权）**，点右上角「立即授权」走完 OAuth 流程。

### 第 2 步：「我的连接 → 授权」tab，找到刚授权的连接

![step2](docs/images/hap-step2-connections.png)

### 第 3 步：进入连接，在账户行点 `...` → 查看日志

![step3](docs/images/hap-step3-account-menu.png)

### 第 4 步：在日志列表中找一条「获取 token」→ 点查看详情

![step4](docs/images/hap-step4-log-list.png)

### 第 5 步：在「返回值」标签里复制 `access_token` 和 `refresh_token`

![step5](docs/images/hap-step5-tokens.png)

把这两个值在 install.py 提示时分别粘到：
- `MD_HAP_TOKEN:` ← 粘 `access_token`
- `MD_HAP_REFRESH_TOKEN:` ← 粘 `refresh_token`

> 这两个 token 只在 `install.py` 时用一次（用于把你的账号绑定到服务端，换出长期 `hap_key`）。绑定完成后 Claude Code 运行时只用 `hap_key` + `account_id` 调 token hook 拿当天的 HAP token，不再需要它们。

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
┌──────────────┐ stdio ┌──────────────────────────────┐
│ Claude Code  │──────▶│        mdmcp.server          │
└──────────────┘       ├──────────────────────────────┤
                       │ [静态注册] 50 个 v1 工具     │──┐
                       ├──────────────────────────────┤  │HTTP
                       │ [动态注册] HapGateway        │──┤
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

`.env`（或 Claude Code `.mcp.json` 的 env）：

```env
# 必填：v1 协作 API
MD_ACCOUNT_ID=你的明道账号 UUID
MD_KEY=你的接入 key

# HAP 网关（install.py 走完后自动写入）
MD_HAP_REFRESH_TOKEN=  # install 时粘贴
MD_HAP_TOKEN=          # install 时粘贴
MD_HAP_KEY=            # install.py 自动写入

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
| `Missing MD_ACCOUNT_ID or MD_KEY` | .env 没配 | 跑 `python3 install.py` 或手工填 `.env` |
| `Missing MD_ACCOUNT_ID or MD_HAP_KEY` | HAP 没注册 | 重跑 `python3 install.py` 走 HAP 步骤 |
| `HAP token 接口返回空` | hap_key 在服务端失效（refresh_token 过期等） | 按上面文档重新拿一对 token + refresh_token，重跑 install |
| 启动显示 `HAP 网关工具 0 个` | `/mcp` 握手失败 | 网络问题；v1 工具不受影响 |
| HAP 工具返回 `Http Headers verification failed` | HAP 后端对该工具有额外鉴权要求 | HAP 侧既有问题（Node 版也有），非 mdmcp bug |
| `ensurepip` 失败、venv 装不上 | python.org 的 3.14 安装包 ensurepip 有 bug；或目录在 iCloud 同步范围被吞文件 | 换 Homebrew `python@3.12`；项目挪出 `~/Desktop` / `~/Documents` |

---

## 与前代项目

| 项目 | 覆盖 | 状态 |
|------|-----|------|
| `mdold` | v1 + 本地 OAuth | 已停止维护 |
| `md-cloud` | v1 + 云端 token | 已由 mdmcp 取代 |
| `hap-mcp-cloud-refresh` | HAP 代理（Node） | 已由 mdmcp 取代 |
| **mdmcp** | v1 + HAP | **推荐使用** |

---

## API 参考

明道开放平台：<https://open.mingdao.com/document>

## License

MIT
