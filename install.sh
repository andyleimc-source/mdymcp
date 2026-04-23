#!/usr/bin/env sh
# mdymcp 一键安装脚本（mac / linux）
# 用法：
#   curl -LsSf https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/install.sh | sh
#
# 做三件事：
#   1) 如果没有 uv，自动装 uv（astral.sh 官方脚本）
#   2) uv tool install mdymcp（持久安装，uv 自动挑合适的 Python，绕开 3.14 / 太老的坑）
#   3) 跑 mdymcp-install 交互式向导，完成 OAuth + HAP + MCP 客户端注册

set -e

info()  { printf "\033[36m[mdymcp]\033[0m %s\n" "$1"; }
ok()    { printf "\033[32m✅\033[0m %s\n" "$1"; }
warn()  { printf "\033[33m⚠️ \033[0m %s\n" "$1"; }
err()   { printf "\033[31m❌\033[0m %s\n" "$1" >&2; }

if ! command -v uv >/dev/null 2>&1; then
    info "未检测到 uv，正在从 astral.sh 安装…"
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        err "uv 安装失败。请手动安装：https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
    # install.sh 会把 uv 放到 ~/.local/bin（或 ~/.cargo/bin）
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    ok "uv 安装完成"
else
    ok "已检测到 uv：$(command -v uv)"
fi

info "安装 / 升级 mdymcp（uv 会自动挑合适的 Python 解释器）"
# --refresh 强制 uv 跳过 PyPI 索引缓存，避免刚发布的新版本看不到
uv tool install --upgrade --refresh mdymcp

# uv tool 把可执行文件放在 `uv tool dir --bin`，把它加进本次会话的 PATH
UV_TOOL_BIN="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
export PATH="$UV_TOOL_BIN:$PATH"

if ! command -v mdymcp-install >/dev/null 2>&1; then
    err "mdymcp-install 未找到。请手动 export PATH=\"$UV_TOOL_BIN:\$PATH\" 后重试。"
    err "或直接跑：uvx --from mdymcp mdymcp-install"
    exit 1
fi

info "启动交互式配置"
# curl ... | sh 会把 stdin 占给脚本本身，导致 mdymcp-install 的 input() 直接 EOF。
# 把 stdin 重定向到 /dev/tty（真实终端），这样交互提示就能读到键盘。
# 没有终端（如 CI）时 /dev/tty 打不开，提示用户手动接着跑。
if [ -r /dev/tty ]; then
    exec mdymcp-install </dev/tty
else
    warn "检测不到终端（可能在 CI / 非交互环境运行）。"
    warn "请在普通终端里直接运行：mdymcp-install"
    exit 0
fi
