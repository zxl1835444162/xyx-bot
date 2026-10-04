#!/usr/bin/env bash
# 在 macOS 上**直接从源码**运行（不打包，适合自己用 / 改代码）
#
# 用法：
#     bash scripts/run_macos.sh            # 启动图形界面
#     bash scripts/run_macos.sh cli books  # 走命令行模式（透传给 main.py）
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "✗ 没找到 python3。建议装 python.org 官方版（自带 tkinter）。" >&2
  exit 1
fi

# 复用已有的虚拟环境（有就用，没有就提示）
for VENV in .venv-mac .venv312 .venv; do
  if [ -x "$VENV/bin/python3" ]; then
    PY="$VENV/bin/python3"
    break
  fi
done

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo "✗ 这个 Python 没有 tkinter，起不了图形界面：$PY" >&2
  echo "    macOS 上：装 python.org 官方版，或 brew install python-tk" >&2
  exit 1
fi

if ! "$PY" -c "import playwright" >/dev/null 2>&1; then
  echo "==> 缺 playwright，先装依赖"
  "$PY" -m pip install -r requirements-gui.txt
fi

echo "==> 解释器：$PY"
exec "$PY" launcher.py "$@"
