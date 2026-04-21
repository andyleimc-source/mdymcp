#!/usr/bin/env python3
"""mdmcp 一键交互式安装脚本。

用法：clone 仓库后在项目根目录运行
    python3 install.py

脚本会：
  1) 创建 .venv 并安装 mdmcp
  2) 引导你获取 MD_ACCOUNT_ID / MD_KEY（浏览器 OAuth 或手动输入）
  3) 写入 .env
  4) 可选配置 Claude Code MCP（项目级 .mcp.json 或用户级 claude mcp add）
  5) 跑一次 ping 验证
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
MCP_JSON = ROOT / ".mcp.json"


def info(msg: str) -> None:
    print(f"\033[36m[mdmcp]\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"\033[32m✅\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"\033[33m⚠️ \033[0m {msg}")


def err(msg: str) -> None:
    print(f"\033[31m❌\033[0m {msg}", file=sys.stderr)


def ask(q: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        ans = input(f"{q}{suffix}: ").strip()
        if ans:
            return ans
        if default:
            return default


def ask_choice(q: str, options: list[tuple[str, str]], default: str) -> str:
    print(f"\n{q}")
    for k, label in options:
        marker = "*" if k == default else " "
        print(f"  {marker} [{k}] {label}")
    keys = [k for k, _ in options]
    while True:
        ans = input(f"选择 (默认 {default}): ").strip() or default
        if ans in keys:
            return ans
        print(f"  请输入 {'/'.join(keys)}")


def ask_yes(q: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    ans = input(f"{q} [{d}]: ").strip().lower()
    if not ans:
        return default
    return ans in ("y", "yes")


def run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, **kw)


def step_venv() -> Path:
    info("步骤 1/5：准备 Python 虚拟环境")
    py = VENV / "bin" / "python3"
    if not py.exists():
        py_sys = Path(sys.executable)
        info(f"用 {py_sys} 创建 {VENV}")
        run([str(py_sys), "-m", "venv", str(VENV)])
    else:
        info(f"已存在 {VENV}，跳过创建")

    info("安装/更新 mdmcp 包（非 editable，兼容 Python 3.14+）")
    run([str(py), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run([str(py), "-m", "pip", "install", "--quiet", "."], cwd=str(ROOT))
    ok("虚拟环境就绪")
    return py


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def write_env(updates: dict[str, str]) -> None:
    existing = read_env()
    existing.update(updates)
    lines = [f"{k}={v}" for k, v in existing.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def step_credentials(py: Path) -> dict[str, str]:
    info("步骤 2/5：获取明道凭据（MD_ACCOUNT_ID / MD_KEY）")
    existing = read_env()
    if existing.get("MD_ACCOUNT_ID") and existing.get("MD_KEY"):
        ok(f".env 已存在凭据：MD_ACCOUNT_ID={existing['MD_ACCOUNT_ID']}")
        if not ask_yes("要重新获取吗？", default=False):
            return {
                "MD_ACCOUNT_ID": existing["MD_ACCOUNT_ID"],
                "MD_KEY": existing["MD_KEY"],
            }

    info("即将打开系统默认浏览器，请确认当前登录的是你要授权的明道账号。")
    info("授权成功后，脚本会自动把凭据写入 .env。")
    auth_bin = VENV / "bin" / "mdmcp-auth"
    try:
        run([str(auth_bin)], cwd=str(ROOT))
    except subprocess.CalledProcessError as e:
        err(f"OAuth 失败：{e}")
        sys.exit(1)

    creds = read_env()
    if not creds.get("MD_ACCOUNT_ID") or not creds.get("MD_KEY"):
        err("OAuth 完成但未在 .env 找到凭据")
        sys.exit(1)
    out = {"MD_ACCOUNT_ID": creds["MD_ACCOUNT_ID"], "MD_KEY": creds["MD_KEY"]}

    # HAP 网关 refresh_token（独立链路，不强制）
    print()
    info("HAP 网关 refresh_token（让你在 Claude Code 里直接用 48 个 HAP 工具）")
    print("  • 去明道 HAP「集成 → 个人授权」页面拿 refresh_token")
    print("  • 留空回车 = 跳过，仅启用 v1 协作 API 的 50 个工具")
    existing_rt = creds.get("MD_HAP_REFRESH_TOKEN", "")
    if existing_rt:
        ok(f".env 已存在 MD_HAP_REFRESH_TOKEN（…{existing_rt[-6:]}）")
        if ask_yes("要重新填写吗？", default=False):
            existing_rt = ""
    if not existing_rt:
        rt = input("MD_HAP_REFRESH_TOKEN: ").strip()
        if rt:
            write_env({"MD_HAP_REFRESH_TOKEN": rt})
            out["MD_HAP_REFRESH_TOKEN"] = rt
            ok("已写入 .env")
        else:
            warn("跳过 HAP refresh_token，HAP 网关工具将不可用")
    else:
        out["MD_HAP_REFRESH_TOKEN"] = existing_rt
    return out


def _show_and_pause(label: str, payload: dict, response: dict | str) -> None:
    print(f"\n  {label}")
    print(f"  ├─ 输入: {json.dumps(payload, ensure_ascii=False)}")
    print(f"  └─ 输出: {response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)}")


def _stepwise_call(py: Path, env: dict, label: str, code: str) -> tuple[bool, str]:
    """子进程跑一段 Python，返回 (是否成功, 输出 stripped)。"""
    try:
        r = subprocess.run([str(py), "-c", code], env=env, capture_output=True, text=True, check=True)
        return True, r.stdout.strip() or r.stderr.strip()
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + (e.stderr or "")


def step_ping(py: Path, creds: dict[str, str]) -> None:
    info("步骤 3/5：验证凭据可用（每个调用都会先展示输入/输出，确认后继续）")
    env = {**os.environ, **creds}

    # ── v1 token 接口 ──
    print("\n[v1.1] 调用 v1 token hook")
    print("  POST https://api.mingdao.com/workflow/hooks2/NjlkYzQ5NGIwMzM0NzkwYjg4MWY4NTk5")
    print(f"  body: {{\"account_id\":\"{creds['MD_ACCOUNT_ID']}\",\"key\":\"***{creds['MD_KEY'][-6:]}\",\"appname\":\"mdcloud\"}}")
    if not ask_yes("继续打这个请求吗？", default=True):
        err("用户中止")
        sys.exit(1)
    code = (
        "from mdmcp.auth import ensure_access_token;"
        "t=ensure_access_token();"
        "print('TOKEN_LEN=', len(t))"
    )
    success, output = _stepwise_call(py, env, "v1 token", code)
    print(f"  → {output}")
    if not success:
        err("v1 token 换取失败，请检查 MD_ACCOUNT_ID / MD_KEY")
        sys.exit(1)
    ok("v1 凭据有效")

    if not creds.get("MD_HAP_REFRESH_TOKEN"):
        warn("未填 MD_HAP_REFRESH_TOKEN，跳过 HAP 网关验证")
        return

    rt = creds["MD_HAP_REFRESH_TOKEN"]

    # ── HAP register ──
    print("\n[hap.1] 调用 HAP register hook（refresh_token → hap_key）")
    print("  POST https://api.mingdao.com/workflow/hooks2/NjllNjNkYzNiODBlZTc3YjE3NDM1Y2U2")
    print(f"  body: {{\"account_id\":\"{creds['MD_ACCOUNT_ID']}\",\"hap_refresh_token\":\"***{rt[-6:]}\"}}")
    if not ask_yes("继续打这个请求吗？", default=True):
        warn("用户跳过 HAP 验证")
        return
    code = (
        "import os, json, urllib.request;"
        "url='https://api.mingdao.com/workflow/hooks2/NjllNjNkYzNiODBlZTc3YjE3NDM1Y2U2';"
        "body=json.dumps({'account_id':os.environ['MD_ACCOUNT_ID'],'hap_refresh_token':os.environ['MD_HAP_REFRESH_TOKEN']}).encode();"
        "req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'});"
        "print(urllib.request.urlopen(req,timeout=30).read().decode())"
    )
    success, output = _stepwise_call(py, env, "HAP register", code)
    print(f"  → 响应: {output}")
    if not success:
        warn("HAP register 调用失败，HAP 网关将跳过")
        return
    try:
        hap_key = json.loads(output).get("hap_key", "")
    except Exception:
        hap_key = ""
    if not hap_key:
        warn("响应里没拿到 hap_key，HAP 网关将跳过")
        return
    ok(f"hap_key 拿到：{hap_key}")

    # ── HAP token ──
    print("\n[hap.2] 调用 HAP token hook（hap_key → HAP token）")
    print("  POST https://api.mingdao.com/workflow/hooks2/NjllNjQ2NGE2NTAyMDc5NzgxMTFjM2Q3")
    print(f"  body: {{\"account_id\":\"{creds['MD_ACCOUNT_ID']}\",\"hap_key\":\"{hap_key}\"}}")
    if not ask_yes("继续打这个请求吗？", default=True):
        warn("用户跳过 HAP token 验证")
        return
    env_with_hk = {**env, "_HAP_KEY": hap_key}
    code = (
        "import os, json, urllib.request;"
        "url='https://api.mingdao.com/workflow/hooks2/NjllNjQ2NGE2NTAyMDc5NzgxMTFjM2Q3';"
        "body=json.dumps({'account_id':os.environ['MD_ACCOUNT_ID'],'hap_key':os.environ['_HAP_KEY']}).encode();"
        "req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'});"
        "print(urllib.request.urlopen(req,timeout=30).read().decode())"
    )
    success, output = _stepwise_call(py, env_with_hk, "HAP token", code)
    print(f"  → 响应: {output}")
    try:
        hap_token = json.loads(output).get("token", "")
    except Exception:
        hap_token = ""
    if hap_token:
        ok(f"HAP token 换出成功（长度 {len(hap_token)}）")
    else:
        warn("HAP token 为空 —— 服务端工作流可能有 bug，refresh_token 也可能失效")
        warn("v1 工具不受影响；HAP 工具会在 server 启动时跳过")


def step_mcp_config(py: Path, creds: dict[str, str]) -> None:
    info("步骤 4/5：配置 Claude Code MCP Server")
    print("\nmdmcp 需要注册到 Claude Code 才能被识别和调用。有两种注册范围：")
    print("  • 用户级：在任何目录打开 Claude Code 都能用 mdmcp（推荐，装一次全局生效）")
    print("  • 项目级：只在「当前目录」打开 Claude Code 时才能用（想把配置随仓库分发时用）")
    print("  • 两个都配：全局可用，同时把配置也提交到当前仓库")
    print("  • 跳过：你自己手动搞，脚本会打印手动命令给你")
    mode = ask_choice(
        "选择注册范围",
        [
            ("1", "项目级 —— 只在当前目录（在此目录写 .mcp.json）"),
            ("2", "用户级 —— 全局所有目录可用（调用 claude mcp add，推荐）"),
            ("3", "两个都配 —— 全局 + 当前目录"),
            ("4", "跳过 —— 我自己手动配"),
        ],
        default="2",
    )

    env_block = {
        "MD_ACCOUNT_ID": creds["MD_ACCOUNT_ID"],
        "MD_KEY": creds["MD_KEY"],
    }
    if creds.get("MD_HAP_REFRESH_TOKEN"):
        env_block["MD_HAP_REFRESH_TOKEN"] = creds["MD_HAP_REFRESH_TOKEN"]
    server_entry = {
        "type": "stdio",
        "command": str(py),
        "args": ["-m", "mdmcp.server"],
        "env": env_block,
    }

    if mode in ("1", "3"):
        existing: dict = {}
        if MCP_JSON.exists():
            try:
                existing = json.loads(MCP_JSON.read_text(encoding="utf-8"))
            except Exception:
                warn(f"{MCP_JSON} 无法解析，将覆盖")
        existing.setdefault("mcpServers", {})["mdmcp"] = server_entry
        MCP_JSON.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        ok(f"已写入 {MCP_JSON}")

    if mode in ("2", "3"):
        claude_bin = shutil.which("claude")
        if not claude_bin:
            warn("未检测到 `claude` CLI，跳过用户级配置。手动命令见下方。")
            print_user_level_hint(py, creds)
        else:
            info("调用 claude mcp add 注册到用户级…")
            # 先尝试移除已存在的同名条目，避免冲突
            run(
                [claude_bin, "mcp", "remove", "mdmcp", "--scope", "user"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cmd = [
                claude_bin, "mcp", "add", "mdmcp",
                "--scope", "user",
                "-e", f"MD_ACCOUNT_ID={creds['MD_ACCOUNT_ID']}",
                "-e", f"MD_KEY={creds['MD_KEY']}",
            ]
            if creds.get("MD_HAP_REFRESH_TOKEN"):
                cmd += ["-e", f"MD_HAP_REFRESH_TOKEN={creds['MD_HAP_REFRESH_TOKEN']}"]
            cmd += ["--", str(py), "-m", "mdmcp.server"]
            try:
                run(cmd)
                ok("已注册到用户级 Claude Code")
            except subprocess.CalledProcessError as e:
                err(f"claude mcp add 失败：{e}")
                print_user_level_hint(py, creds)

    if mode == "4":
        info("已跳过。参考下面的手动配置：")
        print_user_level_hint(py, creds)


def print_user_level_hint(py: Path, creds: dict[str, str]) -> None:
    print("\n—— 手动配置 Claude Code（用户级）——")
    hap_env = (
        f" -e MD_HAP_REFRESH_TOKEN={creds['MD_HAP_REFRESH_TOKEN']}"
        if creds.get("MD_HAP_REFRESH_TOKEN") else ""
    )
    print(
        f"claude mcp add mdmcp --scope user "
        f"-e MD_ACCOUNT_ID={creds['MD_ACCOUNT_ID']} "
        f"-e MD_KEY={creds['MD_KEY']}{hap_env} "
        f"-- {py} -m mdmcp.server"
    )
    print()


def step_done() -> None:
    info("步骤 5/5：完成")
    ok("mdmcp 安装完毕。重启 Claude Code 即可使用。")
    print("\n试试在 Claude Code 里说：")
    print("  · 「帮我看看最近的公司动态」")
    print("  · 「创建一个明天上午 10 点的日程」")
    print("  · 「列出公司所有部门」")


def preflight() -> None:
    """开工前最低门槛检查：Python 版本 + 命令可用性。"""
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        err(f"Python {major}.{minor} 过低，mdmcp 要求 ≥ 3.10。建议用 Homebrew 装 python@3.12 或更高版本后重试。")
        sys.exit(1)
    if shutil.which("python3") is None:
        err("未检测到 python3 可执行文件。请先安装 Python 3.10+。")
        sys.exit(1)
    # venv / pip 模块内置，一般都有；保险起见做个轻量探测
    try:
        subprocess.run([sys.executable, "-m", "venv", "--help"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError:
        err(f"{sys.executable} 不含 venv 模块。Linux 用户请装 python3-venv；macOS 用户请换 Homebrew Python。")
        sys.exit(1)


def main() -> None:
    print("=" * 56)
    print("  mdmcp 交互式安装")
    print("=" * 56)
    preflight()
    py = step_venv()
    creds = step_credentials(py)
    step_ping(py, creds)
    step_mcp_config(py, creds)
    step_done()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)
