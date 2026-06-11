"""CLI 入口：`mdymcp-auth` — 浏览器一键 OAuth 授权（v1），并顺带检查/补填 HAP PAT。"""

from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from . import auth

HAP_PAT_URL = "https://www.mingdao.com/personal?type=pat"


def _check_hap_pat(env_path: Path) -> None:
    """v1 授权完成后顺带体检 HAP 凭证：缺 PAT 就引导补填，发现旧版残留就清理。

    0.2.x → 0.4.x 跳级用户的 .env 里只有已废弃的 MD_HAP_TOKEN/REFRESH/KEY，
    没有这步会静默丢掉全部 HAP 工具（应用/工作表/记录/审批）。
    """
    from .cli_install import read_env, _clean_token  # 复用解析逻辑

    existing = read_env(env_path)
    legacy = sorted(auth.LEGACY_HAP_KEYS & set(existing))

    if _clean_token(existing.get("MD_HAP_PAT", "")):
        if legacy:
            auth._purge_env_vars(env_path, auth.LEGACY_HAP_KEYS)
            print(f"→ 已清理旧版 HAP 凭据残留（{', '.join(legacy)}），现在只用 MD_HAP_PAT。")
        return

    print()
    if legacy:
        print(f"⚠️  检测到旧版 HAP 凭据（{', '.join(legacy)}）——0.3.0 起已废弃，现在只认 MD_HAP_PAT。")
    print("HAP 网关 PAT 未配置：没有它就用不了应用/工作表/记录/审批这一半工具（日程/动态等 v1 工具不受影响）。")
    print(f"  • 即将打开 PAT 页：{HAP_PAT_URL}")
    print("  • 已登录 → 直接生成/复制 PAT；未登录 → 登录后会自动跳回该页")
    try:
        webbrowser.open(HAP_PAT_URL)
    except Exception:
        pass
    pat = _clean_token(input("MD_HAP_PAT (pat_xxx，回车跳过): "))
    if not pat:
        print("→ 跳过。之后可在 ~/.mdymcp/.env 加 MD_HAP_PAT=pat_xxx 并重启 MCP 客户端启用 HAP 工具。")
        return
    auth._write_env_vars(env_path, {"MD_HAP_PAT": pat})
    auth._purge_env_vars(env_path, auth.LEGACY_HAP_KEYS)
    # 实拉一次远端工具清单验证 PAT 可用
    try:
        from .gateway import HapGateway
        os.environ["MD_HAP_PAT"] = pat
        count = len(HapGateway().list_tools())
    except Exception:
        count = 0
    if count > 0:
        print(f"→ PAT 有效（{count} 个 HAP 网关工具可用），已写入 {env_path}")
    else:
        print("⚠️  PAT 已写入，但验证拉取工具清单失败（可能是网络）。重启 MCP 后若 HAP 工具仍缺，"
              f"请去 {HAP_PAT_URL} 重新生成。")


def main() -> None:
    target = Path.home() / ".mdymcp"
    target.mkdir(parents=True, exist_ok=True)
    try:
        auth.run_auth_flow(project_root=target)
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ {e}", file=sys.stderr)
        sys.exit(1)

    # mdymcp-install 自己有 PAT 步骤，置 MDYMCP_SKIP_PAT_PROMPT=1 避免重复问
    if os.environ.get("MDYMCP_SKIP_PAT_PROMPT", "").strip() not in ("1", "true", "yes"):
        try:
            _check_hap_pat(target / ".env")
        except KeyboardInterrupt:
            print("\n→ 已跳过 PAT 配置。")

    print("\n✅ 完成。重启 MCP 客户端（或重开会话）生效。")


if __name__ == "__main__":
    main()
