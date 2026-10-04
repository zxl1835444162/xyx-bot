# -*- coding: utf-8 -*-
"""用已存的 GitHub 凭据查一下：令牌是否有效、有哪些权限、额度够不够。

★ 全程不打印令牌本身。
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")
try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

GIT = Path(os.environ["USERPROFILE"]) / ".workbuddy" / "binaries" / \
    "PortableGit" / "versions" / "1.2.0" / "cmd" / "git.exe"
GCM_DIR = GIT.parent.parent / "mingw64" / "bin"

env = dict(os.environ)
env.update({"GCM_INTERACTIVE": "never", "GIT_TERMINAL_PROMPT": "0",
            "PATH": str(GIT.parent) + os.pathsep + str(GCM_DIR) + os.pathsep
                    + env.get("PATH", "")})

r = subprocess.run([str(GIT), "credential", "fill"],
                   input="protocol=https\nhost=github.com\n\n",
                   capture_output=True, text=True, timeout=25, env=env)
creds = {}
for line in (r.stdout or "").splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip()
tok = creds.get("password") or ""
if not tok:
    print("✗ 拿不到令牌")
    sys.exit(2)
print(f"令牌类型猜测: {'ghp_ 经典 PAT' if tok.startswith('ghp_') else ('github_pat_ 细粒度' if tok.startswith('github_pat_') else '其它/长度 ' + str(len(tok)))}")


def api(path, method="GET", data=None):
    req = urllib.request.Request(
        "https://api.github.com" + path, method=method,
        data=json.dumps(data).encode() if data else None,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "xyx-bot-setup",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Content-Type": "application/json"} if data else {}),
        })
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = resp.read().decode()
        return resp.status, (json.loads(body) if body.strip() else {}), dict(resp.headers)


try:
    st, user, hdr = api("/user")
except Exception as e:
    print(f"✗ /user 调用失败：{type(e).__name__}: {e}")
    sys.exit(3)

print(f"\n/user -> HTTP {st}")
print(f"  登录名 : {user.get('login')}")
print(f"  名字   : {user.get('name')}")
print(f"  id     : {user.get('id')}")
print(f"  noreply 邮箱建议: {user.get('id')}+{user.get('login')}@users.noreply.github.com")

scopes = hdr.get("X-OAuth-Scopes") or hdr.get("x-oauth-scopes") or ""
print(f"\n令牌权限范围 (X-OAuth-Scopes): {scopes or '（细粒度令牌不返回这个头）'}")

can_repo = ("repo" in scopes) or (not scopes)   # 细粒度令牌看不到 scopes
print(f"能否建仓库 : {'✓ 应该可以' if can_repo else '✗ 权限不足（缺 repo）'}")

st2, rl, _ = api("/rate_limit")
core = rl.get("resources", {}).get("core", {})
print(f"\nAPI 额度 : {core.get('remaining')}/{core.get('limit')}  "
      f"(已用 {core.get('used')})")

st3, repos, _ = api("/user/repos?per_page=100&sort=updated")
print(f"\n你现有仓库 {len(repos)} 个，最近 5 个：")
for x in repos[:5]:
    print(f"   {'private' if x['private'] else 'public '}  "
          f"{x['full_name']}  ({x.get('default_branch')})")

print("\n建议的仓库名: xyx-bot")
name_taken = any(x["name"] == "xyx-bot" for x in repos)
print(f"  「xyx-bot」是否已存在: {name_taken}")
