"""HTTP client for Mingdao v1 API."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .auth import BASE_API_URL, ensure_access_token, invalidate_cached_token

# access_token 可能在有效期内被明道单方面作废（2026-07-03 实锤：中年死亡，refresh 链还活）。
# 进程内缓存的 token 死了不该报错到底——清缓存重取一次（server 模式会拿到服务器自愈后的新 token）。
_TOKEN_INVALID_CODES = {10101, 10105}


def _token_invalid(resp: dict[str, Any]) -> bool:
    return (not resp.get("success", True)) and resp.get("error_code") in _TOKEN_INVALID_CODES


def _get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = _get_once(endpoint, params)
    if _token_invalid(resp):
        invalidate_cached_token()
        resp = _get_once(endpoint, params)
    return resp


def _get_once(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token = ensure_access_token()
    all_params: dict[str, Any] = {"access_token": token, "format": "json"}
    if params:
        all_params.update({k: v for k, v in params.items() if v is not None and v != ""})
    query = urllib.parse.urlencode(all_params)
    url = f"{BASE_API_URL}{endpoint}?{query}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "mdymcp/0.2"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = _post_once(endpoint, data)
    if _token_invalid(resp):
        invalidate_cached_token()
        resp = _post_once(endpoint, data)
    return resp


def _post_once(endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    token = ensure_access_token()
    all_data: dict[str, Any] = {"access_token": token, "format": "json"}
    if data:
        all_data.update({k: v for k, v in data.items() if v is not None and v != ""})
    body = urllib.parse.urlencode(all_data).encode("utf-8")
    url = f"{BASE_API_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "mdymcp/0.2",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_get(endpoint: str, **kwargs: Any) -> dict[str, Any]:
    return _get(endpoint, kwargs if kwargs else None)


def api_post(endpoint: str, **kwargs: Any) -> dict[str, Any]:
    return _post(endpoint, kwargs if kwargs else None)
