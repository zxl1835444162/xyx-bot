# -*- coding: utf-8 -*-
"""提交工作流修复 → 推送 → 手动触发 build-macos → 轮询到结束。

★ 上一版失败原因：读凭据时没设 GCM_INTERACTIVE=never，
  GCM 想弹 UI，于是 `git credential fill` 卡住直到超时。
  读凭据必须"非交互"，只有 push 才允许交互（万一需要重新授权）。
"""
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


def _env(interactive: bool) -> dict:
    e = dict(os.environ)
    e["PATH"] = str(GIT.parent) + os.pathsep + str(GCM_DIR) + os.pathsep \
        + e.get("PATH", "")
    e["GIT_TERMINAL_PROMPT"] = "0" if not interactive else "1"
    # ★ 非交互时必须显式关掉 GCM 的 UI，否则它会一直等窗口
    e["GCM_INTERACTIVE"] = "always" if interactive else "never"
    return e


def git(*args, quiet=False, interactive=False):
    r = subprocess.run([str(GIT), *args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=_env(interactive))
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if not quiet and out:
        print("   " + out.replace("\n", "\n   ")[:900])
    return r.returncode, out


def get_token() -> str:
    r = subprocess.run([str(GIT), "credential", "fill"],
                       input="protocol=https\nhost=github.com\n\n",
                       capture_output=True, text=True, timeout=20,
                       env=_env(interactive=False))
    for line in (r.stdout or "").splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


TOK = get_token()
print(f"取到令牌: {'是（长度 %d）' % len(TOK) if TOK else '否'}")
if not TOK:
    print("✗ 拿不到令牌，终止")
    sys.exit(2)


def api(path, method="GET", data=None):
    req = urllib.request.Request(
        "https://api.github.com" + path, method=method,
        data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"Bearer {TOK}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "xyx-bot",
                 **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            b = resp.read().decode()
            return resp.status, (json.loads(b) if b.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}


print()
print("=" * 64)
print("  1) 提交并推送工作流修复")
print("=" * 64)
_rc, st = git("status", "--porcelain", quiet=True)
print(st or "   （工作区干净，无需提交）")
if st.strip():
    git("add", "-A")
    git("commit", "-m",
        "修复 build-macos 触发条件：tags 与 paths 不能写在同一个 push 下\n\n"
        "GitHub 的过滤条件是「与」——同时写 tags 和 paths 会变成\n"
        "\"既要是 v* 标签、又要改动这些文件\"，普通分支推送永远不触发。\n"
        "改为 branches+paths 过滤分支推送，发布走 release 事件。\n"
        "并在 test_portability.py 里加了这条坑的回归检查。")
    git("push", "origin", "main", interactive=True)
    print("   ✓ 已推送")

print()
print("=" * 64)
print("  2) 手动触发 build-macos")
print("=" * 64)
st, resp = api("/repos/%s/%s/actions/workflows/build-macos.yml/dispatches"
               % (OWNER, REPO), "POST", {"ref": "main"})
print(f"   dispatch -> HTTP {st}  {'' if st < 300 else resp}")
if st not in (200, 201, 204):
    print("   ✗ 触发失败")
    sys.exit(1)

time.sleep(12)
st, runs = api("/repos/%s/%s/actions/runs?per_page=10" % (OWNER, REPO))
target = next((x for x in runs.get("workflow_runs", [])
               if x["name"] == "build-macos"), None)
if not target:
    print("   还没看到 build-macos 运行记录")
    sys.exit(0)
rid = target["id"]
print(f"   运行: {target['html_url']}")

print()
print("=" * 64)
print("  3) 等待构建（最多约 20 分钟）")
print("=" * 64)
deadline = time.time() + 20 * 60
last = ""
run = target
while time.time() < deadline:
    time.sleep(30)
    st, run = api("/repos/%s/%s/actions/runs/%d" % (OWNER, REPO, rid))
    if st != 200:
        continue
    line = f"{run['status']} / {run.get('conclusion')}"
    if line != last:
        print(f"   [{time.strftime('%H:%M:%S')}] {line}")
        last = line
    if run["status"] == "completed":
        break

print()
print("=" * 64)
print(f"  4) 结果：{run.get('conclusion')}")
print("=" * 64)
if run.get("conclusion") != "success":
    print(f"   看日志：{run['html_url']}")
    st, jobs = api("/repos/%s/%s/actions/runs/%d/jobs" % (OWNER, REPO, rid))
    for j in jobs.get("jobs", []):
        print(f"     job {j['name']}: {j['status']} / {j.get('conclusion')}")
        for s in j.get("steps", []):
            if s.get("conclusion") not in ("success", "skipped", None):
                print(f"        ✗ {s['name']}: {s.get('conclusion')}")
    sys.exit(1)

st, arts = api("/repos/%s/%s/actions/runs/%d/artifacts" % (OWNER, REPO, rid))
print("   ✓ 构建成功！产物：")
for a in arts.get("artifacts", []):
    print(f"     {a['name']:<28s} {a['size_in_bytes']/1024/1024:6.1f} MB  "
          f"id={a['id']}")
print(f"\n   运行页: {run['html_url']}")
print(f"   仓库  : https://github.com/{OWNER}/{REPO}")
