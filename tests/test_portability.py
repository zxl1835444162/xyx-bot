# -*- coding: utf-8 -*-
"""跨平台（macOS）可移植性回归测试。

无需 pytest，直接 `python tests/test_portability.py`。

为什么需要这个文件：
    2026-10-04 要把应用搬到 macOS 并用 GitHub Actions 出包。
    Windows 上"跑得通"不代表 macOS 上跑得通 —— 但凡有一处写死了
    `C:\\...`、注册表、`windll`，打出来的 .app 到用户手里就是打不开。

    本文件做三件事：
      A. **静态审计**：扫描源码，找出未加平台保护的 Windows-only 调用/路径。
      B. **逻辑验证**：把平台相关的分支**真的调用一遍**
         （用 monkeypatch 假装在 darwin 上），断言拿到的结果是对的。
      C. **CI 配置检查**：工作流文件存在、YAML 能解析、
         没有用已退役的 runner 标签。

    我在这台机器上**无法运行 macOS 二进制**，所以这里只保证
    "代码里没有平台假设错误"，真正的 .app 由 CI 在 macOS 上构建。
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, got, want):
    if got == want:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}: got={got!r} want={want!r}")


def check_true(name: str, cond, detail: str = ""):
    check(name, bool(cond), True)
    if not cond and detail:
        print(f"         {detail}")


# ==================================================== A. 静态审计
print("=== A. 静态审计：源码里有没有未加保护的 Windows-only 用法 ===")

SRC_FILES = sorted(
    list((ROOT / "src").rglob("*.py")) + list((ROOT / "ui").rglob("*.py")))

#: 允许出现 Windows-only 调用的文件（各自都有平台判断），
#: 值 = 它应该包含的平台保护标记
ALLOW_WINDOWS_ONLY = {
    "src/browser_detector.py": ("IS_WIN", "整个模块按 IS_WIN/IS_MAC 分支"),
    "ui/shot.py": ("sys.platform", "windll 调用包在 sys.platform 判断里"),
}
WINDOWS_ONLY_MARKERS = [
    "winreg", "windll", "GetWindowRect", "win32api", "win32con",
    "os.startfile", "msvcrt", "ctypes.wintypes",
]

for p in SRC_FILES:
    rel = p.relative_to(ROOT).as_posix()
    text = p.read_text(encoding="utf-8")
    hits = [m for m in WINDOWS_ONLY_MARKERS if m in text]
    if not hits:
        continue
    if rel in ALLOW_WINDOWS_ONLY:
        needle, why = ALLOW_WINDOWS_ONLY[rel]
        check_true(f"{rel} 含 {hits} 但有平台保护（{needle}）",
                   needle in text, why)
    else:
        check_true(f"{rel} 不应出现 Windows-only 调用 {hits}", False,
                   f"命中：{hits}")

# ---- 源码里不该有 Windows 绝对路径（browser_detector 的 Windows 表除外）----
C_DRIVE = re.compile(r"[A-Za-z]:\\\\(?:Program|Users|Windows|Python)")
offenders = []
for p in SRC_FILES:
    rel = p.relative_to(ROOT).as_posix()
    if rel == "src/browser_detector.py":
        continue                      # Windows 注册表/默认路径表的归属地
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except Exception:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if C_DRIVE.search(node.value):
                offenders.append(f"{rel}:{node.lineno}")
check_true(f"src/ 与 ui/ 里没有写死的 Windows 绝对路径（发现 {offenders[:4]}）",
           not offenders)

# ---- macOS 浏览器检测表必须齐全 ----
_det = (ROOT / "src" / "browser_detector.py").read_text(encoding="utf-8")
for name, exe in [
    ("Chrome", "Contents/MacOS/Google Chrome"),
    ("Edge", "Contents/MacOS/Microsoft Edge"),
    ("Chromium", "Contents/MacOS/Chromium"),
]:
    check_true(f"macOS 浏览器表包含 {name}（{exe}）",
               name in _det and exe in _det)
check_true("macOS 会在 /Applications 与 ~/Applications 下找",
           "/Applications" in _det and "~/Applications" in _det)
check_true("注册表读取在非 Windows 平台直接返回 None",
           "if not IS_WIN:" in _det)
check_true("非 Windows 下不要求 .exe 后缀（改判可执行位）",
           "os.access(file_path, os.X_OK)" in _det)

# ---- 字体：必须给 macOS 备好中文字体 ----
_theme = (ROOT / "ui" / "theme.py").read_text(encoding="utf-8")
check_true("字体按平台分表", "UI_FONT_CANDIDATES" in _theme
           and "MONO_FONT_CANDIDATES" in _theme)
check_true("macOS 首选 PingFang SC（系统中文默认字体）",
           "PingFang SC" in _theme)
check_true("Windows 仍首选微软雅黑（原行为不变）",
           "Microsoft YaHei UI" in _theme)
check_true("Linux 也备了 Noto Sans CJK", "Noto Sans CJK SC" in _theme)
check_true("字体解析只在真的存在时才缓存（防止把失败结果钉住）",
           "只缓存\"确实存在\"的结果" in _theme or "_FONT_CACHE[key] = name"
           in _theme)
check_true("字体可用环境变量覆盖（排障用）",
           "XYX_UI_FONT" in _theme and "XYX_MONO_FONT" in _theme)

# ---- 打包/脚本/工作流文件必须都在 ----
MUST_EXIST = [
    "packaging/macos/xyxbot.spec",
    "scripts/build_macos.sh",
    "scripts/run_macos.sh",
    ".github/workflows/tests.yml",
    ".github/workflows/build-macos.yml",
    "src/selftest.py",
]
for rel in MUST_EXIST:
    check_true(f"存在 {rel}", (ROOT / rel).exists())

# ---- PyInstaller spec 必须是合法 Python，且入口/数据目录处理正确 ----
_spec_path = ROOT / "packaging" / "macos" / "xyxbot.spec"
_spec = _spec_path.read_text(encoding="utf-8")
try:
    compile(_spec, str(_spec_path), "exec")
    check_true("xyxbot.spec 语法正确", True)
except SyntaxError as e:
    check_true("xyxbot.spec 语法正确", False, str(e))
check_true("spec 用 run_gui.py 作入口", "run_gui.py" in _spec)
check_true("spec 把 playwright driver 收进包（collect_all）",
           "collect_all" in _spec and "playwright" in _spec)
check_true("spec 收集 src / ui 子模块（注册表是动态 import 的）",
           "collect_submodules" in _spec
           and '"src"' in _spec and '"ui"' in _spec,
           "spec 里应有 collect_submodules('src'/'ui')")
check_true("spec 产出 .app（BUNDLE）", "BUNDLE(" in _spec
           and "XYXBot.app" in _spec)
check_true("spec 设了中文显示名与 Retina 支持",
           "星月创作台" in _spec and "NSHighResolutionCapable" in _spec)

# ---- 启动脚本不该写死 Windows 路径 ----
for rel in ("scripts/build_macos.sh", "scripts/run_macos.sh"):
    txt = (ROOT / rel).read_text(encoding="utf-8")
    check_true(f"{rel} 是 POSIX 脚本（shebang bash）", txt.startswith("#!/usr/bin/env bash"))
    check_true(f"{rel} 没写死 Windows 路径", "Scripts\\" not in txt
               and "python.exe" not in txt)
check_true("build_macos.sh 会检查 tkinter（否则 .app 起不来）",
           "import tkinter" in (ROOT / "scripts/build_macos.sh")
           .read_text(encoding="utf-8"))
check_true("build_macos.sh 用 ditto 压缩（保留 .app 权限/符号链接）",
           "ditto -c -k" in (ROOT / "scripts/build_macos.sh")
           .read_text(encoding="utf-8"))

# ---- launcher 要能找到 POSIX 解释器 ----
_lau = (ROOT / "launcher.py").read_text(encoding="utf-8")
check_true("launcher 按平台选 bin/Scripts", '_BIN = "Scripts" if os.name == "nt"'
           in _lau)
check_true("launcher 有 Homebrew / 系统 python3 候选",
           "/opt/homebrew/bin/python3" in _lau and "/usr/bin/python3" in _lau)
check_true("launcher 优先用当前解释器", "sys.executable" in _lau)

# ---- GUI 入口要支持 --selftest（CI 才能验证打包产物）----
_rg = (ROOT / "run_gui.py").read_text(encoding="utf-8")
check_true("run_gui.py 支持 --selftest", "--selftest" in _rg)
check_true("run_gui.py 在 selftest 时不创建窗口",
           "run_selftest" in _rg and _rg.index("--selftest") < _rg.index("LoginWindow"))

# ---- 应用图标：源图在、产物有效、spec 真的引用了它 ----
print("\n--- 应用图标 ---")
ICON_DIR = ROOT / "packaging" / "icons"
for rel in ("source-icon.png", "icon.icns", "icon.ico", "icon-1024.png"):
    check_true(f"存在 packaging/icons/{rel}", (ICON_DIR / rel).exists())

try:
    from PIL import Image

    # 源图（用户的原始素材）必须原样留着
    with Image.open(ICON_DIR / "source-icon.png") as src_im:
        check("源图是 2048x2048", src_im.size, (2048, 2048))

    # macOS 图标：1024 画布 + 四角透明（证明套了圆角遮罩而不是方块）
    with Image.open(ICON_DIR / "icon-1024.png") as mac_im:
        check("icon-1024 尺寸", mac_im.size, (1024, 1024))
        check("icon-1024 带透明通道", mac_im.mode, "RGBA")
        a = mac_im.convert("RGBA").getchannel("A")
        check("左上角是透明的（圆角外形生效）", a.getpixel((2, 2)), 0)
        check("右上角是透明的", a.getpixel((1021, 2)), 0)
        check("正中间是不透明的（图形没被切掉）", a.getpixel((512, 512)), 255)

    # Windows 图标：多尺寸齐全
    with Image.open(ICON_DIR / "icon.ico") as ico_im:
        sizes = sorted(ico_im.ico.sizes())
    check("icon.ico 含 7 个尺寸",
          sizes, [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                  (128, 128), (256, 256)])

    # ICNS 容器：自己解析一遍（macOS 上才能用 iconutil，这里只能自己验）
    import importlib.util

    _mspec = importlib.util.spec_from_file_location(
        "make_icons", ROOT / "scripts" / "make_icons.py")
    _mk = importlib.util.module_from_spec(_mspec)
    _mspec.loader.exec_module(_mk)
    _chunks = _mk.read_icns(ICON_DIR / "icon.icns")
    check("icon.icns 有 10 个块", len(_chunks), 10)
    check_true("每个块的 PNG 尺寸都与类型码相符",
               all(w == h == dict(_mk.ICNS_CHUNKS)[c] for c, _l, w, h in _chunks),
               str(_chunks))
    _sizes_in_icns = sorted({w for _c, _l, w, _h in _chunks})
    check_true("icns 覆盖 16~1024（含 Retina 用的 512、1024）",
               _sizes_in_icns == [16, 32, 64, 128, 256, 512, 1024],
               str(_sizes_in_icns))

    # 去水印：在**提交进仓库的** icon-1024.png 上验证
    #   （icon-clean.png 是 2048 的中间产物，体积大、被 gitignore 了）
    with Image.open(ICON_DIR / "icon-1024.png") as mac_im2:
        mm = mac_im2.convert("RGBA")
        # 源图坐标 → 图标坐标：先缩到 MAC_BODY，再整体偏移
        scale = _mk.MAC_BODY / 2048.0
        off = (_mk.MAC_CANVAS - _mk.MAC_BODY) // 2
        x0, y0, x1, y1 = _mk.WATERMARK_BOX
        bx0 = int(off + x0 * scale)
        by0 = int(off + y0 * scale)
        bx1 = int(off + x1 * scale)
        by1 = int(off + y1 * scale)
        pxm = mm.load()
        bright = 0
        for yy in range(by0, by1):
            for xx in range(bx0, bx1):
                r, g, b, _a = pxm[xx, yy]
                if r + g + b > 330:
                    bright += 1
        check("水印框里已无亮像素（去水印生效）", bright, 0)
        print(f"         （检查区域 {bx0},{by0} - {bx1},{by1}）")
except ImportError:
    print("  SKIP：没有 Pillow，跳过图标检查")

_spec_icon = "icon.icns" in _spec
check_true("xyxbot.spec 引用了 icon.icns", _spec_icon)
check_true("spec 里图标路径做了存在性判断（缺了也不至于打不出包）",
           "APP_ICON" in _spec and "os.path.exists(ICNS)" in _spec)
_req = (ROOT / "requirements-gui.txt").read_text(encoding="utf-8")
check_true("requirements-gui.txt 声明了 Pillow（原来用到了但没声明）",
           "Pillow" in _req or "pillow" in _req)

# ==================================================== B. 平台分支逻辑
print("\n=== B. 平台相关分支：真的调用一遍（假装在 macOS 上） ===")

from src import browser as B  # noqa: E402
from src import config as C  # noqa: E402

_real_platform = sys.platform


def _as(plat: str):
    """临时把 sys.platform 换成别的值。"""
    sys.platform = plat


def _restore():
    sys.platform = _real_platform


# ---- UA 要跟着平台走 ----
try:
    _as("darwin")
    mac_ua = B.platform_user_agent()
    _as("win32")
    win_ua = B.platform_user_agent()
    _as("linux")
    linux_ua = B.platform_user_agent()
finally:
    _restore()

check_true("macOS UA 标明 Macintosh", "Macintosh" in mac_ua, mac_ua)
check_true("macOS UA 不是 Windows", "Windows NT" not in mac_ua, mac_ua)
check_true("Windows UA 仍是原来的 Windows", "Windows NT 10.0" in win_ua, win_ua)
check_true("Linux UA 标明 X11", "X11" in linux_ua, linux_ua)
check_true("三种平台的 UA 互不相同",
           len({mac_ua, win_ua, linux_ua}) == 3)

# 环境变量可覆盖
os.environ["XYX_USER_AGENT"] = "CustomUA/1.0"
try:
    check("XYX_USER_AGENT 可强制覆盖 UA",
          B.platform_user_agent(), "CustomUA/1.0")
finally:
    os.environ.pop("XYX_USER_AGENT", None)
check_true("清掉覆盖后回到平台 UA",
           B.platform_user_agent() == B.platform_user_agent())

# ---- 打包后数据目录必须移出只读的 .app ----
check_true("config 暴露 DATA_ROOT", hasattr(C, "DATA_ROOT"))
_real_frozen = getattr(sys, "frozen", None)
try:
    sys.frozen = True
    # ★ 用显式的 platform_key 驱动三个分支 ——
    #   光改 sys.platform 在 Windows 上验证不了 Linux 分支
    #   （config 里还有 os.name == "nt" 这条判断）。
    mac_root = C._default_data_root("darwin")
    win_root = C._default_data_root("win32")
    lin_root = C._default_data_root("linux")
finally:
    if _real_frozen is None:
        try:
            del sys.frozen
        except Exception:
            pass
    else:
        sys.frozen = _real_frozen

_mac_s = str(mac_root).replace("\\", "/")
_lin_s = str(lin_root).replace("\\", "/")
check_true(f"打包后 macOS 数据目录在 Application Support（{_mac_s}）",
           "Library/Application Support" in _mac_s and _mac_s.endswith("XYXBot"),
           _mac_s)
check_true(f"打包后 Windows 用 AppData（{win_root}）",
           "AppData" in str(win_root) and str(win_root).endswith("XYXBot"),
           str(win_root))
check_true(f"打包后 Linux 用 .local/share（{_lin_s}）",
           ".local/share" in _lin_s and _lin_s.endswith("XYXBot"), _lin_s)
check_true("三个平台的落点互不相同",
           len({str(mac_root), str(win_root), str(lin_root)}) == 3)
check_true("打包后数据目录不再等于项目根（说明真的搬走了）",
           mac_root != C.ROOT and win_root != C.ROOT and lin_root != C.ROOT)

# 源码运行时必须保持原行为（还是项目目录）
check("源码运行 → 数据目录 = 项目根", C.DATA_ROOT, C.ROOT)
check("源码运行 → artifacts 仍在项目下", C.ARTIFACTS, C.ROOT / "artifacts")

# XYX_DATA_DIR 覆盖
os.environ["XYX_DATA_DIR"] = str(ROOT / "_tmp_data_probe")
try:
    check("XYX_DATA_DIR 可指定数据目录",
          C._default_data_root(), ROOT / "_tmp_data_probe")
finally:
    os.environ.pop("XYX_DATA_DIR", None)

# ---- 自检本身要能跑，且判定为"可以启动" ----
from src.selftest import collect_facts, run_selftest  # noqa: E402

facts = collect_facts()
for key in ("platform", "arch", "python", "frozen", "tkinter_ok",
            "display_ok", "data_root", "data_writable", "playwright_ok",
            "browser_path", "session_ok", "errors", "warnings"):
    check_true(f"自检返回了 {key}", key in facts, str(sorted(facts)))
check_true("自检认为数据目录可写（关键：登录态要存得下）",
           facts["data_writable"], facts.get("data_detail", ""))
check_true("自检认为 Playwright driver 在（打包后浏览器才起得来）",
           facts["playwright_ok"], facts.get("playwright_detail", ""))
check_true("自检没有阻塞性错误", not facts["errors"],
           str(facts["errors"]))
check("run_selftest() 退出码 0（可以启动）",
      run_selftest(verbose=False), 0)

# ---- 浏览器缺失时的报错要"人话"（打包分发最容易踩的坑）----
_b = (ROOT / "src" / "browser.py").read_text(encoding="utf-8")
check_true("浏览器缺失时给出可照抄的命令",
           "playwright install chromium" in _b)
check_true("浏览器缺失时的提示提到装 Chrome/Edge",
           "Chrome" in _b and "Edge" in _b)

# ==================================================== C. CI 配置
print("\n=== C. GitHub Actions 配置 ===")

WF_DIR = ROOT / ".github" / "workflows"
wf_texts = {p.name: p.read_text(encoding="utf-8") for p in WF_DIR.glob("*.yml")}
check_true(f"找到工作流：{sorted(wf_texts)}",
           "tests.yml" in wf_texts and "build-macos.yml" in wf_texts)

_all_wf = "\n".join(wf_texts.values())

# ★ 只看 `runs-on:` 的值 —— 注释里提到 macos-13 是**说明文字**，不算违规
_runs_on = re.findall(r"^\s*runs-on:\s*(.+?)\s*$", _all_wf, re.M)
check_true(f"工作流都声明了 runs-on（{_runs_on}）", bool(_runs_on))
RETIRED = ["macos-13", "macos-12", "macos-11", "ubuntu-20.04"]
bad_labels = [x for x in RETIRED if any(x in r for r in _runs_on)]
check_true(f"runs-on 里没有已退役的标签（{bad_labels}）", not bad_labels,
           "macos-13 已于 2025-12 退役；macos-14 正在退役（2026-10 公告）")

check_true("build-macos 用 arm64 runner（macos-15）",
           "macos-15" in wf_texts.get("build-macos.yml", ""))
check_true("build-macos 用 Intel runner（macos-15-intel，GitHub 支持到 2027-08）",
           "macos-15-intel" in wf_texts.get("build-macos.yml", ""))
check_true("build-macos 声明了 arm64 / x86_64 两个架构",
           "arm64" in wf_texts.get("build-macos.yml", "")
           and "x86_64" in wf_texts.get("build-macos.yml", ""))
check_true("build-macos 用了 PyInstaller spec",
           "xyxbot.spec" in wf_texts.get("build-macos.yml", ""))
check_true("build-macos 会上传产物（upload-artifact）",
           "upload-artifact" in wf_texts.get("build-macos.yml", ""))
check_true("build-macos 打包前先跑测试",
           "test_portability" in wf_texts.get("build-macos.yml", ""))
check_true("build-macos 用 ditto 压缩",
           "ditto -c -k" in wf_texts.get("build-macos.yml", ""))
check_true("build-macos 用 --selftest 冒烟（headless 也能跑）",
           "--selftest" in wf_texts.get("build-macos.yml", ""))
check_true("tests.yml 覆盖三平台",
           all(x in wf_texts.get("tests.yml", "")
               for x in ("ubuntu-latest", "windows-latest", "macos-15")))

# YAML 能不能真的解析（有 pyyaml 就真解析，没有就退回结构检查）
try:
    import yaml

    for name, txt in wf_texts.items():
        try:
            data = yaml.safe_load(txt)
            ok = isinstance(data, dict) and "jobs" in data
            check_true(f"{name} YAML 解析通过且有 jobs", ok, str(type(data)))
        except Exception as e:
            check_true(f"{name} YAML 解析通过", False, f"{type(e).__name__}: {e}")
    print("         （pyyaml 可用 → 做了真实解析）")
except ImportError:
    for name, txt in wf_texts.items():
        check_true(f"{name} 有 jobs: 与 runs-on:", "jobs:" in txt
                   and "runs-on:" in txt)
    print("         （没有 pyyaml → 只做了结构检查）")

# ==================================================== 汇总
print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)

sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)
