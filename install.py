#!/usr/bin/env python3
"""mdymcp 一键交互式安装脚本（Clone 模式入口）。

用法：clone 仓库后在项目根目录运行
    python3 install.py

脚本会：
  1) 可选 git pull 拉最新代码
  2) 创建 .venv 并安装 mdymcp
  3) 把控制权交给 venv 里的 `mdymcp-install --from-clone <repo-root>`
     完成 OAuth、凭据验证、MCP 客户端注册

PyPI 用户请直接用 uv 一行安装（见 README），不用跑这个脚本。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def info(msg: str) -> None:
    print(f"\033[36m[mdymcp]\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"\033[32m✅\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"\033[33m⚠️ \033[0m {msg}")


def err(msg: str) -> None:
    print(f"\033[31m❌\033[0m {msg}", file=sys.stderr)


def run(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, **kw)


def _try_git_pull() -> None:
    if not (ROOT / ".git").exists():
        return
    try:
        r = subprocess.run(
            ["git", "-C", str(ROOT), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            msg = (r.stdout.strip() or "已是最新").splitlines()[-1]
            info(f"git pull：{msg}")
        else:
            warn(f"git pull 失败，将继续使用当前代码：{r.stderr.strip()[:160]}")
    except Exception as e:
        warn(f"git pull 异常：{e}")


def step_venv() -> Path:
    info("准备 Python 虚拟环境")
    _try_git_pull()
    py = VENV / "bin" / "python3"
    if not py.exists():
        py_sys = Path(sys.executable)
        info(f"用 {py_sys} 创建 {VENV}")
        run([str(py_sys), "-m", "venv", str(VENV)])
    else:
        info(f"已存在 {VENV}，跳过创建")

    info("安装/更新 mdymcp 包")
    run([str(py), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    # --force-reinstall --no-deps 保证即使版本号没变也能覆盖本地改动
    run([str(py), "-m", "pip", "install", "--quiet", "--upgrade",
         "--force-reinstall", "--no-deps", "."], cwd=str(ROOT))
    run([str(py), "-m", "pip", "install", "--quiet", "."], cwd=str(ROOT))
    ok("虚拟环境就绪")
    return py


def preflight() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 10):
        err(f"Python {major}.{minor} 过低，mdymcp 要求 ≥ 3.10。")
        sys.exit(1)
    if shutil.which("python3") is None:
        err("未检测到 python3。请先安装 Python 3.10+。")
        sys.exit(1)
    try:
        subprocess.run([sys.executable, "-m", "venv", "--help"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError:
        err(f"{sys.executable} 不含 venv 模块。")
        sys.exit(1)


def main() -> None:
    print("=" * 56)
    print("  mdymcp 交互式安装（Clone 模式）")
    print("=" * 56)
    preflight()
    py = step_venv()
    # 把剩下的交互流程交给 venv 里的 mdymcp-install，保持单一实现
    installer = VENV / "bin" / "mdymcp-install"
    if not installer.exists():
        err(f"{installer} 不存在，pip install 可能失败了")
        sys.exit(1)
    cmd = [str(installer), "--from-clone", str(ROOT)] + sys.argv[1:]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(130)
