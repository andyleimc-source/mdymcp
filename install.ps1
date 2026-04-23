# mdymcp 一键安装脚本（Windows PowerShell）
# 用法：
#   powershell -c "irm https://raw.githubusercontent.com/andyleimc-source/mdymcp/main/install.ps1 | iex"
#
# 做三件事：
#   1) 如果没有 uv，自动装 uv（astral.sh 官方脚本）
#   2) uv tool install mdymcp（持久安装，uv 自动挑合适的 Python，绕开 3.14 / 太老的坑）
#   3) 跑 mdymcp-install 交互式向导，完成 OAuth + HAP + MCP 客户端注册

$ErrorActionPreference = 'Stop'

function Info  ([string]$m) { Write-Host "[mdymcp] $m" -ForegroundColor Cyan }
function Ok    ([string]$m) { Write-Host "✅ $m" -ForegroundColor Green }
function Warn  ([string]$m) { Write-Host "⚠️  $m" -ForegroundColor Yellow }
function ErrMsg([string]$m) { Write-Host "❌ $m" -ForegroundColor Red }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Info "未检测到 uv，正在从 astral.sh 安装…"
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        ErrMsg "uv 安装失败：$_"
        ErrMsg "请手动安装：https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    }
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    Ok "uv 安装完成"
} else {
    Ok "已检测到 uv：$((Get-Command uv).Source)"
}

Info "安装 / 升级 mdymcp（uv 会自动挑合适的 Python 解释器）"
uv tool install --upgrade --refresh mdymcp

$uvToolBin = & uv tool dir --bin 2>$null
if (-not $uvToolBin) { $uvToolBin = "$env:USERPROFILE\.local\bin" }
$env:PATH = "$uvToolBin;$env:PATH"

if (-not (Get-Command mdymcp-install -ErrorAction SilentlyContinue)) {
    ErrMsg "mdymcp-install 未找到。请手动把 $uvToolBin 加入 PATH 后重试。"
    ErrMsg "或直接跑：uvx --from mdymcp mdymcp-install"
    exit 1
}

Info "启动交互式配置"
& mdymcp-install
