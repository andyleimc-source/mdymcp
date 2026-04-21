# mdmcp

**明道（Mingdao）统一 MCP Server** — 一次 OAuth 授权，获得 **v1 协作 API 50 个工具 + HAP 网关 48 个工具**，共计 ~98 个工具。

由 [雷码工坊](https://github.com/andyleimc-source) 维护。取代早期的 [`md-cloud`](https://github.com/andyleimc-source/md-cloud)（只含 v1）和 [`hap-mcp-cloud-refresh`](https://github.com/andyleimc-source/hap-mcp-cloud-refresh)（Node.js 只含 HAP）。

---

## 功能总览

### 一、v1 协作 API 工具（50 个，本地实现）

覆盖 8 个模块：

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

## 快速开始

```bash
git clone https://github.com/andyleimc-source/mdmcp.git
cd mdmcp
python3 install.py
```

交互式脚本会：

1. 建 `.venv` 并装依赖
2. 引导你浏览器 OAuth 授权
3. 写入 `.env`（`MD_ACCOUNT_ID` / `MD_KEY`）
4. 可选注册到 Claude Code（用户级 / 项目级 / 都配）
5. 跑一次 token 换取验证

装完重启 Claude Code，直接对话：

- "帮我看看最近公司动态" → `post_get_all_posts`（v1）
- "列出我的全部应用" → `get_app_list`（HAP）
- "在 XX 工作表新增一行记录" → `create_record`（HAP）

---

## 架构

```
┌──────────────┐ stdio ┌──────────────────────────────┐
│ Claude Code  │──────▶│        mdmcp.server          │
└──────────────┘       ├──────────────────────────────┤
                       │ [静态注册] 50 个 v1 工具       │──┐
                       ├──────────────────────────────┤  │HTTP
                       │ [动态注册] HapGateway         │──┤
                       │ 48 个 HAP 工具（透明代理）    │  │
                       └──────────────────────────────┘  ▼
                     ┌──────────────────────────────────────┐
                     │ api.mingdao.com/v1/*   (v1 API)      │
                     │ api2.mingdao.com/mcp   (HAP gateway) │
                     └──────────────────────────────────────┘
```

Token：
- 启动不预拉，首次工具调用触发
- 内存缓存到当天本地 23:59:59，次日首次调用重拉
- 不持久化到磁盘

HAP 网关握手失败时**不崩 server**，仅跳过远端工具注册，v1 工具仍可用。

---

## 配置

`.env`（或 Claude Code `.mcp.json` 的 env）：

```env
MD_ACCOUNT_ID=你的明道账号 UUID
MD_KEY=你的接入 key

# HAP 网关 refresh_token（不填则只启用 v1 协作 API 的 50 个工具）
MD_HAP_REFRESH_TOKEN=你的 HAP 个人授权 refresh_token

# 可选（通常不用动）
# MD_HOOK_URL=<自部署 v1 token hook>
# MD_HAP_REGISTER_HOOK=<自部署 HAP register hook>
# MD_HAP_TOKEN_HOOK=<自部署 HAP token hook>
# MD_APP_KEY=<自定义 OAuth app_key>
# MD_REGISTER_URL=<自定义注册 hook>
# MD_CALLBACK_PORT=8080
```

---

## 故障排查

| 现象 | 原因 | 解决 |
|------|------|------|
| `Missing MD_ACCOUNT_ID or MD_KEY` | .env 没配 | 跑 `python3 install.py` 或手工填 `.env` |
| `Token endpoint returned no token: {'token': ''}` | 服务端 hook 工作流挂了 | 联系运营方查工作流执行历史 |
| 启动显示 `HAP 网关工具 0 个` | `/mcp` 握手失败 | 网络问题；v1 工具不受影响 |
| HAP 工具返回 `Http Headers verification failed` | HAP 后端对该工具有额外鉴权要求 | HAP 侧既有问题（Node 版也有），非 mdmcp bug |

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
