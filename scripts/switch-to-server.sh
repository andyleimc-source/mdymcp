#!/usr/bin/env bash
# 把当前这台 Mac 切成 mdymcp v1 token 的 server 只读模式（read-only client）。
#
# 做的事（幂等，可重复跑）：
#   1. 从一台已切好的 peer（默认 work）拉受限 SSH key 到 ~/.mdymcp/
#   2. 全局 uv tool 装 mdymcp==0.5.0
#   3. 写 4 个 MD_V1_TOKEN_* 到 ~/.mdymcp/.env（保留现有 PAT/凭据，不重新授权）
#   4. 顺带把 weekly-md 的 .venv 里的 mdymcp 也升到 0.5.0（它会 import 调用）
#   5. 验证 server 模式能取到 token
#
# 用法（在要切的那台机器上跑）：
#   bash scripts/switch-to-server.sh
#   PEER=100.86.179.75 bash scripts/switch-to-server.sh   # 改从 m1pro 拉 key
#
# ⚠️ 别在这台机器重新授权（mdymcp-auth），否则会轮换种子把服务器顶成孤儿。
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

VERSION="0.5.1"
PEER="${PEER:-100.82.108.123}"          # 受限 key 来源机（默认 work；m1pro=100.86.179.75）
HOST="101.43.4.46"; SSH_USER="ubuntu"
MDY="$HOME/.mdymcp"; KEY="$MDY/server_token_key"
mkdir -p "$MDY"

echo "==> 1/5 从 $PEER 拉受限 key…"
scp -o StrictHostKeyChecking=accept-new "andy@${PEER}:~/.mdymcp/server_token_key" "$KEY"
chmod 600 "$KEY"

echo "==> 2/5 全局安装 mdymcp==$VERSION…"
uv tool install --force --refresh-package mdymcp "mdymcp==$VERSION" >/dev/null 2>&1 || \
  uv tool install --force --refresh-package mdymcp "mdymcp==$VERSION"

PYBIN="$HOME/.local/share/uv/tools/mdymcp/bin/python3"

echo "==> 3/5 写 server 配置到 ~/.mdymcp/.env（保留现有凭据，不重新授权）…"
"$PYBIN" - "$HOST" "$SSH_USER" "$KEY" <<'PY'
import sys
from pathlib import Path
from mdymcp.auth import _write_env_vars
host, user, key = sys.argv[1], sys.argv[2], sys.argv[3]
_write_env_vars(Path.home()/".mdymcp"/".env", {
    "MD_V1_TOKEN_MODE": "server",
    "MD_V1_TOKEN_SSH_HOST": host,
    "MD_V1_TOKEN_SSH_USER": user,
    "MD_V1_TOKEN_SSH_KEY": key,
})
print("   .env 已更新")
PY

echo "==> 4/5 升级项目 venv 里的 mdymcp（weekly-md 等）…"
for venv in "$HOME/Documents/running/hap/weekly-md/.venv"; do
  if [ -x "$venv/bin/python" ] && "$venv/bin/python" -c "import mdymcp" 2>/dev/null; then
    uv pip install --python "$venv/bin/python" -U "mdymcp==$VERSION" >/dev/null 2>&1
    echo "   $venv → $("$venv/bin/python" -c 'import importlib.metadata as m;print(m.version("mdymcp"))')"
  fi
done

echo "==> 5/5 验证 server 模式取 token…"
"$PYBIN" -c "import importlib.metadata as m; from mdymcp.auth import ensure_access_token; print('   全局 mdymcp', m.version('mdymcp'), '| ✅ 取到 token len', len(ensure_access_token()))"

echo "🎉 完成。重启 MCP 客户端（或重开会话）生效。"
