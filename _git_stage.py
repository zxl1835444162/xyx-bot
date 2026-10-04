# -*- coding: utf-8 -*-
"""初始化本地 git 仓库并暂存文件，然后**报告**将要提交的内容。

★ 这一步不推送、不建远端仓库，先让人看清"要提交什么"。
   重点确认：没有把 artifacts/（含明文登录票据）带进去。
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

ROOT = Path.cwd()
GIT = Path(os.environ["USERPROFILE"]) / ".workbuddy" / "binaries" / \
    "PortableGit" / "versions" / "1.2.0" / "cmd" / "git.exe"

env = dict(os.environ)
env["PATH"] = str(GIT.parent) + os.pathsep + env.get("PATH", "")
# 避免 git 弹任何交互
env["GIT_TERMINAL_PROMPT"] = "0"
env["GCM_INTERACTIVE"] = "never"


def run(*args, check=True):
    r = subprocess.run([str(GIT), *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    if check and r.returncode != 0:
        print(f"✗ git {' '.join(args)} 失败：\n{r.stdout}\n{r.stderr}")
        sys.exit(1)
    return (r.stdout or "").strip()


print(f"git 版本: {run('--version')}")
print(f"仓库目录: {ROOT}\n")

if not (ROOT / ".git").exists():
    print("==> git init -b main")
    run("init", "-b", "main")
else:
    print("==> 已有 .git，跳过 init")

# ★ 不设全局身份（那是用户的机器配置），只给这个仓库设一份
run("config", "user.name", "zxl1835444162")
run("config", "user.email", "62532629+zxl1835444162@users.noreply.github.com")
print("==> 已设仓库级 user.name / user.email（不改你的全局配置）")

print("==> git add -A")
run("add", "-A")

files = [f for f in run("ls-files").splitlines() if f]
print(f"\n暂存文件数: {len(files)}")

# ---- 安全检查：绝不能提交这些东西 ----
DANGER = ["artifacts/storage/", "state.json", "state.backup.json",
          "session_meta.json", "credentials.json", ".venv"]
bad = [f for f in files
       if any(f.startswith(d) or f.endswith(d) for d in DANGER)]
print(f"\n★ 危险文件检查: {'✓ 没有敏感文件' if not bad else '✗ 有！' + str(bad)}")

# ---- 体积统计 ----
total = 0
big = []
for f in files:
    p = ROOT / f
    if p.exists():
        sz = p.stat().st_size
        total += sz
        if sz > 300_000:
            big.append((sz, f))
print(f"总体积: {total/1024/1024:.2f} MB")
print("大文件（>300KB）:")
for sz, f in sorted(big, reverse=True)[:12]:
    print(f"   {sz/1024:8.1f} KB  {f}")

print("\n按目录统计:")
tops = {}
for f in files:
    top = f.split("/")[0] if "/" in f else "(根目录)"
    tops[top] = tops.get(top, 0) + 1
for k, v in sorted(tops.items(), key=lambda kv: -kv[1]):
    print(f"   {v:4d}  {k}")

print("\n关键文件是否都在:")
for must in ("README.md", ".gitignore", ".github/workflows/build-macos.yml",
             ".github/workflows/tests.yml", "packaging/macos/xyxbot.spec",
             "packaging/icons/icon.icns", "packaging/icons/source-icon.png",
             "scripts/build_macos.sh", "src/selftest.py",
             "tests/test_portability.py", "MACOS_PORT.md"):
    print(f"   {'✓' if must in files else '✗'} {must}")

print("\n未跟踪（被忽略）的前 15 项:")
ign = run("status", "--porcelain", "--ignored=matching", check=False)
shown = 0
for line in ign.splitlines():
    if line.startswith("!!") and shown < 15:
        print("   " + line[3:])
        shown += 1
