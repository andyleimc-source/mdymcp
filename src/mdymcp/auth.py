"""Token 管理 — v1 token 本地签发/持久化/刷新（OAuth2），保留远端 hook 作为未迁移机器的回落。"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _ssl_ctx() -> ssl.SSLContext:
    """返回一个带 certifi CA 的 SSL 上下文。

    macOS 上 python.org 安装的 Python 往往不带根证书，导致 urlopen 直接
    CERTIFICATE_VERIFY_FAILED。优先用 certifi 的 CA bundle；装不上就回落到系统默认。
    """
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


_SSL_CTX = _ssl_ctx()

BASE_API_URL = "https://api.mingdao.com"
HOOK_URL_DEFAULT = "https://api.mingdao.com/workflow/hooks2/NjlkYzQ5NGIwMzM0NzkwYjg4MWY4NTk5"

# OAuth 本地授权（mdymcp-auth 命令使用）。
# app_key/app_secret 有意公开内嵌（公共客户端模式，同 Google/GitHub CLI）：
# 安全边界在用户浏览器登录+授权，secret 公开不会泄露任何用户数据。
# 可用 MD_APP_KEY / MD_APP_SECRET 环境变量换成自己的 OAuth 应用。
APP_KEY_DEFAULT = "6A228C49DAC4"
APP_SECRET_DEFAULT = "29F04C41F3C41EDA8297F3B273AD710"
CALLBACK_PORT_DEFAULT = 8080

# HAP 网关凭据（独立于 v1 token）：用户在 https://www.mingdao.com/personal?type=pat
# 自助生成的个人 PAT（pat_xxx），本身就是 Bearer token，无需任何远端交换。

# 0.2.x 旧 HAP 链路的废弃键（refresh_token → register → hap_key），0.3.0 起只认 MD_HAP_PAT
LEGACY_HAP_KEYS = {"MD_HAP_TOKEN", "MD_HAP_REFRESH_TOKEN", "MD_HAP_KEY"}

_cache: dict[str, Any] = {"token": "", "expires_at": 0}


def invalidate_cached_token() -> None:
    """清掉进程内 v1 token 缓存，下次 ensure_access_token() 强制重取。

    用途：API 返回 10101/10105（token 在有效期内被明道单方面作废）时，
    api_client 清缓存重试一次——server 模式会从服务器拿到 daemon 自愈后的新 token。
    """
    _cache["token"] = ""
    _cache["expires_at"] = 0


MDYMCP_USER_HOME = Path.home() / ".mdymcp"
# 兼容 0.1.x 的老路径；新路径优先，读到老路径时不强制迁移，等 install 再搬家
MDYMCP_USER_HOME_LEGACY = Path.home() / ".mdmcp"


def _load_env() -> None:
    """Lazy load .env，**合并** cwd → ~/.mdymcp → ~/.mdmcp (legacy) → package parent。

    先出现的文件里的键优先（setdefault），后面的文件只补缺失键——这样项目自带的
    .env（如某项目根放了 META_* / PORT 等配置）**不会屏蔽** ~/.mdymcp/.env 里的
    MD_ 凭据（MD_ACCOUNT_ID / MD_HAP_PAT / MD_V1_TOKEN_* 等）。
    （旧实现读到第一个 .env 就 return，导致带自有 .env 的项目里 mdymcp 完全拿不到凭据。）
    """
    seen: set[Any] = set()
    for d in [Path.cwd(), MDYMCP_USER_HOME, MDYMCP_USER_HOME_LEGACY,
              Path(__file__).resolve().parent.parent.parent]:
        env = d / ".env"
        try:
            marker = env.resolve()
        except Exception:
            marker = env
        if marker in seen or not env.exists():
            continue
        seen.add(marker)
        for raw_line in env.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _next_local_midnight_ts() -> int:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(tomorrow.timestamp())


# ─────────────────────────────────────────────
# v1 token：本地签发 / 持久化 / 刷新
# ─────────────────────────────────────────────

V1_TOKEN_FILE = MDYMCP_USER_HOME / "v1_token.json"
TOKEN_SAFETY_MARGIN = 300  # 提前 5 分钟视为过期，避免边界上拿到将死 token


class _TokenFileLock:
    """跨进程文件锁：防止同机多个 MCP 进程同时 refresh 把 refresh_token 轮换两次。
    Windows 上 fcntl 不可用则退化为无锁（mdymcp 主场景是 mac）。"""

    def __init__(self) -> None:
        self._fh = None

    def __enter__(self) -> "_TokenFileLock":
        try:
            import fcntl
            MDYMCP_USER_HOME.mkdir(parents=True, exist_ok=True)
            self._fh = open(V1_TOKEN_FILE.with_suffix(".lock"), "w")
            fcntl.flock(self._fh, fcntl.LOCK_EX)
        except Exception:
            self._fh = None
        return self

    def __exit__(self, *_a: Any) -> None:
        if self._fh is not None:
            try:
                import fcntl
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()


def _read_token_file() -> dict[str, Any] | None:
    try:
        return json.loads(V1_TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_token_file(data: dict[str, Any]) -> None:
    MDYMCP_USER_HOME.mkdir(parents=True, exist_ok=True)
    V1_TOKEN_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(V1_TOKEN_FILE, 0o600)


def _http_json(url: str, *, form_body: dict[str, Any] | None = None) -> dict[str, Any]:
    import urllib.parse as _up
    headers = {"Accept": "application/json", "User-Agent": "mdymcp/0.4"}
    data = None
    if form_body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = _up.urlencode(form_body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _exchange_token(grant_type: str, **params: str) -> dict[str, Any]:
    """调明道 oauth2/access_token 换 token 对。返回标准化的 token 文件结构。

    实测可用格式（与服务端工作流一致）：POST x-www-form-urlencoded；
    兜底参数全拼 query 的 POST。
    """
    _load_env()
    app_key = os.getenv("MD_APP_KEY", APP_KEY_DEFAULT).strip()
    app_secret = os.getenv("MD_APP_SECRET", APP_SECRET_DEFAULT).strip()

    q = {"app_key": app_key, "app_secret": app_secret,
         "grant_type": grant_type, "format": "json", **params}
    endpoint = f"{BASE_API_URL}/oauth2/access_token"

    import urllib.parse as _up
    last_err: Exception | None = None
    data: dict[str, Any] = {}
    for attempt in ("post_form", "post_query"):
        try:
            if attempt == "post_form":
                data = _http_json(endpoint, form_body=q)
            else:
                data = _http_json(f"{endpoint}?{_up.urlencode(q)}", form_body={})
        except Exception as e:
            last_err = e
            continue
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        access_token = str(payload.get("access_token") or "").strip()
        if access_token:
            now = int(time.time())
            try:
                expires_in = int(payload.get("expires_in") or 0)
            except (TypeError, ValueError):
                expires_in = 0
            if expires_in <= 0:
                expires_in = 86400  # 文档：未发布应用 1 天，保守取下限
            return {
                "access_token": access_token,
                "refresh_token": str(payload.get("refresh_token") or "").strip(),
                "expires_at": now + expires_in,
                "obtained_at": now,
            }
    detail = data if data else last_err
    raise RuntimeError(f"[v1] oauth2/access_token({grant_type}) 失败：{detail!r}")


def _ensure_local_token() -> str:
    """本地链路：token 文件未过期直接用；过期用 refresh_token 续；续不动指引重授权。"""
    with _TokenFileLock():
        tok = _read_token_file()
        now = time.time()
        if tok and tok.get("access_token") and now < tok.get("expires_at", 0) - TOKEN_SAFETY_MARGIN:
            _cache["token"] = tok["access_token"]
            _cache["expires_at"] = tok["expires_at"]
            return str(tok["access_token"])

        refresh_token = (tok or {}).get("refresh_token", "")
        if not refresh_token:
            raise RuntimeError(
                "[v1] 本地无可用 token（未授权或 token 文件损坏）。"
                "请运行 mdymcp-auth 重新授权。"
            )
        try:
            new_tok = _exchange_token("refresh_token", refresh_token=refresh_token)
        except Exception as e:
            raise RuntimeError(
                f"[v1] 刷新 token 失败（refresh_token 可能已过期，有效期 14 天）。"
                f"请运行 mdymcp-auth 重新授权。原始错误：{e}"
            ) from e
        _write_token_file(new_tok)
        _cache["token"] = new_tok["access_token"]
        _cache["expires_at"] = new_tok["expires_at"]
        return str(new_tok["access_token"])


def _ensure_server_token() -> str:
    """server 模式：用受限 SSH key 远程读常驻服务器上的 token 文件，取出 access_token。

    每次现取，**不写本地文件、不持有 refresh_token、绝不在客户端 refresh**——
    刷新由服务器上的 refresh-daemon 单点负责（见 server/）。取到的 token 只进
    进程内内存缓存（_cache，按服务器给的 expires_at 失效），不落盘。

    取 token 硬依赖服务器在线 + 网络通（频率低，已接受）；失败时报错明确指向
    服务器 / 网络 / 重新种子，绝不静默。
    """
    host = os.getenv("MD_V1_TOKEN_SSH_HOST", "").strip()
    user = os.getenv("MD_V1_TOKEN_SSH_USER", "").strip()
    key = os.getenv("MD_V1_TOKEN_SSH_KEY", "").strip()
    missing = [name for name, val in (
        ("MD_V1_TOKEN_SSH_HOST", host),
        ("MD_V1_TOKEN_SSH_USER", user),
        ("MD_V1_TOKEN_SSH_KEY", key),
    ) if not val]
    if missing:
        raise RuntimeError(
            f"[v1] server 模式缺配置：{', '.join(missing)}。"
            "请运行 mdymcp-server-setup 重新配置，或在 ~/.mdymcp/.env 补齐。"
        )
    key_path = os.path.expanduser(key)
    if not os.path.exists(key_path):
        raise RuntimeError(
            f"[v1] server 模式 SSH key 不存在：{key_path}。请运行 mdymcp-server-setup 重新配置。"
        )

    cmd = [
        "ssh", "-i", key_path,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
    ]
    # 受限 key 的 forced command 会固定 `cat <token文件>` 并忽略客户端传的命令；
    # 仅当用非受限 key 调试时，MD_V1_TOKEN_REMOTE_PATH 才生效。
    remote_path = os.getenv("MD_V1_TOKEN_REMOTE_PATH", "").strip()
    if remote_path:
        cmd += ["cat", remote_path]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        raise RuntimeError(
            f"[v1] server 模式取 token 失败（SSH 连不上 {user}@{host}，"
            f"检查服务器是否在线 / 网络是否通）：{e}"
        ) from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"[v1] server 模式取 token 失败（ssh 退出码 {proc.returncode}）："
            f"{proc.stderr.strip() or proc.stdout.strip() or '无输出'}"
        )
    try:
        data = json.loads(proc.stdout)
    except Exception as e:
        raise RuntimeError(
            "[v1] server 模式取 token 失败（服务器返回非 JSON，"
            "疑似受限 key 的 forced command 配错或 token 文件路径不对）："
            f"{proc.stdout[:200]!r}"
        ) from e
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError(f"[v1] server 模式：服务器 token 文件里没有 access_token：{data!r}")
    try:
        expires_at = int(data.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    _cache["token"] = access_token
    _cache["expires_at"] = expires_at or int(time.time() + 3600)
    return access_token


def _hook_token_legacy() -> str:
    """旧链路：远端 hook 换 token（未配置 MD_APP_SECRET 的机器回落用，迁移完成后可删）。"""
    account_id = os.getenv("MD_ACCOUNT_ID", "").strip()
    key = os.getenv("MD_KEY", "").strip()
    hook_url = os.getenv("MD_HOOK_URL", HOOK_URL_DEFAULT).strip()
    if not account_id or not key:
        raise RuntimeError(
            "[v1] 未配置本地 OAuth（MD_APP_SECRET）也缺旧凭据 MD_ACCOUNT_ID/MD_KEY。"
            "推荐：在 .env 配 MD_APP_SECRET 后运行 mdymcp-auth 走本地 token。"
        )

    body = json.dumps({"account_id": account_id, "key": key}).encode("utf-8")
    req = urllib.request.Request(
        hook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "mdymcp/0.4",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    token = data.get("token")
    if not token:
        raise RuntimeError(f"[v1] Token endpoint returned no token: {data!r}")

    _cache["token"] = token
    _cache["expires_at"] = _next_local_midnight_ts()
    return str(token)


def ensure_access_token() -> str:
    if _cache["token"] and time.time() < _cache["expires_at"] - 60:
        return str(_cache["token"])

    _load_env()
    # server 模式：去常驻服务器现取，绝不本地 refresh（多 owner 抢刷是 token 失效的真因）
    mode = os.getenv("MD_V1_TOKEN_MODE", "local").strip().lower()
    if mode == "server":
        return _ensure_server_token()
    # 已本地授权 → 本地链路；仅有旧凭据的未迁移机器 → 回落旧 hook；都没有 → 指引授权
    if V1_TOKEN_FILE.exists():
        return _ensure_local_token()
    if os.getenv("MD_ACCOUNT_ID", "").strip() and os.getenv("MD_KEY", "").strip():
        return _hook_token_legacy()
    raise RuntimeError("[v1] 尚未授权。请运行 mdymcp-auth（开浏览器一键授权）。")


def ensure_hap_token() -> str:
    """HAP 网关 token —— 直接用 .env 里的 PAT（pat_xxx），无需任何远端交换。

    PAT 由用户在 https://www.mingdao.com/personal?type=pat 自助生成，本身即 Bearer token，
    长期有效、自管。缺失时抛错指向生成页。
    """
    _load_env()
    pat = os.getenv("MD_HAP_PAT", "").strip()
    if not pat:
        raise RuntimeError(
            "[HAP] 缺 MD_HAP_PAT。请运行 mdymcp-install 填入 HAP PAT，"
            "或在 .env 设 MD_HAP_PAT=pat_xxx"
            "（在 https://www.mingdao.com/personal?type=pat 生成）。"
        )
    return pat


# ─────────────────────────────────────────────
# OAuth 自助注册流程（mdymcp-auth 命令）
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
<html><head><meta charset="utf-8"><title>mdymcp 授权成功</title></head>
<body style="font-family:system-ui;max-width:560px;margin:80px auto;padding:0 24px;color:#222">
<h2>✅ 授权成功</h2>
<p>已收到授权码，正在本地交换 token。请回到终端查看结果，本页面可以关闭。</p>
</body></html>"""

_CALLBACK_HTML_ERR = """<!doctype html>
<html><head><meta charset="utf-8"><title>mdymcp 授权失败</title></head>
<body style="font-family:system-ui;max-width:560px;margin:80px auto;padding:0 24px;color:#222">
<h2>❌ 授权失败</h2>
<p>{msg}</p><p>请回到终端查看详细错误。</p>
</body></html>"""


def _open_incognito(url: str) -> str:
    """用隐身/无痕窗口打开 URL（避免污染默认浏览器会话）。

    依次尝试 Chrome → Edge → Firefox 的隐身模式，全部失败再回落到默认浏览器。
    无论成败都把 URL 复制到剪贴板，便于手动粘贴。
    """
    plat = sys.platform
    attempts: list[tuple[str, list[str]]] = []

    if plat == "darwin":
        mac_candidates = [
            ("Chrome 隐身", "Google Chrome", ["--incognito", "--new-window", url]),
            ("Edge InPrivate", "Microsoft Edge", ["--inprivate", "--new-window", url]),
            ("Firefox 隐私窗口", "Firefox", ["-private-window", url]),
        ]
        for label, app_name, args in mac_candidates:
            if not _mac_app_exists(app_name):
                continue
            attempts.append((label, ["open", "-na", app_name, "--args", *args]))
    elif plat.startswith("win"):
        win_candidates = [
            ("Chrome 隐身", "chrome.exe", ["--incognito", "--new-window", url]),
            ("Edge InPrivate", "msedge.exe", ["--inprivate", "--new-window", url]),
            ("Firefox 隐私窗口", "firefox.exe", ["-private-window", url]),
        ]
        for label, exe_name, args in win_candidates:
            exe_path = _win_find_browser(exe_name)
            if not exe_path:
                continue
            attempts.append((label, [exe_path, *args]))
    else:
        for name, exe, flag in [
            ("Chrome 隐身", "google-chrome", "--incognito"),
            ("Chromium 隐身", "chromium-browser", "--incognito"),
            ("Chromium 隐身", "chromium", "--incognito"),
            ("Edge InPrivate", "microsoft-edge", "--inprivate"),
            ("Firefox 隐私窗口", "firefox", "--private-window"),
        ]:
            if shutil.which(exe):
                attempts.append((name, [exe, flag, "--new-window", url]) if "firefox" not in exe else (name, [exe, flag, url]))

    for label, cmd in attempts:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _copy_to_clipboard(url)
            return label
        except Exception:
            continue

    try:
        webbrowser.open(url)
        _copy_to_clipboard(url)
        return "默认浏览器（未找到隐身浏览器，已回落）"
    except Exception:
        _copy_to_clipboard(url)
        return "剪贴板（请手动粘贴打开）"


def _mac_app_exists(app_name: str) -> bool:
    for base in ("/Applications", os.path.expanduser("~/Applications")):
        if os.path.isdir(os.path.join(base, f"{app_name}.app")):
            return True
    try:
        r = subprocess.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '*' && kMDItemDisplayName == '{app_name}.app'"],
            capture_output=True, text=True, timeout=2,
        )
        if r.stdout.strip():
            return True
    except Exception:
        pass
    return False


def _win_find_browser(exe_name: str) -> str | None:
    found = shutil.which(exe_name)
    if found:
        return found
    candidates = {
        "chrome.exe": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        "msedge.exe": [
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ],
        "firefox.exe": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
    }.get(exe_name, [])
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


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


def _purge_env_vars(env_path: Path, keys: set[str]) -> list[str]:
    """从 .env 删除指定键，返回实际删掉的键名。注释和其它行原样保留。"""
    if not env_path.exists():
        return []
    removed: list[str] = []
    kept: list[str] = []
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip() in keys:
            removed.append(s.split("=", 1)[0].strip())
            continue
        kept.append(raw)
    if removed:
        env_path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    return removed


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
    """一键 OAuth：起本地 server → 开隐身浏览器 → 接 code → 本地换 token → 写 token 文件。

    返回 {"token_file": ...}。app_key/app_secret 已内嵌默认值，无需配置。
    """
    _load_env()
    app_key = os.getenv("MD_APP_KEY", APP_KEY_DEFAULT).strip()
    port = int(os.getenv("MD_CALLBACK_PORT", str(CALLBACK_PORT_DEFAULT)))
    redirect_uri = f"http://localhost:{port}/callback"

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
            f"端口 {port} 已被占用。用 MD_CALLBACK_PORT=xxxx mdymcp-auth 换端口"
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
        raise RuntimeError("等待授权超时（5 分钟），请重新运行 mdymcp-auth。")
    if "error" in res:
        raise RuntimeError(f"授权失败：{res['error']}")
    if res.get("state") != state:
        raise RuntimeError("state 不匹配，疑似 CSRF 攻击，已拒绝。")

    code = res["code"]
    print("→ 已拿到授权码，正在本地换取 token…")

    tok = _exchange_token("authorization_code", code=code, redirect_uri=redirect_uri)
    _write_token_file(tok)
    _cache["token"] = tok["access_token"]
    _cache["expires_at"] = tok["expires_at"]

    # 实调一个轻量 v1 接口确认 token 真可用，避免"授权成功但用不了"
    import urllib.parse as _up
    verify_url = (
        f"{BASE_API_URL}/v1/passport/get_passport_detail?"
        + _up.urlencode({"access_token": tok["access_token"], "format": "json"})
    )
    try:
        verify = _http_json(verify_url)
    except Exception as e:
        raise RuntimeError(f"token 已签发但验证调用失败：{e}") from e
    if not verify.get("success", True) and verify.get("error_code"):
        raise RuntimeError(f"token 已签发但被 v1 API 拒绝：{verify!r}")

    ttl_days = max(1, round((tok["expires_at"] - tok["obtained_at"]) / 86400))
    print(f"→ token 已写入 {V1_TOKEN_FILE}（有效约 {ttl_days} 天，过期自动用 refresh_token 续期）")
    return {"token_file": str(V1_TOKEN_FILE)}
