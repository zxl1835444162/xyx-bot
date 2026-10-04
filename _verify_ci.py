# -*- coding: utf-8 -*-
"""推送 → 确认两个工作流都能**快速结束**（不再卡死）→ 抓 macOS 的界面冒烟输出。"""
import json
import os
import re
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
SCRATCH = ["_watch2.py", "_where_stuck.py", "_look.py", "_look_ubuntu.py",
           "_push_and_watch.py", "_final.py", "_finish.py", "_finish2.py",
           "_logs2.py", "_build_now.py", "_retry_build.py", "_gh_logs.py",
           "_download_artifacts.py", "_verify_zips.py", "_verify_final.py",
           "_cleanup_and_check.py", "_check_ci_gui.py", "_last_build.json"]


def _env(interactive=False):
    e = dict(os.environ)
    e["PATH"] = str(GIT.parent) + os.pathsep + str(GCM_DIR) + os.pathsep + \
        e.get("PATH", "")
    e["GIT_TERMINAL_PROMPT"] = "1" if interactive else "0"
    e["GCM_INTERACTIVE"] = "always" if interactive else "never"
    return e


def git(*a, quiet=False, interactive=False):
    r = subprocess.run([str(GIT), *a], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=_env(interactive))
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    if not quiet and out:
        print("   " + out.replace("\n", "\n   ")[:900])
    return r.returncode, out


def token():
    for _ in range(4):
        try:
            r = subprocess.run([str(GIT), "credential", "fill"],
                               input="protocol=https\nhost=github.com\n\n",
                               capture_output=True, text=True, timeout=60,
                               env=_env())
            t = next((x.split("=", 1)[1].strip()
                      for x in (r.stdout or "").splitlines()
                      if x.startswith("password=")), "")
            if t:
                return t
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2)
    return ""


TOK = token()
if not TOK:
    print("✗ 没令牌")
    sys.exit(2)


class _Strip(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            for store in (new.headers, new.unredirected_hdrs):
                for k in [k for k in list(store) if k.lower() == "authorization"]:
                    del store[k]
        return new


OPENER = urllib.request.build_opener(_Strip)


def api(path, method="GET", data=None, raw=False):
    req = urllib.request.Request(
        "https://api.github.com" + path, method=method,
        data=json.dumps(data).encode() if data else None,
        headers={"Authorization": f"Bearer {TOK}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "xyx-bot",
                 **({"Content-Type": "application/json"} if data else {})})
    try:
        with OPENER.open(req, timeout=90) as resp:
            b = resp.read()
            return resp.status, (b.decode("utf-8", "replace") if raw
                                 else json.loads(b.decode() or "{}"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


print("=" * 70)
print("  1) 本地全部测试")
print("=" * 70)
PY = str(ROOT / ".venv312" / "Scripts" / "python.exe")
tot = 0
for t in ("test_fixes", "test_gui_pages", "test_waiting", "test_runplan",
          "test_memory", "test_portability", "test_login_flow"):
    r = subprocess.run([PY, f"tests/{t}.py"], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "XYX_NO_DIALOG": "1"})
    n = next((ln.strip() for ln in (r.stdout or "").splitlines()
              if "通过" in ln and "项" in ln), "")
    print(f"   {'✓' if r.returncode == 0 else '✗'} {t:<18s} {n}")
    if r.returncode != 0:
        print((r.stdout or "")[-1200:])
    m = re.search(r"通过 (\d+) 项", n)
    if m:
        tot += int(m.group(1))
print(f"   合计 {tot} 项")

print()
print("=" * 70)
print("  2) 提交推送")
print("=" * 70)
for f in SCRATCH:
    p = ROOT / f
    if p.exists():
        p.unlink()
for p in ROOT.glob("_log_*.txt"):
    p.unlink()
_rc, tracked = git("ls-files", quiet=True)
to_rm = [f for f in SCRATCH + ["_log_tests.yml_111382903582.txt"]
         if f in set(tracked.splitlines())]
if to_rm:
    git("rm", "--cached", "-q", *to_rm)
git("add", "-A")
_rc, st = git("status", "--porcelain", quiet=True)
print(f"   {st or '（无变更）'}")
if st.strip():
    git("commit", "-m",
        "窗口探测改为「用户本机默认开、CI 自动关」+ 加超时兜底\n\n"
        "实测踩坑：窗口显示探测要跑真实 mainloop 并映射可见窗口，在 GitHub 的\n"
        "macOS runner 上会**永久卡住** —— tests 的 macos job 与 build-macos 的\n"
        "两个 job 全都卡在包内自检那一步，跑了 8 分钟以上只能手动取消。\n"
        "那种 runner 虽然 tk.Tk() 能建（自检报「图形会话可用」），但没有真正的\n"
        "登录会话去显示窗口，after 定时器永不触发、quit() 永远等不到。\n\n"
        "- _window_probe_wanted()：XYX_SELFTEST_WINDOW 显式开关 >\n"
        "  检测到 CI 环境变量则关 > 否则（用户本机）开\n"
        "- 默认冒烟恢复 win.withdraw()，不映射窗口 → 任何环境都安全\n"
        "- 「登录窗→销毁→主窗」在无探测时只做构造，异常照样抓得到\n"
        "- 两个工作流都加 timeout-minutes（20/15），防死等烧额度\n"
        "- 删掉误提交的 job 日志；.gitignore 加 _log_*.txt")
    git("push", "origin", "main", interactive=True)

print()
print("=" * 70)
print("  3) 触发 build-macos，观察是否快速结束")
print("=" * 70)
st, _ = api(f"/repos/{OWNER}/{REPO}/actions/workflows/build-macos.yml/"
            f"dispatches", "POST", {"ref": "main"})
time.sleep(15)
want = {}
for wf in ("tests.yml", "build-macos.yml"):
    st, runs = api(f"/repos/{OWNER}/{REPO}/actions/workflows/{wf}/runs"
                   f"?per_page=3")
    it = runs.get("workflow_runs", [])
    if it:
        want[wf] = (it[0]["id"], time.time())
        print(f"   {wf} -> run {it[0]['id']}")

deadline = time.time() + 20 * 60
done = {}
while time.time() < deadline and len(done) < len(want):
    time.sleep(30)
    for wf, (rid, t0) in want.items():
        if wf in done:
            continue
        st, run = api(f"/repos/{OWNER}/{REPO}/actions/runs/{rid}")
        if st != 200:
            continue
        if run["status"] == "completed":
            mins = (time.time() - t0) / 60
            done[wf] = (run.get("conclusion"), mins)
            print(f"   [{time.strftime('%H:%M:%S')}] {wf}: "
                  f"{run.get('conclusion')}  （约 {mins:.1f} 分钟）")
        else:
            mins = (time.time() - t0) / 60
            print(f"   [{time.strftime('%H:%M:%S')}] {wf}: {run['status']} "
                  f"({mins:.1f} 分钟)")

print()
print("=" * 70)
print("  4) macOS 的界面冒烟输出")
print("=" * 70)
for wf, (rid, _t) in want.items():
    st, jobs = api(f"/repos/{OWNER}/{REPO}/actions/runs/{rid}/jobs")
    for j in jobs.get("jobs", []):
        nm = j["name"].lower()
        if "macos" not in nm and "arm64" not in nm and "x86" not in nm:
            continue
        print(f"\n--- {wf} / {j['name']}: {j['status']}/{j.get('conclusion')} ---")
        if j.get("conclusion") != "success":
            for s in j.get("steps", []):
                if s.get("conclusion") not in ("success", "skipped", None):
                    print(f"    ✗ {s['name']} ({s.get('conclusion')})")
        st2, log = api(f"/repos/{OWNER}/{REPO}/actions/jobs/{j['id']}/logs",
                       raw=True)
        if st2 != 200 or not isinstance(log, str):
            print(f"    日志拿不到 {st2}")
            continue
        out = [ln.split("Z ", 1)[-1].rstrip() if "Z " in ln else ln.rstrip()
               for ln in log.splitlines()]
        show, n = False, 0
        for s in out:
            if "界面构造冒烟" in s:
                show = True
            if show:
                print("    " + s[:185])
                n += 1
                if n > 16:
                    show = False
