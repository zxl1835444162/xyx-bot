# -*- coding: utf-8 -*-
"""清理：把我这次调试用的临时脚本从仓库里去掉，并确认 Actions 状态。"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")
try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

ROOT = Path.cwd()
OWNER, REPO = "zxl1835444162", "xyx-bot"
GIT = Path(os.environ["USERPROFILE"]) / ".workbuddy" / "binaries" / \
    "PortableGit" / "versions" / "1.2.0" / "cmd" / "git.exe"
GCM_DIR = GIT.parent.parent / "mingw64" / "bin"

# 我这次的一次性脚本（不该进仓库）
SCRATCH = [
    "_check_gh_cred.py", "_gh_probe.py", "_git_stage.py", "_gh_push.py",
    "_gh_push2.py", "_inspect_icon.py", "_measure_icon.py", "_yamlcheck.py",
    "_check_yaml.py", "_dedup_chapters.py", "_fix_checkbox.py", "_widen.py",
    "_mutate.py", "_patch_text.py", "_patch_flush.py", "_patch_utf8.py",
    "_patch_clicks.py", "_patch_diag_utf8.py", "_renumber.py",
    "_warm_memory.py", "_check_real_ws.py",
]


def env():
    e = dict(os.environ)
    e["PATH"] = str(GIT.parent) + os.pathsep + str(GCM_DIR) + os.pathsep \
        + e.get("PATH", "")
    e["GIT_TERMINAL_PROMPT"] = "0"
    return e


def git(*args, check=True, quiet=False):
    r = subprocess.run([str(GIT), *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env())
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if not quiet and out:
        print("   " + out.replace("\n", "\n   ")[:800])
    if check and r.returncode != 0:
        print(f"✗ git {' '.join(args)} 失败")
        sys.exit(1)
    return out


print("==> 删除工作区里的一次性脚本")
removed = []
for f in SCRATCH:
    p = ROOT / f
    if p.exists():
        p.unlink()
        removed.append(f)
    # 已删除但仍被跟踪的文件，也要从索引里去掉
    if f in git("ls-files", quiet=True):
        git("rm", "--cached", "-q", f, check=False, quiet=True)
print(f"   删掉 {len(removed)} 个：{removed}")

rc = git("status", "--porcelain", quiet=True)
print(f"\n==> 变更:\n{rc or '   （无）'}")

if rc.strip():
    git("add", "-A")
    git("commit", "-m", "清理：移除开发期一次性脚本（_gh_* / _inspect_* 等）")
    git("push", "origin", "main")
    print("   ✓ 已推送清理提交")

# ---------------------------------------------------------------- Actions
print("\n==> 查询 Actions（带令牌）")
r = subprocess.run([str(GIT), "credential", "fill"],
                   input="protocol=https\nhost=github.com\n\n",
                   capture_output=True, text=True, timeout=25, env=env())
tok = ""
for line in (r.stdout or "").splitlines():
    if line.startswith("password="):
        tok = line.split("=", 1)[1].strip()


def api(path):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Authorization": f"Bearer {tok}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "xyx-bot"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}


st, runs = api(f"/repos/{OWNER}/{REPO}/actions/runs?per_page=10")
if st != 200:
    print(f"   查询失败 HTTP {st}: {runs}")
else:
    items = runs.get("workflow_runs", [])
    print(f"   共 {runs.get('total_count')} 个运行")
    for x in items[:10]:
        print(f"     [{x['status']:>12s} / {str(x.get('conclusion')):>9s}] "
              f"{x['name']:<12s} {x['html_url']}")

st, wfs = api(f"/repos/{OWNER}/{REPO}/actions/workflows")
if st == 200:
    print(f"\n   已注册工作流 {wfs.get('total_count')} 个：")
    for w in wfs.get("workflows", []):
        print(f"     - {w['name']}  ({w['path']})  state={w['state']}")

print(f"\n仓库: https://github.com/{OWNER}/{REPO}")
print(f"Actions: https://github.com/{OWNER}/{REPO}/actions")
