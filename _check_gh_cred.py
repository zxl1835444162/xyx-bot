# -*- coding: utf-8 -*-
"""检查是否**已经**有可用的 GitHub 凭据（不打印任何密钥）。

只用来决定：是"直接就能推"，还是"需要弹出浏览器让用户授权一次"。
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

GIT = Path(os.environ["USERPROFILE"]) / ".workbuddy" / "binaries" / \
    "PortableGit" / "versions" / "1.2.0" / "cmd" / "git.exe"
GCM = GIT.parent.parent / "mingw64" / "bin" / "git-credential-manager.exe"

print(f"git : {GIT}  存在={GIT.exists()}")
print(f"gcm : {GCM}  存在={GCM.exists()}")

env = dict(os.environ)
env.update({
    "GCM_INTERACTIVE": "never",       # 不要弹 UI，只查已存的
    "GIT_TERMINAL_PROMPT": "0",       # 不要问终端
    "GCM_PROVIDER": "github",
    # 让 GCM 用我们指定的凭据存储（默认就是它）
    "PATH": str(GIT.parent) + os.pathsep + str(GCM.parent) + os.pathsep
            + env.get("PATH", ""),
})

inp = "protocol=https\nhost=github.com\n\n"
try:
    r = subprocess.run([str(GIT), "credential", "fill"], input=inp,
                       capture_output=True, text=True, timeout=25, env=env)
except Exception as e:
    print(f"调用失败: {type(e).__name__}: {e}")
    sys.exit(3)

out = r.stdout or ""
fields = {}
for line in out.splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        fields[k.strip()] = v.strip()

print(f"\n退出码: {r.returncode}")
print(f"stderr : {(r.stderr or '').strip()[:300]}")
print(f"是否有 username: {bool(fields.get('username'))}")
print(f"  username      : {fields.get('username')!r}")
print(f"是否有 password(令牌): {bool(fields.get('password'))}")
if fields.get("password"):
    print(f"  password 长度 : {len(fields['password'])}  （不打印内容）")
print(f"其它字段      : {[k for k in fields if k not in ('username','password')]}")

print()
if fields.get("password"):
    print("结论：★ 已经有可用的 GitHub 凭据 → 可以直接建仓库并推送，不需要再授权")
    sys.exit(0)
print("结论：没有现成凭据 → 需要触发一次 GitHub 授权（会弹浏览器）")
sys.exit(1)
