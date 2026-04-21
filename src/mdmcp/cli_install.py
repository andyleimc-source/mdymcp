"""CLI 入口：`mdmcp-install` — 交互式安装/配置。

两种调用方式：
  1) PyPI 场景：用户 `pipx install mdmcp` 后直接 `mdmcp-install`，
     配置写到 `~/.mdmcp/`。
  2) Clone 场景：`install.py` 在本仓库里创建 .venv 后调用
     `.venv/bin/mdmcp-install --from-clone <repo-root>`，配置写到仓库根。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
ANTIGRAVITY_CONFIG = Path.home() / ".gemini" / "antigravity" / "mcp_config.json"
ALL_CLIENTS = {"claude", "codex", "antigravity"}
DEBUG = os.getenv("MDMCP_INSTALL_DEBUG", "").strip() in ("1", "true", "yes") \
        or "--debug" in sys.argv


def _parse_client_flag() -> set[str] | None:
    for a in sys.argv[1:]:
        if a.startswith("--client="):
            v = a.split("=", 1)[1].lower().strip()
            if v in ("both", "all"):
                return set(ALL_CLIENTS)
            return {x for x in v.split(",") if x in ALL_CLIENTS}
    return None


def _parse_from_clone() -> Path | None:
    for i, a in enumerate(sys.argv[1:]):
        if a == "--from-clone" and i + 1 < len(sys.argv) - 1:
            return Path(sys.argv[i + 2]).resolve()
        if a.startswith("--from-clone="):
            return Path(a.split("=", 1)[1]).resolve()
    return None


def info(msg: str) -> None:
    print(f"\033[36m[mdmcp]\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"\033[32m✅\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"\033[33m⚠️ \033[0m {msg}")


def err(msg: str) -> None:
    print(f"\033[31m❌\033[0m {msg}", file=sys.stderr)


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


def read_env(env_file: Path) -> dict[str, str]:
    if not env_file.exists():
        return {}
    out: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def write_env(env_file: Path, updates: dict[str, str]) -> None:
    existing = read_env(env_file)
    existing.update(updates)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in existing.items()]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def step_credentials(py: Path, root: Path) -> dict[str, str]:
    info("步骤 1/4：获取明道凭据（MD_ACCOUNT_ID / MD_KEY）")
    env_file = root / ".env"
    existing = read_env(env_file)
    if existing.get("MD_ACCOUNT_ID") and existing.get("MD_KEY"):
        ok(f".env 已存在凭据：MD_ACCOUNT_ID={existing['MD_ACCOUNT_ID']}")
        if not ask_yes("要重新获取吗？", default=False):
            return {k: existing[k] for k in ("MD_ACCOUNT_ID", "MD_KEY",
                                              "MD_HAP_REFRESH_TOKEN", "MD_HAP_TOKEN",
                                              "MD_HAP_KEY")
                    if k in existing}

    info("即将打开浏览器隐身窗口，请登录要授权的明道账号。")
    info(f"授权完成后会写入 {env_file}")
    # 直接调用模块，避免 shutil.which 在 PATH 缺失时找不到
    code = (
        "from pathlib import Path; from mdmcp.cli_auth import main;"
        f"import os; os.chdir({str(root)!r});"
        "main()"
    )
    try:
        run([str(py), "-c", code])
    except subprocess.CalledProcessError as e:
        err(f"OAuth 失败：{e}")
        sys.exit(1)

    creds = read_env(env_file)
    if not creds.get("MD_ACCOUNT_ID") or not creds.get("MD_KEY"):
        err("OAuth 完成但未在 .env 找到凭据")
        sys.exit(1)
    out = {"MD_ACCOUNT_ID": creds["MD_ACCOUNT_ID"], "MD_KEY": creds["MD_KEY"]}

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
            if creds.get("MD_HAP_KEY"):
                out["MD_HAP_KEY"] = creds["MD_HAP_KEY"]
            return out
    rt = input("MD_HAP_REFRESH_TOKEN: ").strip()
    tk = input("MD_HAP_TOKEN: ").strip() if rt else ""
    if rt and tk:
        write_env(env_file, {"MD_HAP_REFRESH_TOKEN": rt, "MD_HAP_TOKEN": tk})
        out["MD_HAP_REFRESH_TOKEN"] = rt
        out["MD_HAP_TOKEN"] = tk
        ok("已写入 .env")
    else:
        warn("HAP 凭据不完整，跳过 HAP 网关；v1 工具不受影响")
    return out


def _stepwise_call(py: Path, env: dict, code: str) -> tuple[bool, str]:
    try:
        r = subprocess.run([str(py), "-c", code], env=env, capture_output=True,
                           text=True, check=True)
        return True, r.stdout.strip() or r.stderr.strip()
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + (e.stderr or "")


def step_ping(py: Path, root: Path, creds: dict[str, str]) -> dict[str, str]:
    info("步骤 2/4：验证凭据可用")
    env = {**os.environ, **creds}
    env_file = root / ".env"
    out = dict(creds)

    success, output = _stepwise_call(py, env,
        "from mdmcp.auth import ensure_access_token; print(len(ensure_access_token()))")
    if not success:
        err(f"v1 token 换取失败：{output.strip()}"); sys.exit(1)
    ok("v1 凭据有效")

    if not creds.get("MD_HAP_REFRESH_TOKEN") or not creds.get("MD_HAP_TOKEN"):
        warn("未填 HAP 凭据，跳过 HAP 网关；仅启用 50 个 v1 工具")
        return out

    if creds.get("MD_HAP_KEY"):
        info(f"复用已有 hap_key (…{creds['MD_HAP_KEY'][-6:]})")
    else:
        reg_code = (
            "from mdmcp.auth import hap_register;"
            "import os;"
            "print(hap_register(os.environ['MD_ACCOUNT_ID'], os.environ['MD_HAP_REFRESH_TOKEN'], os.environ['MD_HAP_TOKEN']))"
        )
        success, output = _stepwise_call(py, env, reg_code)
        hap_key = output.strip().splitlines()[-1] if success and output.strip() else ""
        if not hap_key:
            warn(f"HAP register 失败，HAP 工具将跳过；v1 不受影响 ({output.strip()[-120:]})")
            return out
        write_env(env_file, {"MD_HAP_KEY": hap_key})
        out["MD_HAP_KEY"] = hap_key
        env["MD_HAP_KEY"] = hap_key
        ok("HAP 已注册（hap_key 写入 .env）")

    success, output = _stepwise_call(py, env,
        "from mdmcp.auth import ensure_hap_token; print(len(ensure_hap_token()))")
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


def _write_project_mcp_json(root: Path, py: Path, env_block: dict[str, str]) -> None:
    mcp_json = root / ".mcp.json"
    server_entry = {"type": "stdio", "command": str(py),
                    "args": ["-m", "mdmcp.server"], "env": env_block}
    existing: dict = {}
    if mcp_json.exists():
        try:
            existing = json.loads(mcp_json.read_text(encoding="utf-8"))
        except Exception:
            warn(f"{mcp_json} 无法解析，将覆盖")
    existing.setdefault("mcpServers", {})["mdmcp"] = server_entry
    mcp_json.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def _register_codex(py: Path, env_block: dict[str, str]) -> bool:
    CODEX_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    text = CODEX_CONFIG.read_text(encoding="utf-8") if CODEX_CONFIG.exists() else ""

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


def _register_antigravity(py: Path, env_block: dict[str, str]) -> bool:
    """写 ~/.gemini/antigravity/mcp_config.json，合并已有 mcpServers。"""
    ANTIGRAVITY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    server_entry = {
        "command": str(py),
        "args": ["-m", "mdmcp.server"],
        "env": env_block,
    }
    existing: dict = {}
    if ANTIGRAVITY_CONFIG.exists():
        try:
            existing = json.loads(ANTIGRAVITY_CONFIG.read_text(encoding="utf-8"))
        except Exception:
            warn(f"{ANTIGRAVITY_CONFIG} 无法解析，将覆盖")
    existing.setdefault("mcpServers", {})["mdmcp"] = server_entry
    ANTIGRAVITY_CONFIG.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def step_mcp_config(py: Path, root: Path, creds: dict[str, str],
                    client_override: set[str] | None, write_project: bool) -> None:
    info("步骤 3/4：注册到 MCP 客户端")
    env_block = _build_env_block(creds)

    claude_bin = shutil.which("claude")
    codex_bin_or_cfg = shutil.which("codex") or (CODEX_CONFIG.exists() or CODEX_CONFIG.parent.exists())
    antigravity_detected = ANTIGRAVITY_CONFIG.parent.exists()

    detected: set[str] = set()
    if claude_bin:
        detected.add("claude")
    if codex_bin_or_cfg:
        detected.add("codex")
    if antigravity_detected:
        detected.add("antigravity")

    if client_override is not None:
        targets = client_override
        info(f"--client 指定客户端：{', '.join(sorted(targets)) or '(空)'}")
    else:
        if detected:
            print(f"\n  自动检测到已安装客户端：{', '.join(sorted(detected))}")
        else:
            print("\n  未检测到 claude / codex / antigravity（依然可以选，装上后配置即可生效）")
        # 默认值：检测到 ≥2 个 → 全部检测到的（4）；只检测到 1 个 → 那一个；都没 → Claude
        if len(detected) >= 2:
            default_choice = "4"
        elif detected == {"codex"}:
            default_choice = "2"
        elif detected == {"antigravity"}:
            default_choice = "3"
        else:
            default_choice = "1"
        print("  • Claude Code：写到 ~/.claude.json（claude mcp add）")
        print("  • Codex CLI：写到 ~/.codex/config.toml")
        print("  • Antigravity：写到 ~/.gemini/antigravity/mcp_config.json")
        client_choice = ask_choice(
            "选择 MCP 客户端",
            [("1", "Claude Code"),
             ("2", "Codex"),
             ("3", "Antigravity"),
             ("4", "全部检测到的（或全部三个）")],
            default=default_choice,
        )
        if client_choice == "1":
            targets = {"claude"}
        elif client_choice == "2":
            targets = {"codex"}
        elif client_choice == "3":
            targets = {"antigravity"}
        else:
            targets = detected if detected else set(ALL_CLIENTS)

    if write_project:
        scope = "3"
    else:
        print()
        print("  • 用户级：在任何目录打开客户端都能用 mdmcp（推荐）")
        print("  • 项目级：只在当前目录打开 Claude Code 才能用（写 .mcp.json，便于跟仓库分发；Codex / Antigravity 不支持项目级）")
        print("  • 两个都配：全局可用 + 配置随当前仓库分发")
        scope = ask_choice(
            "选择注册范围",
            [("1", "用户级 —— 全局可用（推荐）"),
             ("2", "项目级 —— 只在当前目录（写 .mcp.json）"),
             ("3", "两个都配")],
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
        if "antigravity" in targets and _register_antigravity(py, env_block):
            registered.append(f"Antigravity（{ANTIGRAVITY_CONFIG}）")
    if do_project:
        _write_project_mcp_json(Path.cwd(), py, env_block)
        registered.append(f"项目级 .mcp.json（{Path.cwd()}）")

    if registered:
        ok("已注册到：" + " + ".join(registered))
        if "antigravity" in targets:
            info("Antigravity 需要在 IDE 里打开「Manage MCP Servers → Refresh」才能看到 mdmcp")
    else:
        warn("没有成功注册的客户端，下面是手动命令：")
        env_args = " ".join(f"-e {k}={v}" for k, v in env_block.items())
        print(f"\nclaude mcp add mdmcp --scope user {env_args} -- {py} -m mdmcp.server")


def step_done() -> None:
    info("步骤 4/4：完成")
    ok("mdmcp 安装完毕。重启 Claude Code 即可使用。")
    print("\n试试在 Claude Code 里说：")
    print("  · 「帮我看看最近的公司动态」")
    print("  · 「创建一个明天上午 10 点的日程」")
    print("  · 「列出公司所有部门」")


def main() -> None:
    print("=" * 56)
    print("  mdmcp 交互式安装")
    print("=" * 56)

    from_clone = _parse_from_clone()
    client_override = _parse_client_flag()
    write_project = "--project" in sys.argv

    if from_clone is not None:
        root = from_clone
        info(f"Clone 模式：配置写入仓库根 {root}")
    else:
        root = Path.home() / ".mdmcp"
        root.mkdir(parents=True, exist_ok=True)
        info(f"PyPI 模式：配置写入 {root}")

    py = Path(sys.executable)

    try:
        creds = step_credentials(py, root)
        creds = step_ping(py, root, creds)
        step_mcp_config(py, root, creds, client_override, write_project)
        step_done()
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)


if __name__ == "__main__":
    main()
