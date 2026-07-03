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


def _alert(title: str, msg: str, level: str = "timeSensitive") -> None:
    """Bark 推送告警（可选）。/opt/mdymcp/alert.env 里配 BARK_KEY / BARK_KEY_IPAD 才生效。"""
    keys = []
    env_file = TOKEN_FILE.parent / "alert.env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and line.strip().startswith("BARK_KEY"):
                keys.append(line.split("=", 1)[1].strip().strip('"'))
    except FileNotFoundError:
        return
    for key in [k for k in keys if k]:
        try:
            url = (f"https://api.day.app/{key}/"
                   + urllib.parse.quote(title) + "/" + urllib.parse.quote(msg)
                   + f"?group=mdymcp&level={level}&isArchive=1")
            with urllib.request.urlopen(url, timeout=10) as resp:
                resp.read()
        except Exception as e:
            _log(f"WARN: Bark 告警发送失败：{e}")


def _token_alive(access_token: str):
    """实调轻量 v1 接口测活。True=活；False=确认死（10101/10105）；None=探测失败不判死。

    为什么需要（2026-07-03 实锤）：access_token 可能在有效期内被明道**单方面作废**
    （refresh 链却还活着）。daemon 只看本地 expires_at 会误报"无需刷新"，
    然后全网 v1 挂到下一次计划刷新（最长 ~22h）。每小时测活 → 死亡最多 1h 内自愈。
    """
    q = urllib.parse.urlencode({"access_token": access_token, "format": "json"})
    req = urllib.request.Request(
        f"{BASE_API_URL}/v1/passport/get_passport_detail?{q}",
        headers={"Accept": "application/json", "User-Agent": "mdymcp-refresh-daemon/1.1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        _log(f"WARN: 测活探测失败（网络/接口异常，不据此判死）：{e}")
        return None
    if data.get("success"):
        return True
    if data.get("error_code") in (10101, 10105):
        return False
    _log(f"WARN: 测活返回未知错误，不据此判死：{data!r}")
    return None


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
    midlife_death = False

    if remaining > REFRESH_MARGIN:
        # 没到刷新窗口 ≠ token 还活着：测活兜底（中年死亡 → 立即强刷自愈）
        alive = _token_alive(str(tok.get("access_token") or ""))
        if alive is not False:
            _log(f"OK: 无需刷新，access_token 还有 {remaining // 3600}h{(remaining % 3600) // 60}m 到期"
                 f"（测活：{'通过' if alive else '跳过'}）。")
            return
        _log("ALERT: access_token 未到期但已被作废（中年死亡），强制刷新自愈…")
        midlife_death = True

    refresh_token = str(tok.get("refresh_token") or "").strip()
    if not refresh_token:
        _log("ERROR: token 文件无 refresh_token，无法刷新。需要重新种 seed。")
        sys.exit(2)

    # 写盘预检（致命教训 2026-06-29）：明道 oauth2 refresh 会**轮换** refresh_token——
    # 一旦 _exchange_refresh 成功，旧 refresh_token 立即作废，必须把新 token 落盘才算完成。
    # 若先 refresh 成功、后 _write_token 因目录不可写失败，旧 token 已废、新 token 没存
    # → token 当场变孤儿（10101），且重试都用作废的旧 token 雪崩。
    # 因此刷新前先确认目录可写：不可写就直接退出、**绝不消耗 refresh_token**，等修好权限下轮自愈。
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _probe = TOKEN_FILE.with_suffix(".writeprobe")
        _probe.write_text("ok", encoding="utf-8")
        _probe.unlink()
    except Exception as e:
        _log(f"ERROR: token 目录不可写（{TOKEN_FILE.parent}），中止刷新以保住 refresh_token。"
             f"请确保该目录归 daemon 运行用户所有（chown）。底层错误：{e}")
        sys.exit(3)

    _log(f"距过期 {remaining}s（< 余量 {REFRESH_MARGIN}s），开始刷新…")
    last_err: Exception | None = None
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            new_tok = _exchange_refresh(refresh_token)
            _write_token(new_tok)
            ttl_h = (new_tok["expires_at"] - now) // 3600
            _log(f"DONE: 刷新成功，新 access_token 有效约 {ttl_h}h，refresh_token 已轮换并落盘。")
            if midlife_death:
                # 中年死亡自愈成功 → 静默推送记录死亡时刻，帮排查是谁作废了 token
                _alert("mdymcp token 中年死亡已自愈",
                       f"access_token 在有效期内被外部作废，已强刷恢复（{time.strftime('%m-%d %H:%M')}）。"
                       "想想这个时间点你/系统在明道侧做了什么。", level="passive")
            return
        except Exception as e:
            last_err = e
            _log(f"WARN: 第 {attempt}/{RETRY_TIMES} 次刷新失败：{e}")
            if attempt < RETRY_TIMES:
                time.sleep(RETRY_BACKOFF * attempt)

    _log(f"ERROR: 连续 {RETRY_TIMES} 次刷新失败，token 链有断裂风险（refresh_token 14 天过期）。"
         f"最后错误：{last_err}")
    _alert("mdymcp token 刷新失败",
           f"服务器连续 {RETRY_TIMES} 次刷新失败，链有断裂风险，需人工检查。最后错误：{last_err}")
    sys.exit(1)


if __name__ == "__main__":
    main()
