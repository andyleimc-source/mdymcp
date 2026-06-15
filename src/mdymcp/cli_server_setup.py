"""CLI 入口：`mdymcp-server-setup` — 把 v1 token 刷新一次性部署到你自己的服务器。

server 模式心智（见仓库 handoff-mdymcp-server-refresh.md）：
  - v1 token 失效的真因不是「授权太短」，是「多个端抢着 refresh，互相把对方顶成孤儿」
    （明道 oauth2 每次 refresh 都轮换 refresh_token）。
  - 解法：让**一台常驻服务器当唯一 owner** 单点刷新，其余所有端只读、永不刷新。
  - 本命令在**做初始 provision 的那一台机器**上跑一次即可；其余机器只需把生成的
    受限 key + 4 个 MD_V1_TOKEN_* 配置拷过去。

只在做初始部署的机器上需要本命令；它会调用仓库里的 server/provision.sh。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import auth


def _find_provision_script() -> Path | None:
    """从 clone 仓库里找 server/provision.sh（site-packages 安装则找不到，回落手动指引）。"""
    here = Path(__file__).resolve()
    for base in (here.parents[2], here.parents[1], Path.cwd()):
        cand = base / "server" / "provision.sh"
        if cand.exists():
            return cand
    return None


def main() -> None:
    home = Path.home() / ".mdymcp"
    home.mkdir(parents=True, exist_ok=True)
    seed = home / "v1_token.json"

    print("== mdymcp server 模式部署 ==")
    print("把 v1 token 的刷新集中到你自己的一台常驻服务器（单 owner），彻底治好「token 互相顶掉」。\n")

    # 1. seed token：没有就先走一次浏览器授权
    if not seed.exists() or '"refresh_token"' not in seed.read_text(encoding="utf-8"):
        print("→ 还没有可用的 seed token（含 refresh_token）。先做一次浏览器授权拿种子…")
        try:
            os.environ["MDYMCP_SKIP_PAT_PROMPT"] = "1"
            auth.run_auth_flow(project_root=home)
        except Exception as e:
            print(f"❌ 授权失败：{e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"→ 已有 seed token：{seed}")

    # 2. 收集服务器信息
    host = input("\n服务器 IP/域名: ").strip()
    if not host:
        print("❌ 没填服务器地址，退出。", file=sys.stderr)
        sys.exit(1)
    ssh_user = input("登录用户 [ubuntu]: ").strip() or "ubuntu"

    # 3. 跑 provision.sh
    script = _find_provision_script()
    if script is None:
        print("\n⚠️ 没找到 server/provision.sh（你大概是 pip/uv 装的，不是 clone 仓库）。")
        print("   provision 只需在一台机器上做一次，请到 clone 的仓库里手动跑：")
        print(f"     bash server/provision.sh {host} {ssh_user}")
        print("   之后把 ~/.mdymcp/server_token_key 和 .env 里 4 个 MD_V1_TOKEN_* 拷到本机即可。")
        sys.exit(2)

    print(f"\n→ 运行 {script} …（过程中可能要你输服务器登录密码 / sudo 密码）\n")
    try:
        subprocess.run(["bash", str(script), host, ssh_user], check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ provision 失败（退出码 {e.returncode}）。", file=sys.stderr)
        sys.exit(e.returncode)

    print("\n✅ 完成。本机已切到 server 模式，重启 MCP 客户端生效。")


if __name__ == "__main__":
    main()
