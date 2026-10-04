#!/usr/bin/env bash
# 在 macOS 上把本项目打成 XYXBot.app
#
# 用法：
#     bash scripts/build_macos.sh
# 产物：
#     dist/XYXBot.app
#     dist/XYXBot-macos-<架构>.zip
#
# ★ 必须在 macOS 上跑 —— PyInstaller **不能跨平台编译**，
#   在 Windows / Linux 上做不出 macOS 的 .app。
#   （GitHub Actions 里由 .github/workflows/build-macos.yml 自动完成这件事。）
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
ARCH="$(uname -m)"

echo "==> 项目目录 : $ROOT"
echo "==> 机器架构 : $ARCH （本机打出来的包只适用于本架构）"
echo "==> 系统版本 : $(sw_vers -productVersion 2>/dev/null || echo '?')"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ 没找到 python3。建议装 python.org 官方版（自带 tkinter）：" >&2
  echo "    https://www.python.org/downloads/macos/" >&2
  exit 1
fi

echo "==> 检查这个 Python 有没有 tkinter（GUI 必需）"
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "✗ 当前 python3 没有 tkinter，做出来的 .app 会起不来。" >&2
  echo "    用 python.org 的官方安装包，或 brew install python-tk" >&2
  exit 1
fi
echo "    ✓ tkinter 可用"
"$PY" -c "import tkinter, sys; print('    Tk 版本:', tkinter.TkVersion, '| Python:', sys.version.split()[0])"

VENV=".venv-mac"
if [ ! -d "$VENV" ]; then
  echo "==> 创建虚拟环境 $VENV"
  "$PY" -m venv "$VENV"
fi

# shellcheck disable=SC1091
. "$VENV/bin/activate"

echo "==> 安装依赖"
python -m pip install --upgrade pip >/dev/null
pip install -r requirements-gui.txt
pip install "pyinstaller>=6.6"

echo "==> 版本自检"
python -c "import playwright, tkinter, PyInstaller; print('    playwright', playwright.__version__ if hasattr(playwright,'__version__') else 'ok'); print('    pyinstaller', PyInstaller.__version__)"

echo "==> 先跑一遍不依赖窗口的测试（有问题就别打包了）"
for t in test_fixes test_waiting test_runplan test_memory test_portability; do
  if [ -f "tests/$t.py" ]; then
    echo "    --- $t ---"
    python "tests/$t.py"
  fi
done

echo "==> PyInstaller 打包（第一次会比较慢）"
rm -rf build dist
pyinstaller --clean --noconfirm packaging/macos/xyxbot.spec

if [ ! -d "dist/XYXBot.app" ]; then
  echo "✗ 没产出 dist/XYXBot.app，看上面的 PyInstaller 输出" >&2
  exit 1
fi

echo "==> 压缩（ditto 能保留 .app 的权限与符号链接，别用 zip）"
ZIP="dist/XYXBot-macos-${ARCH}.zip"
ditto -c -k --keepParent "dist/XYXBot.app" "$ZIP"

echo
echo "============================================================"
echo "  ✓ 打包完成"
echo "    应用 : $ROOT/dist/XYXBot.app"
echo "    压缩 : $ROOT/$ZIP  ($(du -h "$ZIP" | cut -f1))"
echo
echo "  未签名的 .app 第一次打开会被 Gatekeeper 拦，两种办法："
echo "    ① 在 Finder 里【右键 → 打开】→ 再点【打开】"
echo "    ② 或执行： xattr -cr \"$ROOT/dist/XYXBot.app\""
echo
echo "  数据目录（登录态/配置/细纲/日志都在这里）："
echo "    ~/Library/Application Support/XYXBot/artifacts/"
echo "============================================================"
