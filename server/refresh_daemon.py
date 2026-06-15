#!/usr/bin/env python3
"""mdymcp v1 token 服务器集中刷新 daemon（单 owner，one-shot）。

设计见仓库根 handoff-mdymcp-server-refresh.md。要点：
  - 这台常驻服务器是 v1 token 的**唯一 owner**：只有它持有 refresh_token、只有它 refresh。
  - 明道 oauth2 每次 refresh 都会**轮换 refresh_token**——所以全网只能有一个 owner，
    否则两端互相把对方顶成孤儿（error_code 10101 / access_token 不存在）。
  - one-shot 设计：每次运行只判断「是否快过期」，快过期才 refresh 并落盘。
    由 systemd timer 每小时拉起一次 → 漏跑几次也不会断链（access_token 寿命 24h）。
  - 自包含、零三方依赖（urllib + 标准库），可直接 scp 到服务器跑。

退出码：0=正常（刷新或无需刷新都算）；非 0=刷新失败（systemd 会记录，可接告警）。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# 公共客户端模式：app_key/app_secret 有意公开内嵌（同 mdymcp/auth.py，安全边界在用户授权）。
# 可用环境变量 MD_APP_KEY / MD_APP_SECRET 覆盖。
APP_KEY_DEFAULT = "6A228C49DAC4"
APP_SECRET_DEFAULT = "29F04C41F3C41EDA8297F3B273AD710"
BASE_API_URL = "https://api.mingdao.com"

TOKEN_FILE = Path(os.getenv("MDYMCP_TOKEN_FILE", "/opt/mdymcp/v1_token.json"))
# 距过期还剩多少秒就提前 refresh。access_token 寿命 24h，留 2h 余量足够，
# 也把「每次 refresh 都轮换 refresh_token」的轮换频率压到约 1 次/天。
REFRESH_MARGIN = int(os.getenv("MDYMCP_REFRESH_MARGIN", str(2 * 3600)))
RETRY_TIMES = 3
RETRY_BACKOFF = 5  # 秒，指数退避基数


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _read_token() -> dict:
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _log(f"ERROR: token 文件不存在：{TOKEN_FILE}。需要先种 seed（本地 mdymcp-auth → 推上来）。")
        sys.exit(2)
    except Exception as e:
        _log(f"ERROR: token 文件解析失败：{e}")
        sys.exit(2)


def _write_token(data: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(TOKEN_FILE)  # 原子替换，避免客户端读到半个文件
    os.chmod(TOKEN_FILE, 0o600)


def _exchange_refresh(refresh_token: str) -> dict:
    app_key = os.getenv("MD_APP_KEY", APP_KEY_DEFAULT).strip()
    app_secret = os.getenv("MD_APP_SECRET", APP_SECRET_DEFAULT).strip()
    q = {
        "app_key": app_key,
        "app_secret": app_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "format": "json",
    }
    endpoint = f"{BASE_API_URL}/oauth2/access_token"
    body = urllib.parse.urlencode(q).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "mdymcp-refresh-daemon/1.0",
    }
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    access_token = str(payload.get("access_token") or "").strip()
    new_refresh = str(payload.get("refresh_token") or "").strip()
    if not access_token or not new_refresh:
        raise RuntimeError(f"oauth2 返回缺 token：{data!r}")
    now = int(time.time())
    try:
        expires_in = int(payload.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    if expires_in <= 0:
        expires_in = 86400
    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "expires_at": now + expires_in,
        "obtained_at": now,
    }


def main() -> None:
    tok = _read_token()
    now = int(time.time())
    expires_at = int(tok.get("expires_at") or 0)
    remaining = expires_at - now

    if remaining > REFRESH_MARGIN:
        _log(f"OK: 无需刷新，access_token 还有 {remaining // 3600}h{(remaining % 3600) // 60}m 到期。")
        return

    refresh_token = str(tok.get("refresh_token") or "").strip()
    if not refresh_token:
        _log("ERROR: token 文件无 refresh_token，无法刷新。需要重新种 seed。")
        sys.exit(2)

    _log(f"距过期 {remaining}s（< 余量 {REFRESH_MARGIN}s），开始刷新…")
    last_err: Exception | None = None
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            new_tok = _exchange_refresh(refresh_token)
            _write_token(new_tok)
            ttl_h = (new_tok["expires_at"] - now) // 3600
            _log(f"DONE: 刷新成功，新 access_token 有效约 {ttl_h}h，refresh_token 已轮换并落盘。")
            return
        except Exception as e:
            last_err = e
            _log(f"WARN: 第 {attempt}/{RETRY_TIMES} 次刷新失败：{e}")
            if attempt < RETRY_TIMES:
                time.sleep(RETRY_BACKOFF * attempt)

    _log(f"ERROR: 连续 {RETRY_TIMES} 次刷新失败，token 链有断裂风险（refresh_token 14 天过期）。"
         f"最后错误：{last_err}")
    sys.exit(1)


if __name__ == "__main__":
    main()
