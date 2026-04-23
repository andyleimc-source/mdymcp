"""MCP Server entry point — mdymcp (明道协作 v1 + HAP 网关合并版)."""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import Tool
from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.types import CallToolResult, TextContent
from pydantic import ConfigDict

from . import (
    tools_calendar,
    tools_company,
    tools_group,
    tools_message,
    tools_passport,
    tools_post,
    tools_user,
    tools_webchat,
)
from .gateway import HapGateway

log = logging.getLogger("mdymcp")

mcp = FastMCP(
    "mdymcp",
    instructions=(
        "明道统一 MCP：v1 协作 API（动态/日程/群组/用户/组织/私信/收件箱/账户）+ "
        "HAP 网关（应用/工作表/记录/审批/角色）。无需 OAuth 授权，仅需 .env 配置 "
        "MD_ACCOUNT_ID 与 MD_KEY，token 由服务端每日自动刷新。"
    ),
)

# 静态注册：44 个 v1 协作 API 工具
tools_post.register(mcp)
tools_calendar.register(mcp)
tools_webchat.register(mcp)
tools_message.register(mcp)
tools_group.register(mcp)
tools_user.register(mcp)
tools_company.register(mcp)
tools_passport.register(mcp)


# ─────────────────────────────────────────────────────────────
# 动态注册：HAP 网关的远端工具（透明代理 api2.mingdao.com/mcp）
# ─────────────────────────────────────────────────────────────

class _PassThroughArgs(ArgModelBase):
    """允许任意字段的参数模型 —— 把 MCP 客户端传的参数原样透传给远端网关。"""

    model_config = ConfigDict(extra="allow")

    def model_dump_one_level(self) -> dict[str, Any]:  # type: ignore[override]
        return dict(self.model_extra or {})


def _make_delegator(gateway: HapGateway, remote_name: str):
    def delegator(**kwargs: Any) -> CallToolResult:
        raw = gateway.call_tool(remote_name, kwargs)
        content = raw.get("content") or [
            TextContent(type="text", text=str(raw))
        ]
        return CallToolResult(
            content=content,
            structuredContent=raw.get("structuredContent"),
            isError=bool(raw.get("isError", False)),
        )

    delegator.__name__ = remote_name
    return delegator


def _register_gateway_tools() -> int:
    gateway = HapGateway()
    tools = gateway.list_tools()
    if not tools:
        return 0

    fn_metadata = FuncMetadata(arg_model=_PassThroughArgs)
    registered = 0
    for schema in tools:
        name = schema.get("name")
        if not name or name in mcp._tool_manager._tools:
            continue
        tool = Tool(
            fn=_make_delegator(gateway, name),
            name=name,
            description=schema.get("description", ""),
            parameters=schema.get("inputSchema") or {"type": "object"},
            fn_metadata=fn_metadata,
            is_async=False,
        )
        mcp._tool_manager._tools[name] = tool
        registered += 1
    return registered


_hap_count = _register_gateway_tools()
log.info("mdymcp 已加载 %d 个本地 v1 工具 + %d 个 HAP 网关工具",
         len(mcp._tool_manager._tools) - _hap_count, _hap_count)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
