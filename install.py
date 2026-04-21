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
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"

# 调试模式：MDMCP_INSTALL_DEBUG=1 或 --debug 启用，逐步显示每个网络请求并 y/n 确认
DEBUG = os.getenv("MDMCP_INSTALL_DEBUG", "").strip() in ("1", "true", "yes") \
        or "--debug" in sys.argv

# --client=claude|codex|both 覆盖自动检测；--project 额外写一份 .mcp.json 到当前仓库
def _parse_client_flag() -> set[str] | None:
    for a in sys.argv[1:]:
        if a.startswith("--client="):
            v = a.split("=", 1)[1].lower().strip()
            if v in ("both", "all"):
                return {"claude", "codex"}
            return {x for x in v.split(",") if x in ("claude", "codex")}
    return None

CLIENT_OVERRIDE = _parse_client_flag()
WRITE_PROJECT_MCP = "--project" in sys.argv


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


def _try_git_pull() -> None:
    """仓库已是 git clone 时主动 pull，避免复用老代码跑旧逻辑。"""
    if not (ROOT / ".git").exists():
        return
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            msg = r.stdout.strip() or "已是最新"
            info(f"git pull：{msg.splitlines()[-1]}")
        else:
            warn(f"git pull 失败，将继续使用当前代码：{r.stderr.strip()[:160]}")
    except Exception as e:
        warn(f"git pull 异常：{e}")


def step_venv() -> Path:
    info("步骤 1/5：准备 Python 虚拟环境")
    _try_git_pull()
    py = VENV / "bin" / "python3"
    if not py.exists():
        py_sys = Path(sys.executable)
        info(f"用 {py_sys} 创建 {VENV}")
        run([str(py_sys), "-m", "venv", str(VENV)])
    else:
        info(f"已存在 {VENV}，跳过创建")

    info("安装/更新 mdmcp 包（--upgrade 强制拉最新本地代码）")
    run([str(py), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run([str(py), "-m", "pip", "install", "--quiet", "--upgrade", "--force-reinstall",
         "--no-deps", "."], cwd=str(ROOT))
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

    # HAP 网关凭据（独立链路，不强制；需要 refresh_token + access token 一起注册到服务端）
    print()
    info("HAP 网关凭据（让你在 Claude Code 里直接用 48 个 HAP 工具）")
    print("  • 去明道 HAP「集成 → 个人授权」页面，复制 refresh_token 和 access token")
    print("  • 任一留空 = 跳过 HAP，仅启用 v1 协作 API 的 50 个工具")
    existing_rt = creds.get("MD_HAP_REFRESH_TOKEN", "")
    existing_tk = creds.get("MD_HAP_TOKEN", "")
    if existing_rt and existing_tk:
        ok(f".env 已存在 HAP 凭据（refresh…{existing_rt[-6:]} / token…{existing_tk[-6:]}）")
        if not ask_yes("要重新填写吗？", default=False):
            out["MD_HAP_REFRESH_TOKEN"] = existing_rt
            out["MD_HAP_TOKEN"] = existing_tk
            return out
    rt = input("MD_HAP_REFRESH_TOKEN: ").strip()
    tk = input("MD_HAP_TOKEN: ").strip() if rt else ""
    if rt and tk:
        write_env({"MD_HAP_REFRESH_TOKEN": rt, "MD_HAP_TOKEN": tk})
        out["MD_HAP_REFRESH_TOKEN"] = rt
        out["MD_HAP_TOKEN"] = tk
        ok("已写入 .env")
    else:
        warn("HAP 凭据不完整，跳过 HAP 网关；v1 工具不受影响")
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


def _hap_register_call(py: Path, env: dict) -> tuple[bool, str]:
    code = (
        "from mdmcp.auth import hap_register;"
        "import os;"
        "print(hap_register(os.environ['MD_ACCOUNT_ID'], os.environ['MD_HAP_REFRESH_TOKEN'], os.environ['MD_HAP_TOKEN']))"
    )
    return _stepwise_call(py, env, "HAP register", code)


def _hap_token_validate(py: Path, env: dict) -> tuple[bool, str]:
    code = "from mdmcp.auth import ensure_hap_token; print(len(ensure_hap_token()))"
    return _stepwise_call(py, env, "HAP token", code)


def step_ping(py: Path, creds: dict[str, str]) -> dict[str, str]:
    """验证凭据；HAP 路径里完成一次性 register，把 hap_key 写回 .env 并返回。"""
    info("步骤 3/5：验证凭据可用" + ("（调试模式 step-by-step）" if DEBUG else ""))
    env = {**os.environ, **creds}
    out = dict(creds)

    # ── v1 token ──
    if DEBUG:
        print("\n[v1.1] 调用 v1 token hook")
        print("  POST https://api.mingdao.com/workflow/hooks2/NjlkYzQ5NGIwMzM0NzkwYjg4MWY4NTk5")
        print(f"  body: {{\"account_id\":\"{creds['MD_ACCOUNT_ID']}\",\"key\":\"***{creds['MD_KEY'][-6:]}\"}}")
        if not ask_yes("继续打这个请求吗？", default=True):
            err("用户中止"); sys.exit(1)
    success, output = _stepwise_call(py, env, "v1 token",
        "from mdmcp.auth import ensure_access_token; print(len(ensure_access_token()))")
    if DEBUG:
        print(f"  → token 长度 {output.strip()}")
    if not success:
        err(f"v1 token 换取失败：{output.strip()}"); sys.exit(1)
    ok("v1 凭据有效")

    if not creds.get("MD_HAP_REFRESH_TOKEN") or not creds.get("MD_HAP_TOKEN"):
        warn("未填 HAP 凭据，跳过 HAP 网关；仅启用 50 个 v1 工具")
        return out

    # ── HAP register（一次性） ──
    if DEBUG:
        rt, tk = creds["MD_HAP_REFRESH_TOKEN"], creds["MD_HAP_TOKEN"]
        print("\n[hap.1] 调用 HAP register hook（一次性绑定，写回 MD_HAP_KEY）")
        print("  POST https://api.mingdao.com/workflow/hooks2/NjllNjNkYzNiODBlZTc3YjE3NDM1Y2U2")
        print(f"  body: {{\"account_id\":\"{creds['MD_ACCOUNT_ID']}\",\"hap_refresh_token\":\"***{rt[-6:]}\",\"hap_token\":\"***{tk[-6:]}\"}}")
        if not ask_yes("继续打这个请求吗？", default=True):
            warn("用户跳过 HAP 验证"); return out
    success, output = _hap_register_call(py, env)
    hap_key = output.strip().splitlines()[-1] if success and output.strip() else ""
    if DEBUG:
        print(f"  → hap_key: {hap_key or output.strip()}")
    if not hap_key:
        warn(f"HAP register 失败，HAP 工具将跳过；v1 不受影响 ({output.strip()[-120:]})")
        return out
    write_env({"MD_HAP_KEY": hap_key})
    out["MD_HAP_KEY"] = hap_key
    env["MD_HAP_KEY"] = hap_key
    ok(f"HAP 已注册（hap_key 写入 .env）")

    # ── HAP token 验证 ──
    if DEBUG:
        print("\n[hap.2] 调用 HAP token hook 验证（hap_key → token）")
        print("  POST https://api.mingdao.com/workflow/hooks2/NjllNjQ2NGE2NTAyMDc5NzgxMTFjM2Q3")
        print(f"  body: {{\"account_id\":\"{creds['MD_ACCOUNT_ID']}\",\"hap_key\":\"{hap_key}\"}}")
        if not ask_yes("继续打这个请求吗？", default=True):
            warn("用户跳过 HAP token 验证"); return out
    success, output = _hap_token_validate(py, env)
    if DEBUG:
        print(f"  → token 长度: {output.strip()}")
    if success:
        ok("HAP 凭据有效（48 个 HAP 工具可用）")
    else:
        warn(f"HAP token 验证失败：{output.strip()[-160:]}")
    return out


def _build_env_block(creds: dict[str, str]) -> dict[str, str]:
    env_block = {"MD_ACCOUNT_ID": creds["MD_ACCOUNT_ID"], "MD_KEY": creds["MD_KEY"]}
    if creds.get("MD_HAP_KEY"):
        env_block["MD_HAP_KEY"] = creds["MD_HAP_KEY"]
    return env_block


def _register_claude_user(claude_bin: str, py: Path, env_block: dict[str, str]) -> bool:
    run([claude_bin, "mcp", "remove", "mdmcp", "--scope", "user"],
        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = [claude_bin, "mcp", "add", "mdmcp", "--scope", "user"]
    for k, v in env_block.items():
        cmd += ["-e", f"{k}={v}"]
    cmd += ["--", str(py), "-m", "mdmcp.server"]
    try:
        run(cmd, stdout=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError as e:
        err(f"claude mcp add 失败：{e}")
        return False


def _write_project_mcp_json(py: Path, env_block: dict[str, str]) -> None:
    server_entry = {"type": "stdio", "command": str(py),
                    "args": ["-m", "mdmcp.server"], "env": env_block}
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


def _register_codex(py: Path, env_block: dict[str, str]) -> bool:
    """在 ~/.codex/config.toml 里增/改 [mcp_servers.mdmcp] 段。"""
    CODEX_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    text = CODEX_CONFIG.read_text(encoding="utf-8") if CODEX_CONFIG.exists() else ""

    # 删除任何已有的 [mcp_servers.mdmcp...] 段（含子表）
    out_lines: list[str] = []
    skip = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            skip = s.startswith("[mcp_servers.mdmcp]") \
                   or s.startswith("[mcp_servers.mdmcp.")
        if not skip:
            out_lines.append(line)

    env_inline = ", ".join(f'{k} = "{v}"' for k, v in env_block.items())
    block = [
        "[mcp_servers.mdmcp]",
        f'command = "{py}"',
        'args = ["-m", "mdmcp.server"]',
        f"env = {{ {env_inline} }}",
    ]
    body = "\n".join(out_lines).rstrip()
    new_text = (body + "\n\n" if body else "") + "\n".join(block) + "\n"
    CODEX_CONFIG.write_text(new_text, encoding="utf-8")
    return True


def step_mcp_config(py: Path, creds: dict[str, str]) -> None:
    info("步骤 4/5：注册到 MCP 客户端")
    env_block = _build_env_block(creds)

    claude_bin = shutil.which("claude")
    codex_bin_or_cfg = shutil.which("codex") or (CODEX_CONFIG.exists() or CODEX_CONFIG.parent.exists())

    # 自动检测仅用于推荐默认值；--client 直接覆盖；否则交互让用户选
    detected = set()
    if claude_bin:
        detected.add("claude")
    if codex_bin_or_cfg:
        detected.add("codex")

    if CLIENT_OVERRIDE is not None:
        targets = CLIENT_OVERRIDE
        info(f"--client 指定客户端：{', '.join(sorted(targets)) or '(空)'}")
    else:
        if detected:
            print(f"\n  自动检测到已安装客户端：{', '.join(sorted(detected))}")
        else:
            print("\n  未检测到 claude / codex（依然可以选，配置写入后下次装上即可生效）")
        # 默认值：检测到两个 → 都装；检测到一个 → 那个；都没检测到 → claude
        if detected == {"claude", "codex"}:
            default_choice = "3"
        elif "codex" in detected and "claude" not in detected:
            default_choice = "2"
        else:
            default_choice = "1"
        print("  • Claude Code：写到 ~/.claude.json（claude mcp add）")
        print("  • Codex CLI：写到 ~/.codex/config.toml")
        client_choice = ask_choice(
            "选择 MCP 客户端",
            [
                ("1", "Claude Code"),
                ("2", "Codex"),
                ("3", "两个都装"),
            ],
            default=default_choice,
        )
        targets = {"claude", "codex"} if client_choice == "3" \
                  else {"claude"} if client_choice == "1" \
                  else {"codex"}

    # 注册范围：用户级（全局）/ 项目级（当前仓库）/ 都配
    if WRITE_PROJECT_MCP:
        scope = "3"
    else:
        print()
        print("  • 用户级：在任何目录打开客户端都能用 mdmcp（推荐）")
        print("  • 项目级：只在当前目录打开 Claude Code 才能用（写 .mcp.json，便于跟仓库分发；Codex 不支持项目级）")
        print("  • 两个都配：全局可用 + 配置随当前仓库分发")
        scope = ask_choice(
            "选择注册范围",
            [
                ("1", "用户级 —— 全局可用（推荐）"),
                ("2", "项目级 —— 只在当前目录（写 .mcp.json）"),
                ("3", "两个都配"),
            ],
            default="1",
        )

    registered: list[str] = []
    do_user = scope in ("1", "3")
    do_project = scope in ("2", "3")

    if do_user:
        if "claude" in targets and claude_bin and _register_claude_user(claude_bin, py, env_block):
            registered.append("Claude Code（用户级）")
        if "codex" in targets and _register_codex(py, env_block):
            registered.append(f"Codex（{CODEX_CONFIG}）")
    if do_project:
        _write_project_mcp_json(py, env_block)
        registered.append(f"项目级 {MCP_JSON.name}")

    if registered:
        ok("已注册到：" + " + ".join(registered))
    else:
        warn("没有成功注册的客户端，下面是手动命令：")
        print_manual_hints(py, env_block)


def print_manual_hints(py: Path, env_block: dict[str, str]) -> None:
    env_args = " ".join(f"-e {k}={v}" for k, v in env_block.items())
    print("\n—— Claude Code（用户级）——")
    print(f"claude mcp add mdmcp --scope user {env_args} -- {py} -m mdmcp.server")

    env_inline = ", ".join(f'{k} = "{v}"' for k, v in env_block.items())
    print("\n—— Codex CLI（写到 ~/.codex/config.toml）——")
    print("[mcp_servers.mdmcp]")
    print(f'command = "{py}"')
    print('args = ["-m", "mdmcp.server"]')
    print(f"env = {{ {env_inline} }}")
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
    creds = step_ping(py, creds)
    step_mcp_config(py, creds)
    step_done()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)
