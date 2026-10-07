# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把本项目打成 macOS 的 `XYXBot.app`。

用法（在 macOS 上）：
    .venv-mac/bin/pyinstaller --clean --noconfirm packaging/macos/xyxbot.spec
产物：
    dist/XYXBot.app

★ 几个必须知道的点
==================

1) **浏览器内核不打包**
   Playwright 的 Chromium 约 150MB+，而且它下载在
   `~/Library/Caches/ms-playwright`，**不适合塞进 .app**。
   所以：
     * 优先用系统已装的 Chrome / Edge（`src/browser_detector.py` 会在
       /Applications 下找）—— 这也是**反风控更好**的选择（真实浏览器指纹）；
     * 都没有时，程序会给出明确提示，让用户执行
       `python -m playwright install chromium`。
   但 Playwright 的 **driver**（"playwright" 那个 node 可执行文件）必须打进去，
   否则连启动浏览器都做不到 —— 下面用 `collect_all("playwright")` 处理。

2) **数据目录不在 .app 里**
   .app 是只读的（签名/公证后尤其严格）。所有"记忆"
   （登录态 / 工作区配置 / 细纲 / 截图 / 日志）都由
   `src/config.py` 落到：
       ~/Library/Application Support/XYXBot/artifacts/
   见 config.py 里的 `_default_data_root()`。

3) **未签名的 .app，用户第一次打开会被 Gatekeeper 拦**
   这在文档 MACOS_PORT.md 里有说明（右键打开 / xattr -cr）。
   要彻底解决需要 Apple 开发者账号做签名+公证。
"""

import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH = <repo>/packaging/macos  →  仓库根目录是它的上两级
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# ★ 应用图标（由 scripts/make_icons.py 从 packaging/icons/source-icon.png 生成）
#   缺了也不至于打不出包，只是图标会是默认的，所以这里用存在性判断兜一下。
ICNS = os.path.join(ROOT, "packaging", "icons", "icon.icns")
APP_ICON = ICNS if os.path.exists(ICNS) else None

datas = []
binaries = []
hiddenimports = [
    "tkinter",
    "tkinter.font",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    "PIL",
    "PIL.ImageGrab",
]

# ---- Playwright：连 driver 一起收进来（浏览器内核不收）----
for _pkg in ("playwright",):
    d, b, h = collect_all(_pkg)
    datas += d
    binaries += b
    hiddenimports += h

# ---- 本项目自己的包：注册表/适配器是动态 import 的，必须显式收集 ----
# 界面包在业务包内（xyxbot/ui），collect_submodules 会把子包一起收进来
hiddenimports += collect_submodules("xyxbot")

a = Analysis(
    [os.path.join(ROOT, "run_gui.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # 明确排除用不到的重型库，避免 .app 无谓变大
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "pytest", "IPython", "notebook",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XYXBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI 程序：不要弹终端窗口
    disable_windowed_traceback=False,
    argv_emulation=False,   # 需要 pyobjc，我们不需要文件拖拽
    target_arch=None,       # 跟随构建机的架构（arm64 或 x86_64）
    icon=APP_ICON,
    codesign_identity=None, # 想签名就设环境变量后在这里传入
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="XYXBot",
)

app = BUNDLE(
    coll,
    name="XYXBot.app",
    icon=APP_ICON,          # ★ 应用图标（.icns）
    bundle_identifier="com.zhaoshijituan.xyxbot",
    info_plist={
        # Dock / 关于本机里显示的中文名
        "CFBundleName": "XYXBot",
        "CFBundleDisplayName": "星月创作台",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "CFBundlePackageType": "APPL",
        "NSHumanReadableCopyright": "赵氏集团",
        # Retina 支持
        "NSHighResolutionCapable": True,
        # 跟随系统浅色/深色（我们的界面自己就是深色，不跟系统走也行）
        "NSRequiresAquaSystemAppearance": False,
        "LSMinimumSystemVersion": "11.0",
        # 让程序能发起网络请求（Playwright 要访问站点）
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
        "LSApplicationCategoryType": "public.app-category.productivity",
    },
)
