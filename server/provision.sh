#!/usr/bin/env bash
# mdymcp v1 token 服务器集中刷新——一次性 provision（在本地 Mac 跑，部署到你自己的服务器）。
#
# 做的事（全部一次性）：
#   1. 校验本地已有 seed token（~/.mdymcp/v1_token.json，含 refresh_token）
#   2. 生成一把**专用受限 SSH key**（~/.mdymcp/server_token_key，仅用于远程读 token）
#   3. 把 refresh_daemon.py + systemd 单元 + seed token + 受限公钥 推到服务器
#   4. 服务器上：装 daemon、种 token、起 systemd timer（每小时检查、快过期才刷）
#   5. 把受限公钥写进服务器 authorized_keys 并锁 forced command（只能 `cat` 那个 token 文件）
#   6. 打印客户端 .env 配置（MD_V1_TOKEN_MODE=server + host/user/key）
#
# 用法：  bash server/provision.sh <服务器IP> [登录用户=ubuntu]
# 例：    bash server/provision.sh 101.43.4.46 ubuntu
#
# 前置：本地先跑过 mdymcp-auth 拿到 seed token；服务器能用密码/已有 key SSH 登录。
set -euo pipefail

HOST="${1:?用法: bash server/provision.sh <服务器IP> [用户=ubuntu]}"
SSH_USER="${2:-ubuntu}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MDYMCP_HOME="${HOME}/.mdymcp"
SEED_TOKEN="${MDYMCP_HOME}/v1_token.json"
RESTRICTED_KEY="${MDYMCP_HOME}/server_token_key"
REMOTE_TOKEN_PATH="/opt/mdymcp/v1_token.json"

echo "==> 目标服务器：${SSH_USER}@${HOST}"

# ── 1. 校验 seed token ──────────────────────────────────────────────
if [[ ! -f "${SEED_TOKEN}" ]]; then
  echo "❌ 本地没有 seed token：${SEED_TOKEN}"
  echo "   请先在本机跑 mdymcp-auth 完成一次浏览器授权，再回来跑本脚本。"
  exit 1
fi
if ! grep -q '"refresh_token"' "${SEED_TOKEN}"; then
  echo "❌ seed token 里没有 refresh_token，无法供服务器续期。请重新跑 mdymcp-auth。"
  exit 1
fi

# ── 2. 生成专用受限 key（已存在则复用）────────────────────────────────
if [[ ! -f "${RESTRICTED_KEY}" ]]; then
  echo "==> 生成专用受限 SSH key：${RESTRICTED_KEY}"
  ssh-keygen -t ed25519 -N "" -C "mdymcp-v1-token-readonly" -f "${RESTRICTED_KEY}" >/dev/null
else
  echo "==> 复用已存在的受限 key：${RESTRICTED_KEY}"
fi
RESTRICTED_PUB="$(cat "${RESTRICTED_KEY}.pub")"

# ── 3. SSH 连接复用：整个过程只输一次密码 ─────────────────────────────
CTL="$(mktemp -u "${TMPDIR:-/tmp}/mdymcp-ssh-XXXXXX")"
SSH_OPTS=(-o "ControlMaster=auto" -o "ControlPath=${CTL}" -o "ControlPersist=120" \
          -o "StrictHostKeyChecking=accept-new")
cleanup() { ssh "${SSH_OPTS[@]}" -O exit "${SSH_USER}@${HOST}" 2>/dev/null || true; }
trap cleanup EXIT

echo "==> 建立 SSH 连接（如提示请输入服务器登录密码）…"
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${HOST}" "true"

# ── 4. 推文件到服务器临时目录 ─────────────────────────────────────────
REMOTE_TMP="/tmp/mdymcp-provision-$$"
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${HOST}" "mkdir -p ${REMOTE_TMP}"
scp "${SSH_OPTS[@]}" \
  "${SCRIPT_DIR}/refresh_daemon.py" \
  "${SCRIPT_DIR}/mdymcp-refresh.service" \
  "${SCRIPT_DIR}/mdymcp-refresh.timer" \
  "${SEED_TOKEN}" \
  "${SSH_USER}@${HOST}:${REMOTE_TMP}/"

# ── 5. 服务器端安装（一个远程脚本里全干完）──────────────────────────────
echo "==> 服务器端安装 daemon + systemd timer（如提示请输入 sudo 密码）…"
ssh "${SSH_OPTS[@]}" "${SSH_USER}@${HOST}" \
  "RUN_USER='${SSH_USER}' REMOTE_TMP='${REMOTE_TMP}' RESTRICTED_PUB='${RESTRICTED_PUB}' REMOTE_TOKEN_PATH='${REMOTE_TOKEN_PATH}' bash -s" <<'REMOTE'
set -euo pipefail

sudo mkdir -p /opt/mdymcp
# 目录本身必须归 RUN_USER：daemon 原子写 token 时要在此目录建临时文件 v1_token.tmp，
# 目录若归 root，daemon（以 RUN_USER 跑）建临时文件会 Permission denied → 刷新成功却存不下来
# → refresh_token 被明道轮换作废但新 token 没落盘 → token 当场变孤儿（10101）。（2026-06-29 踩坑）
sudo chown "${RUN_USER}:${RUN_USER}" /opt/mdymcp
sudo install -m 0644 "${REMOTE_TMP}/refresh_daemon.py" /opt/mdymcp/refresh_daemon.py
sudo install -m 0600 "${REMOTE_TMP}/v1_token.json"     "${REMOTE_TOKEN_PATH}"
sudo chown "${RUN_USER}:${RUN_USER}" "${REMOTE_TOKEN_PATH}"

# service 里替换运行用户占位
sudo sed "s/__RUN_USER__/${RUN_USER}/" "${REMOTE_TMP}/mdymcp-refresh.service" \
  | sudo tee /etc/systemd/system/mdymcp-refresh.service >/dev/null
sudo install -m 0644 "${REMOTE_TMP}/mdymcp-refresh.timer" /etc/systemd/system/mdymcp-refresh.timer

sudo systemctl daemon-reload
sudo systemctl enable --now mdymcp-refresh.timer
# 立刻跑一次，验证能刷/能读
sudo systemctl start mdymcp-refresh.service || true

# ── 受限公钥写入 authorized_keys（幂等：先删旧的同 comment 行）──────────
AUTH_KEYS="${HOME}/.ssh/authorized_keys"
mkdir -p "${HOME}/.ssh"; chmod 700 "${HOME}/.ssh"
touch "${AUTH_KEYS}"; chmod 600 "${AUTH_KEYS}"
grep -v "mdymcp-v1-token-readonly" "${AUTH_KEYS}" > "${AUTH_KEYS}.new" || true
mv "${AUTH_KEYS}.new" "${AUTH_KEYS}"
FORCED="command=\"cat ${REMOTE_TOKEN_PATH}\",no-pty,no-port-forwarding,no-X11-forwarding,no-agent-forwarding"
echo "${FORCED} ${RESTRICTED_PUB}" >> "${AUTH_KEYS}"
chmod 600 "${AUTH_KEYS}"

rm -rf "${REMOTE_TMP}"

echo "---- 服务器端状态 ----"
systemctl is-active mdymcp-refresh.timer && echo "timer: active" || echo "timer: NOT active"
echo "最近一次刷新日志："
journalctl -u mdymcp-refresh -n 5 --no-pager 2>/dev/null || true
REMOTE

# ── 6. 远程读 token 自测（用受限 key）─────────────────────────────────
echo "==> 用受限 key 自测远程读 token…"
if ssh -i "${RESTRICTED_KEY}" -o "BatchMode=yes" -o "StrictHostKeyChecking=accept-new" \
     "${SSH_USER}@${HOST}" | grep -q '"access_token"'; then
  echo "✅ 受限 key 能读到 token（且只能 cat 这一个文件）。"
else
  echo "⚠️  受限 key 自测没读到 access_token，请人工检查服务器 authorized_keys / token 文件。"
fi

# ── 7. 写客户端 .env ─────────────────────────────────────────────────
ENV_FILE="${MDYMCP_HOME}/.env"
mkdir -p "${MDYMCP_HOME}"
python3 - "$ENV_FILE" "$HOST" "$SSH_USER" "$RESTRICTED_KEY" <<'PY'
import sys, pathlib
env_path, host, user, key = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
updates = {
    "MD_V1_TOKEN_MODE": "server",
    "MD_V1_TOKEN_SSH_HOST": host,
    "MD_V1_TOKEN_SSH_USER": user,
    "MD_V1_TOKEN_SSH_KEY": key,
}
lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
seen = set(); out = []
for raw in lines:
    s = raw.strip()
    if s and not s.startswith("#") and "=" in s and s.split("=",1)[0].strip() in updates:
        k = s.split("=",1)[0].strip(); out.append(f"{k}={updates[k]}"); seen.add(k); continue
    out.append(raw)
for k, v in updates.items():
    if k not in seen: out.append(f"{k}={v}")
env_path.write_text("\n".join(out).rstrip()+"\n", encoding="utf-8")
print(f"==> 已写入客户端配置：{env_path}")
PY

echo
echo "🎉 完成。本机已切到 server 模式（重启 MCP 客户端生效）。"
echo "   其余机器：把同一把受限 key（${RESTRICTED_KEY}）和这 4 个 MD_V1_TOKEN_* 配置拷过去即可。"
echo "   ⚠️ 切 server 后，**所有**用同一明道账号的端都要切 server——一个账号只能有一个 owner。"
