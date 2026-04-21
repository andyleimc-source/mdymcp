"""Token fetcher — 远端 hook 提供 24h token，内存缓存到次日本地 00:00。"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

BASE_API_URL = "https://api.mingdao.com"
HOOK_URL_DEFAULT = "https://api.mingdao.com/workflow/hooks2/NjlkYzQ5NGIwMzM0NzkwYjg4MWY4NTk5"
APPNAME_DEFAULT = "mdcloud"  # 服务端映射表按 appname 路由，沿用既有映射避免重新授权

# OAuth 自助注册（mdmcp-auth 命令使用）
APP_KEY_DEFAULT = "6A228C49DAC4"
CALLBACK_PORT_DEFAULT = 8080
REGISTER_URL_DEFAULT = "https://api.mingdao.com/workflow/hooks/NjllNjFkYjM2NTAyMDc5NzgxMGNmZDll"

# HAP 网关凭据（独立于 v1 token）：refresh_token → register → hap_key → token
HAP_REGISTER_HOOK_DEFAULT = "https://api.mingdao.com/workflow/hooks2/NjllNjNkYzNiODBlZTc3YjE3NDM1Y2U2"
HAP_TOKEN_HOOK_DEFAULT = "https://api.mingdao.com/workflow/hooks2/NjllNjQ2NGE2NTAyMDc5NzgxMTFjM2Q3"

_cache: dict[str, Any] = {"token": "", "expires_at": 0}
_hap_cache: dict[str, Any] = {"hap_key": "", "token": "", "expires_at": 0}


def _load_env() -> None:
    """Lazy load .env from cwd or package parent."""
    for d in [Path.cwd(), Path(__file__).resolve().parent.parent.parent]:
        env = d / ".env"
        if not env.exists():
            continue
        for raw_line in env.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
        return


def _next_local_midnight_ts() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(tomorrow.timestamp())


def ensure_access_token() -> str:
    if _cache["token"] and time.time() < _cache["expires_at"] - 60:
        return str(_cache["token"])

    _load_env()
    account_id = os.getenv("MD_ACCOUNT_ID", "").strip()
    key = os.getenv("MD_KEY", "").strip()
    appname = os.getenv("MD_APPNAME", APPNAME_DEFAULT).strip()
    hook_url = os.getenv("MD_HOOK_URL", HOOK_URL_DEFAULT).strip()
    if not account_id or not key:
        raise RuntimeError(
            "Missing MD_ACCOUNT_ID or MD_KEY. Set them in .env or environment."
        )

    body = json.dumps(
        {"account_id": account_id, "key": key, "appname": appname}
    ).encode("utf-8")
    req = urllib.request.Request(
        hook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "mdmcp/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    token = data.get("token")
    if not token:
        raise RuntimeError(f"Token endpoint returned no token: {data!r}")

    _cache["token"] = token
    _cache["expires_at"] = _next_local_midnight_ts()
    return str(token)


def _hap_post(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "mdmcp/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_hap_token() -> str:
    """HAP 网关 token：refresh_token → register(hap_key) → token，缓存到次日本地 00:00。"""
    if _hap_cache["token"] and time.time() < _hap_cache["expires_at"] - 60:
        return str(_hap_cache["token"])

    _load_env()
    account_id = os.getenv("MD_ACCOUNT_ID", "").strip()
    refresh_token = os.getenv("MD_HAP_REFRESH_TOKEN", "").strip()
    register_url = os.getenv("MD_HAP_REGISTER_HOOK", HAP_REGISTER_HOOK_DEFAULT).strip()
    token_url = os.getenv("MD_HAP_TOKEN_HOOK", HAP_TOKEN_HOOK_DEFAULT).strip()
    if not account_id or not refresh_token:
        raise RuntimeError(
            "Missing MD_ACCOUNT_ID or MD_HAP_REFRESH_TOKEN. "
            "在 .env 配置 HAP 个人授权拿到的 refresh_token。"
        )

    reg = _hap_post(register_url, {"account_id": account_id, "hap_refresh_token": refresh_token})
    hap_key = reg.get("hap_key") or ""
    if not hap_key:
        raise RuntimeError(f"HAP register 未返回 hap_key：{reg!r}")

    tok = _hap_post(token_url, {"account_id": account_id, "hap_key": hap_key})
    token = tok.get("token") or ""
    if not token:
        raise RuntimeError(
            f"HAP token 接口返回空，可能 refresh_token 失效。响应：{tok!r}"
        )

    _hap_cache["hap_key"] = hap_key
    _hap_cache["token"] = token
    _hap_cache["expires_at"] = _next_local_midnight_ts()
    return token


# ─────────────────────────────────────────────
# OAuth 自助注册流程（mdmcp-auth 命令）
# ─────────────────────────────────────────────

import secrets
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


_CALLBACK_HTML_OK = """<!doctype html>
<html><head><meta charset="utf-8"><title>mdmcp 授权成功</title></head>
<body style="font-family:system-ui;max-width:560px;margin:80px auto;padding:0 24px;color:#222">
<h2>✅ 授权成功</h2>
<p>已收到授权码，正在和服务端交换凭据。请回到终端查看结果，本页面可以关闭。</p>
</body></html>"""

_CALLBACK_HTML_ERR = """<!doctype html>
<html><head><meta charset="utf-8"><title>mdmcp 授权失败</title></head>
<body style="font-family:system-ui;max-width:560px;margin:80px auto;padding:0 24px;color:#222">
<h2>❌ 授权失败</h2>
<p>{msg}</p><p>请回到终端查看详细错误。</p>
</body></html>"""


def _open_incognito(url: str) -> str:
    """用系统默认浏览器打开 URL（复用已登录会话）。"""
    try:
        webbrowser.open(url)
    except Exception:
        _copy_to_clipboard(url)
        return "clipboard (manual open required)"
    _copy_to_clipboard(url)
    return "default browser"


def _copy_to_clipboard(text: str) -> bool:
    plat = sys.platform
    candidates: list[list[str]] = []
    if plat == "darwin":
        candidates = [["pbcopy"]]
    elif plat.startswith("win"):
        candidates = [["clip"]]
    else:
        if shutil.which("xclip"):
            candidates = [["xclip", "-selection", "clipboard"]]
        elif shutil.which("wl-copy"):
            candidates = [["wl-copy"]]
    for cmd in candidates:
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            p.communicate(text.encode("utf-8"), timeout=3)
            return True
        except Exception:
            continue
    return False


def _write_env_vars(env_path: Path, updates: dict[str, str]) -> None:
    """追加或覆盖 .env 中的指定键，不动其它行。"""
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    keys = set(updates.keys())
    new_lines: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in keys:
                new_lines.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        new_lines.append(raw)
    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")
    env_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict[str, Any] = {}

    def log_message(self, *_a: Any, **_kw: Any) -> None:  # 静音
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        code = (qs.get("code") or [""])[0]
        state = (qs.get("state") or [""])[0]
        error = (qs.get("error") or [""])[0]
        if error or not code:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = error or "missing code"
            self.wfile.write(_CALLBACK_HTML_ERR.format(msg=msg).encode("utf-8"))
            _CallbackHandler.result = {"error": msg}
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_CALLBACK_HTML_OK.encode("utf-8"))
        _CallbackHandler.result = {"code": code, "state": state}


def run_auth_flow(project_root: Path | None = None) -> dict[str, str]:
    """一键 OAuth：起本地 server → 开隐身浏览器 → 接 code → 换 key → 写 .env。

    返回 {"account_id": ..., "key": ...}。
    """
    _load_env()
    app_key = os.getenv("MD_APP_KEY", APP_KEY_DEFAULT).strip()
    port = int(os.getenv("MD_CALLBACK_PORT", str(CALLBACK_PORT_DEFAULT)))
    register_url = os.getenv("MD_REGISTER_URL", REGISTER_URL_DEFAULT).strip()
    redirect_uri = f"http://localhost:{port}/callback"

    if not app_key or "REPLACE" in register_url:
        raise RuntimeError(
            "APP_KEY 或 REGISTER_URL 未正确配置。请通过环境变量 "
            "MD_APP_KEY / MD_REGISTER_URL 覆盖，或由维护者在 auth.py 顶部填入。"
        )

    state = secrets.token_urlsafe(16)
    authorize_url = (
        f"{BASE_API_URL}/oauth2/authorize?"
        + urllib.parse.urlencode(
            {"app_key": app_key, "redirect_uri": redirect_uri, "state": state}
        )
    )

    try:
        server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as e:
        raise RuntimeError(
            f"端口 {port} 已被占用。用 MD_CALLBACK_PORT=xxxx mdmcp-auth 换端口"
            f"（明道后台的回调地址需要同步更新）。底层错误：{e}"
        ) from e

    _CallbackHandler.result = {}
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()

    print(f"→ 监听本地回调 {redirect_uri}")
    method = _open_incognito(authorize_url)
    print(f"→ 已用 {method} 打开明道授权页（复用现有浏览器登录态）")
    if "clipboard" in method:
        print("  ⚠️  无法自动打开浏览器，请手动访问（URL 已复制到剪贴板）：")
        print(f"     {authorize_url}")
    print("→ 请在浏览器中登录目标明道账号并同意授权…")

    # 等回调，最长 5 分钟
    import time as _t
    deadline = _t.time() + 300
    while _t.time() < deadline and not _CallbackHandler.result:
        _t.sleep(0.3)
    server.shutdown()
    server.server_close()

    res = _CallbackHandler.result
    if not res:
        raise RuntimeError("等待授权超时（5 分钟），请重新运行 mdmcp-auth。")
    if "error" in res:
        raise RuntimeError(f"授权失败：{res['error']}")
    if res.get("state") != state:
        raise RuntimeError("state 不匹配，疑似 CSRF 攻击，已拒绝。")

    code = res["code"]
    print("→ 已拿到授权码，正在请求服务端换取凭据…")

    body = json.dumps({"code": code, "redirect_uri": redirect_uri}).encode("utf-8")
    req = urllib.request.Request(
        register_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "mdmcp-auth/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    account_id = data.get("account_id") or ""
    key = data.get("key") or ""
    if not account_id or not key:
        raise RuntimeError(f"Register endpoint 返回异常：{data!r}")

    root = project_root or Path.cwd()
    env_path = root / ".env"
    _write_env_vars(env_path, {"MD_ACCOUNT_ID": account_id, "MD_KEY": key})
    print(f"→ 已写入 {env_path}")
    print(f"  MD_ACCOUNT_ID={account_id}")
    print(f"  MD_KEY={'*' * 8}{key[-4:] if len(key) > 4 else ''}")
    return {"account_id": account_id, "key": key}
