"""浏览器启动与管理（移植自 novel_publisher/browser.py，做了可用性增强）。

支持三种模式：
  1. 普通启动：Playwright 拉起指定浏览器，注入登录态 storage_state
  2. 持久化启动：user_data_dir 模式，登录态更完整（含 IndexedDB）
  3. CDP 接管：连上你手动打开、带 --remote-debugging-port 的浏览器，
     复用你真实的登录状态和浏览器指纹 —— 对付风控最有效

关于登录态（★ 免登录的关键）
    走「普通启动」或「持久化启动」时，都会自动找 artifacts/storage/state.json：
      - 文件在 → 注入进去，浏览器一打开就是已登录
      - 文件不在 → 全新会话，需登录一次（登录后由 login.py 负责落盘）

与参考项目的差异：
  - 登录态缺失不再抛 FileNotFoundError，按「未登录」处理
  - 增加 persistent 模式（user_data_dir），登录态比 storage_state 更完整
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import Browser as PWBrowser
from playwright.sync_api import BrowserContext
from playwright.sync_api import sync_playwright

from . import config as C
from . import session as S

# 反自动化检测的核心参数，原样移植
BROWSER_ARGS = [
    "--disable-popup-blocking",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
]

BROWSER_IGNORE_ARGS = ["--enable-automation"]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ★★ 跨平台 UA（2026-10-04 转 macOS）
#   原来写死 Windows UA。在 mac 上跑着真 Chrome 却自称 Windows，
#   **UA 和真实内核不一致本身就是一条指纹信号** —— 风控比对平台特征时容易命中。
#   在自己平台上跑，就报自己平台的 UA 最自然。
_WIN_UA = DEFAULT_USER_AGENT
_MAC_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/120.0.0.0 Safari/537.36")
_LINUX_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def platform_user_agent() -> str:
    """按运行平台返回 UA；可用 `XYX_USER_AGENT` 强制覆盖（排查用）。"""
    override = (os.getenv("XYX_USER_AGENT") or "").strip()
    if override:
        return override
    if sys.platform == "darwin":
        return _MAC_UA
    if sys.platform.startswith("win"):
        return _WIN_UA
    return _LINUX_UA


# 实际用的 UA（模块级，方便既有调用点不变）
DEFAULT_USER_AGENT = platform_user_agent()

# 去掉 navigator.webdriver 痕迹
STEALTH_SCRIPT = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "window.chrome={runtime:{}};"
    "Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh']});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
)


def resolve_browser_path(explicit: str | None = None) -> str | None:
    """确定用哪个浏览器可执行文件。

    优先级：显式指定 > 自动检测本机 Edge/Chrome > None（回退自带 Chromium）
    用本机 Edge/Chrome 的好处：无需下载内核，且浏览器指纹真实，风控更友好。
    """
    if explicit:
        return explicit

    from . import config as C

    if not C.AUTO_DETECT_BROWSER:
        return None

    try:
        from .browser_detector import BrowserDetector

        path = BrowserDetector.get_recommended_browser()
        if path:
            print(f"使用本机浏览器: {path}")
            return path
    except Exception as e:
        print(f"浏览器自动检测失败（回退到内置 Chromium）: {e}")

    return None


def resolve_auth_file(auth_file=None) -> str | None:
    """统一解析登录态文件。

    显式传入优先；否则用 session 模块的 state.json（存在才返回路径）。
    """
    if auth_file is not None:
        return str(auth_file) if os.path.exists(str(auth_file)) else None
    return S.state_path_for_playwright()


def open_browser(
    p=None,
    custom_browser_path: str | None = None,
    headless: bool | None = None,
    auth_file: str | os.PathLike | None = None,
    on_browser_not_found=None,
    use_session_state: bool = True,
):
    """打开浏览器，返回 (browser, context)。

    Args:
        custom_browser_path:
            - 纯数字（如 "9222"）→ CDP 接管模式，连本机该端口已开的浏览器
            - 文件路径 → 用它作为 executable_path 启动
            - None → 自动检测本机 Edge/Chrome，再回退 Playwright 自带 Chromium
        auth_file: storage_state JSON 路径。传 None 且 use_session_state=True 时，
                   自动使用 artifacts/storage/state.json（存在才注入）。
    """
    # ---- CDP 接管模式：复用你已登录的真实浏览器 ----
    if custom_browser_path and str(custom_browser_path).isdigit():
        # ★ 根因修复：原来即使 p 为 None 也直接调 open_cdp_session(p, ...)，
        #   会在里面 `p.chromium.connect_over_cdp` 上抛 AttributeError。
        #   现在自己起一个 playwright 实例兜底（调用方没传时）。
        if p is None:
            print("⚠ 未传入 playwright 实例，CDP 接管模式自行启动一个")
            p = sync_playwright().start()
        return open_cdp_session(p, str(custom_browser_path),
                                on_browser_not_found=on_browser_not_found)

    # ---- 普通启动模式 ----
    if headless is None:
        headless = False

    exe = resolve_browser_path(custom_browser_path)
    if exe:
        print(f"浏览器可执行文件: {exe}")
    else:
        print("使用 Playwright 内置 Chromium")

    try:
        browser = p.chromium.launch(
            headless=headless,
            executable_path=exe,
            args=BROWSER_ARGS,
            ignore_default_args=BROWSER_IGNORE_ARGS,
            # ★ 修复：config.SLOW_MO 原来定义了却从未传进来（死配置）。
            #   现在真正生效 —— 每步放慢，便于观察，也让人手速更自然。
            slow_mo=C.SLOW_MO,
        )
    except Exception as e:
        # ★★ 打包成 .app / .exe 之后最容易踩的坑（2026-10-04 转 macOS）：
        #   系统里既没有 Chrome/Edge，也没下载过 Playwright 自带的 Chromium
        #   → 报一句很难懂的 "Executable doesn't exist at ..."。
        #   这里翻译成人话，并给出**可以照抄的命令**。
        msg = str(e)
        if ("Executable doesn't exist" in msg
                or "playwright install" in msg
                or "doesn't exist at" in msg):
            raise RuntimeError(
                "没找到可用的浏览器内核，无法启动自动化。\n"
                "两种解决办法（任选其一）：\n"
                "  1) 安装 Google Chrome 或 Microsoft Edge —— 程序会自动检测并使用；\n"
                "  2) 在终端执行：python -m playwright install chromium\n"
                f"（原始错误：{msg.splitlines()[0][:160]}）") from e
        raise

    usable_auth = resolve_auth_file(auth_file) if use_session_state else None
    if usable_auth:
        print(f"注入已保存的登录态: {usable_auth}")
    else:
        print("未找到登录态文件，以未登录状态打开浏览器")

    context = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        storage_state=usable_auth,
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    context.set_default_timeout(15000)
    context.set_default_navigation_timeout(45000)
    context.add_init_script(STEALTH_SCRIPT)
    return browser, context


def open_cdp_session(p, port, on_browser_not_found=None):
    """连接本机已开调试端口的浏览器，返回 (browser, context)。

    用途：复用你**真实浏览器**里已经登录好的会话。
    典型流程：
        1. 用调试端口启动 Edge
        2. 手动登录星月写作
        3. 调本函数接管 → 之后所有自动化都带着你的真实登录态

    接管后请调用 session.save_from_context(ctx)，
    这样真实浏览器里的 cookie 就能被导出，以后不开调试端口也能用。
    """
    cdp_url = f"http://localhost:{port}/"
    try:
        import requests

        requests.get(f"{cdp_url}json/version", timeout=5)
    except Exception:
        print(f"错误：端口 {port} 上没有可接管的浏览器")
        print("请先用调试端口启动浏览器：")
        print(f'  msedge.exe --remote-debugging-port={port} '
              f'--user-data-dir="C:\\edge-debug"')
        if on_browser_not_found:
            on_browser_not_found()
        return None, None

    print(f"采用浏览器接管模式，端口号：{port}")
    browser = p.chromium.connect_over_cdp(cdp_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    if not browser.contexts:
        ctx.add_init_script(STEALTH_SCRIPT)
    return browser, ctx


def open_persistent(p, user_data_dir: str | os.PathLike, headless: bool = False,
                    browser_path: str | None = None):
    """持久化上下文模式：登录态（含 IndexedDB）存在 user_data_dir，长期复用。

    注意：persistent 模式不需要（也不能）注入 storage_state ——
    它的登录态天然存在 user_data_dir 里，浏览器退出后自己留着。
    """
    exe = resolve_browser_path(browser_path)
    if exe:
        print(f"浏览器可执行文件: {exe}")
    else:
        print("使用 Playwright 内置 Chromium")
    print(f"持久化用户目录: {user_data_dir}")

    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=headless,
        executable_path=exe,
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        args=BROWSER_ARGS,
        ignore_default_args=BROWSER_IGNORE_ARGS,
    )
    ctx.set_default_timeout(15000)
    ctx.set_default_navigation_timeout(45000)
    ctx.add_init_script(STEALTH_SCRIPT)
    return None, ctx


def launch_browser_for_task(p, browser_path=None, auth_file=None, headless=False):
    """给任务用的简化入口。

    不再因「没有登录态」而直接失败 —— 没有就以未登录状态打开，
    由 ensure_login() 决定要不要登录一次。
    """
    browser, context = open_browser(
        p=p, custom_browser_path=browser_path, headless=headless,
        auth_file=auth_file,
    )
    if context is None:
        print("浏览器启动失败（CDP 端口不通？）")
        return None, None
    return browser, context
