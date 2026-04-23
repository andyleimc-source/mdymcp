"""CLI 入口：`mdymcp-auth` — 浏览器一键 OAuth 授权，自动写 .env。"""

from __future__ import annotations

import sys
from pathlib import Path

from . import auth


def main() -> None:
    try:
        auth.run_auth_flow(project_root=Path.cwd())
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ {e}", file=sys.stderr)
        sys.exit(1)
    print("\n✅ 完成。现在可以在 .mcp.json 中配置 mdymcp 并重启 Claude Code。")


if __name__ == "__main__":
    main()
