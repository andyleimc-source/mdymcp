"""CLI 入口：`mdymcp-install` — 交互式安装/配置。

两种调用方式：
  1) PyPI 场景：用户 `uv tool install mdymcp` 后直接 `mdymcp-install`（或
     `uvx --from mdymcp mdymcp-install` 一次性），配置写到 `~/.mdymcp/`。
  2) Clone 场景：`install.py` 在本仓库里用 uv 建环境后调用
     `mdymcp-install --from-clone <repo-root>`，配置写到仓库根。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

CODEX_CONFIG = Path.home() / ".codex" / "config.toml"
ANTIGRAVITY_CONFIG = Path.home() / ".gemini" / "antigravity" / "mcp_config.json"
CURSOR_USER_CONFIG = Path.home() / ".cursor" / "mcp.json"
WINDSURF_USER_CONFIG = Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
ALL_CLIENTS = {"claude", "codex", "antigravity", "cursor", "windsurf", "trae", "vscode"}


def _trae_user_config() -> Path | None:
    """Trae 是 VS Code fork，mcp.json 走 VS Code 的 User 目录约定。
    同时兼容国际版 (Trae) 和国内版 (Trae CN)：优先返回已存在父目录的那个。
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path.home() / ".config"
    candidates = [base / name / "User" / "mcp.json" for name in ("Trae", "Trae CN")]
    # 已存在（或父目录已存在）的优先
    for c in candidates:
        if c.exists() or c.parent.exists() or c.parent.parent.exists():
            return c
    return candidates[0]  # fallback：默认国际版路径


def _vscode_project_config(root: Path) -> Path:
    """VS Code（含 Copilot Chat）项目级 MCP 配置 —— 推荐项目级，能跟仓库走。"""
    return root / ".vscode" / "mcp.json"
DEBUG = os.getenv("MDYMCP_INSTALL_DEBUG", "").strip() in ("1", "true", "yes") \
        or "--debug" in sys.argv

# HAP 个人授权页 —— 拿 refresh_token / access_token 的地方
HAP_INTEGRATION_URL = "https://www.mingdao.com/integrationConnect/69bcae07257900ec41aa2733"


def _resolve_uvx() -> str | None:
    """找到 uvx 可执行文件的绝对路径。找不到返回 None。"""
    found = shutil.which("uvx")
    if found:
        return found
    candidates: list[Path] = [
        Path.home() / ".local" / "bin" / "uvx",
        Path.home() / ".cargo" / "bin" / "uvx",
    ]
    if sys.platform.startswith("win"):
        candidates += [
            Path.home() / ".local" / "bin" / "uvx.exe",
            Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".local" / "bin" / "uvx.exe",
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _build_server_command(py: Path) -> tuple[str, list[str]]:
    """MCP 客户端里配置的启动命令。

    优先 uvx（跨平台、自带 Python 版本管理、不依赖 IDE 继承的 PATH）；
    回落到当前解释器 + -m（兼容 pipx / clone 场景）。
    """
    uvx = _resolve_uvx()
    if uvx:
        return uvx, ["mdymcp"]
    return str(py), ["-m", "mdymcp.server"]


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
    print(f"\033[36m[mdymcp]\033[0m {msg}")


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
        "from pathlib import Path; from mdymcp.cli_auth import main;"
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

    print(f"  • 即将打开 HAP 个人授权页：{HAP_INTEGRATION_URL}")
    print("  • 授权后在页面拿到 refresh_token 和 access_token，粘回下面")
    print("  • 任一留空 = 跳过 HAP，仅启用 v1 协作 API 的 50 个工具")
    try:
        webbrowser.open(HAP_INTEGRATION_URL)
    except Exception:
        warn("浏览器没自动打开，请手动复制上面的 URL")

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
        "from mdymcp.auth import ensure_access_token; print(len(ensure_access_token()))")
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
            "from mdymcp.auth import hap_register;"
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
        "from mdymcp.auth import ensure_hap_token; print(len(ensure_hap_token()))")
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
    # 清理 0.1.x 老注册 + 当前名字（避免重复注册）
    for legacy_name in ("mdmcp", "mdymcp"):
        run([claude_bin, "mcp", "remove", legacy_name, "--scope", "user"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = [claude_bin, "mcp", "add", "mdymcp", "--scope", "user"]
    for k, v in env_block.items():
        cmd += ["-e", f"{k}={v}"]
    server_cmd, server_args = _build_server_command(py)
    cmd += ["--", server_cmd, *server_args]
    try:
        run(cmd, stdout=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError as e:
        err(f"claude mcp add 失败：{e}")
        return False


def _write_project_mcp_json(root: Path, py: Path, env_block: dict[str, str]) -> None:
    mcp_json = root / ".mcp.json"
    server_cmd, server_args = _build_server_command(py)
    server_entry = {"type": "stdio", "command": server_cmd,
                    "args": server_args, "env": env_block}
    existing: dict = {}
    if mcp_json.exists():
        try:
            existing = json.loads(mcp_json.read_text(encoding="utf-8"))
        except Exception:
            warn(f"{mcp_json} 无法解析，将覆盖")
    servers = existing.setdefault("mcpServers", {})
    servers.pop("mdmcp", None)  # 清理老名
    servers["mdymcp"] = server_entry
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
            # 同时清理老名 [mcp_servers.mdmcp] 和新名 [mcp_servers.mdymcp]
            skip = (s.startswith("[mcp_servers.mdmcp]")
                    or s.startswith("[mcp_servers.mdmcp.")
                    or s.startswith("[mcp_servers.mdymcp]")
                    or s.startswith("[mcp_servers.mdymcp."))
        if not skip:
            out_lines.append(line)

    server_cmd, server_args = _build_server_command(py)
    # 用 json.dumps 生成 TOML basic string —— JSON 的转义规则是 TOML basic 的子集，保证 Windows 带反斜杠的路径也安全
    args_inline = "[" + ", ".join(json.dumps(a) for a in server_args) + "]"
    env_inline = ", ".join(f"{k} = {json.dumps(v)}" for k, v in env_block.items())
    block = [
        "[mcp_servers.mdymcp]",
        f"command = {json.dumps(server_cmd)}",
        f"args = {args_inline}",
        f"env = {{ {env_inline} }}",
    ]
    body = "\n".join(out_lines).rstrip()
    new_text = (body + "\n\n" if body else "") + "\n".join(block) + "\n"
    CODEX_CONFIG.write_text(new_text, encoding="utf-8")
    return True


def _write_mcp_servers_json(config_path: Path, py: Path, env_block: dict[str, str],
                             *, key: str = "mcpServers", include_type: bool = False) -> bool:
    """通用写入器：Antigravity / Cursor / Windsurf / Trae / VS Code 都是相似的 JSON 结构，
    仅顶层 key（mcpServers vs servers）和是否带 `type: stdio` 有差。合并已有配置、清理老名。
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    server_cmd, server_args = _build_server_command(py)
    server_entry: dict = {"command": server_cmd, "args": server_args, "env": env_block}
    if include_type:
        server_entry = {"type": "stdio", **server_entry}
    existing: dict = {}
    if config_path.exists():
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            warn(f"{config_path} 无法解析，将覆盖")
    servers = existing.setdefault(key, {})
    servers.pop("mdmcp", None)  # 清理老名
    servers["mdymcp"] = server_entry
    config_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


def _register_antigravity(py: Path, env_block: dict[str, str]) -> bool:
    return _write_mcp_servers_json(ANTIGRAVITY_CONFIG, py, env_block)


def _register_cursor(py: Path, env_block: dict[str, str]) -> bool:
    return _write_mcp_servers_json(CURSOR_USER_CONFIG, py, env_block)


def _register_windsurf(py: Path, env_block: dict[str, str]) -> bool:
    return _write_mcp_servers_json(WINDSURF_USER_CONFIG, py, env_block)


def _register_trae(py: Path, env_block: dict[str, str]) -> bool:
    path = _trae_user_config()
    if path is None:
        return False
    return _write_mcp_servers_json(path, py, env_block)


def _register_vscode(py: Path, env_block: dict[str, str], project_root: Path) -> bool:
    """VS Code（Copilot Chat）用项目级 `.vscode/mcp.json`，顶层 key 是 `servers`、需要 type。"""
    return _write_mcp_servers_json(
        _vscode_project_config(project_root), py, env_block,
        key="servers", include_type=True,
    )


def _detect_clients() -> dict[str, bool]:
    """返回每个 client 是否检测到。顺序即输出顺序。"""
    trae_path = _trae_user_config()
    return {
        "claude":      shutil.which("claude") is not None,
        "codex":       shutil.which("codex") is not None
                       or CODEX_CONFIG.exists() or CODEX_CONFIG.parent.exists(),
        "cursor":      CURSOR_USER_CONFIG.parent.exists() or CURSOR_USER_CONFIG.exists(),
        "windsurf":    WINDSURF_USER_CONFIG.parent.exists() or WINDSURF_USER_CONFIG.exists(),
        "antigravity": ANTIGRAVITY_CONFIG.parent.exists(),
        "trae":        bool(trae_path and (trae_path.parent.exists()
                                           or trae_path.parent.parent.exists())),
        "vscode":      shutil.which("code") is not None
                       or shutil.which("code-insiders") is not None
                       or (Path.home() / "Library" / "Application Support" / "Code").exists()
                       or (Path.home() / ".config" / "Code").exists()
                       or (Path(os.environ.get("APPDATA", "")) / "Code").exists(),
    }


CLIENT_LABELS = {
    "claude":      "Claude Code",
    "codex":       "Codex CLI",
    "cursor":      "Cursor",
    "windsurf":    "Windsurf",
    "antigravity": "Gemini Antigravity",
    "trae":        "Trae",
    "vscode":      "VS Code (Copilot Chat)",
}


def step_mcp_config(py: Path, root: Path, creds: dict[str, str],
                    client_override: set[str] | None, write_project: bool) -> None:
    info("步骤 3/4：注册到 MCP 客户端")
    env_block = _build_env_block(creds)

    detection = _detect_clients()
    detected = {c for c, hit in detection.items() if hit}
    not_detected = {c for c, hit in detection.items() if not hit}

    # 决定目标客户端
    if client_override is not None:
        targets = client_override
        info(f"--client 指定客户端：{', '.join(sorted(targets)) or '(空)'}")
    else:
        print()
        if detected:
            hit_labels = ', '.join(CLIENT_LABELS[c] for c in sorted(detected))
            print(f"  检测到：{hit_labels}")
        if not_detected:
            miss_labels = ', '.join(CLIENT_LABELS[c] for c in sorted(not_detected))
            print(f"  未检测到：{miss_labels}")
        if not detected:
            print("\n  一个都没识别出来。你可以继续手动选择（装上 IDE 后这份配置即生效）。")
            targets = set()
        elif ask_yes(f"\n注册到上面检测到的 {len(detected)} 个客户端？", default=True):
            targets = set(detected)
        else:
            # 手选：列出全部 7 个，逗号分隔索引
            print("\n  手动选择（逗号分隔序号，回车跳过）：")
            numbered = list(CLIENT_LABELS.items())
            for i, (k, label) in enumerate(numbered, 1):
                marker = "✓" if detection[k] else " "
                print(f"    [{i}] {marker} {label}")
            ans = input("  选择: ").strip()
            picks: set[str] = set()
            for token in ans.replace("，", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    idx = int(token)
                    if 1 <= idx <= len(numbered):
                        picks.add(numbered[idx - 1][0])
                except ValueError:
                    pass
            targets = picks

    # 项目级：Claude .mcp.json + VS Code 的 .vscode/mcp.json 都属于项目级
    do_project = write_project
    if not do_project and not client_override and targets:
        do_project = ask_yes(
            f"\n同时在当前目录写项目级配置？"
            f"（.mcp.json for Claude Code / .vscode/mcp.json for VS Code；便于随仓库分发）",
            default=False,
        )

    registered: list[str] = []
    cwd = Path.cwd()

    # 用户级
    if "claude" in targets and detection["claude"]:
        claude_bin = shutil.which("claude")
        if claude_bin and _register_claude_user(claude_bin, py, env_block):
            registered.append(f"{CLIENT_LABELS['claude']}（用户级）")
    if "codex" in targets and _register_codex(py, env_block):
        registered.append(f"{CLIENT_LABELS['codex']}（{CODEX_CONFIG}）")
    if "cursor" in targets and _register_cursor(py, env_block):
        registered.append(f"{CLIENT_LABELS['cursor']}（{CURSOR_USER_CONFIG}）")
    if "windsurf" in targets and _register_windsurf(py, env_block):
        registered.append(f"{CLIENT_LABELS['windsurf']}（{WINDSURF_USER_CONFIG}）")
    if "antigravity" in targets and _register_antigravity(py, env_block):
        registered.append(f"{CLIENT_LABELS['antigravity']}（{ANTIGRAVITY_CONFIG}）")
    if "trae" in targets:
        trae_path = _trae_user_config()
        if trae_path and _register_trae(py, env_block):
            registered.append(f"{CLIENT_LABELS['trae']}（{trae_path}）")

    # 项目级
    if do_project:
        _write_project_mcp_json(cwd, py, env_block)
        registered.append(f"Claude Code 项目级 .mcp.json（{cwd}）")
    if "vscode" in targets:
        # VS Code 只有项目级（我们不碰它的全局 profile）
        if _register_vscode(py, env_block, cwd):
            registered.append(f"{CLIENT_LABELS['vscode']}（{_vscode_project_config(cwd)}）")

    if registered:
        ok("已注册到：\n  • " + "\n  • ".join(registered))
        if "antigravity" in targets:
            info("Antigravity 需要在 IDE 里打开「Manage MCP Servers → Refresh」才能看到 mdymcp")
        if "cursor" in targets or "windsurf" in targets or "trae" in targets or "vscode" in targets:
            info("Cursor / Windsurf / Trae / VS Code 需要重启或在 MCP 设置里刷新")
    else:
        warn("没有成功注册的客户端。手动命令（以 Claude Code 为例）：")
        env_args = " ".join(f"-e {k}={v}" for k, v in env_block.items())
        server_cmd, server_args = _build_server_command(py)
        print(f"\nclaude mcp add mdymcp --scope user {env_args} -- {server_cmd} {' '.join(server_args)}")


def step_done() -> None:
    info("步骤 4/4：完成")
    ok("mdymcp 安装完毕。重启客户端即可使用。")
    print("\n试试在 Claude Code 里说：")
    print("  · 「帮我看看最近的公司动态」")
    print("  · 「创建一个明天上午 10 点的日程」")
    print("  · 「列出公司所有部门」")


def main() -> None:
    print("=" * 56)
    print("  mdymcp 交互式安装")
    print("=" * 56)

    from_clone = _parse_from_clone()
    client_override = _parse_client_flag()
    write_project = "--project" in sys.argv

    if from_clone is not None:
        root = from_clone
        info(f"Clone 模式：配置写入仓库根 {root}")
    else:
        root = Path.home() / ".mdymcp"
        legacy_root = Path.home() / ".mdmcp"
        if legacy_root.exists() and not root.exists():
            info(f"检测到旧配置 {legacy_root}，迁移到 {root}")
            legacy_root.rename(root)
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
