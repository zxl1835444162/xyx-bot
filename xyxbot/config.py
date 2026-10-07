"""集中配置：站点地址、路径、超时、浏览器参数。

网站改版时，优先改这一个文件。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------- 路径
#
# ★★ 打包（.app / .exe）之后，程序所在的目录是**只读**的
#    （macOS 尤其严格：签名/公证过的 .app 往里写会失败，甚至直接崩）。
#    而本项目所有"记忆"都写在 artifacts/ 下 —— 登录态、工作区配置、
#    细纲、截图、日志。
#
#    所以分两种情况：
#      * 源码运行（开发/测试）→ 还是项目目录下的 artifacts/（保持原行为）
#      * 打包运行（sys.frozen）→ 落到系统标准的**用户数据目录**：
#          macOS : ~/Library/Application Support/XYXBot/artifacts/
#          Windows: %APPDATA%\XYXBot\artifacts\
#          Linux : ~/.local/share/XYXBot/artifacts/
#
#    也可以显式用环境变量 `XYX_DATA_DIR` 指定（做便携版/多开很有用）。

ROOT = Path(__file__).resolve().parent.parent

#: 打包后用户数据目录的文件夹名（用 ASCII，避免各种工具链对中文路径的处理差异）
APP_DIR_NAME = "XYXBot"


def _default_data_root(platform_key: str | None = None,
                       home: Path | None = None) -> Path:
    """决定「可写数据」放哪。

    Args:
        platform_key: 仅测试用 —— 显式指定平台（"darwin"/"win32"/其它）。
                      默认按 `sys.platform` 判断。
                      ★ 有这个参数才能在 Windows 上验证 macOS 分支的落点，
                        否则只能靠读代码。
        home:         仅测试用 —— 替换用户主目录。

    Returns:
        数据根目录。源码运行时是项目根；打包后是系统用户数据目录。
    """
    override = (os.getenv("XYX_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser()

    if not getattr(sys, "frozen", False):
        return ROOT                      # 源码运行：项目目录

    plat = sys.platform if platform_key is None else platform_key
    home = home or Path.home()
    # 显式给了 platform_key 就按它判断；否则按真实操作系统
    is_win = (os.name == "nt") if platform_key is None else plat.startswith("win")

    if plat == "darwin":
        base = home / "Library" / "Application Support"
    elif is_win:
        base = Path(os.getenv("APPDATA") or (home / "AppData" / "Roaming"))
    else:
        base = Path(os.getenv("XDG_DATA_HOME") or (home / ".local" / "share"))
    return base / APP_DIR_NAME


DATA_ROOT = _default_data_root()
ARTIFACTS = DATA_ROOT / "artifacts"
SHOTS = ARTIFACTS / "screenshots"
TRACES = ARTIFACTS / "traces"
LOGS = ARTIFACTS / "logs"
STORAGE = ARTIFACTS / "storage"

# 登录态持久化文件（cookie + localStorage）。删掉它 = 登出。
STATE_FILE = STORAGE / "state.json"
# 持久化用户数据目录（比 state.json 更完整，含 IndexedDB）
USER_DATA_DIR = STORAGE / "userdata"
# ★★ 「上次载入的小说」轻量记忆（2026-10-04）：
#    只存 txt 路径 + 用户填的细纲/模板，**不存小说正文** —— 启动时按这个
#    文件里的路径重新分章（实测 100 章只要 5ms），所以文件只有几 KB，
#    而且永远不会和 txt 内容不一致。删掉它 = 忘掉上次载入的小说。
LAST_PROJECT = STORAGE / "last_project.json"

for _d in (SHOTS, TRACES, LOGS, STORAGE):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- 站点

SITE = {
    "name": "星月写作",
    # 首页是纯静态落地页，真正的应用（登录/创作台）在这个入口
    "entry": "https://xingyuexiezuo.com/",
    # ★ 重要：前端用 hash 路由（/#/xxx），不是路径路由（/xxx）
    # 直接访问 https://xingyuexiezuo.com/login 会 404
    "hash_routes": {
        "welcome": "/#/welcome",
        "login": "/#/login",
        "register": "/#/register",
        "reset": "/#/reset",
        "books": "/#/books",
        "scripts": "/#/scripts",
        "forum": "/#/forum",
        "workflow_list": "/#/workflow/list",
        "workflow_create": "/#/workflow/create",
    },
    # 后端接口域名（前端调这些，浏览器里不一定直接可见）
    "api_hosts": [
        "https://a.xingyuexiezuo.com",
        "https://c.xingyuexiezuo.com",
        "https://v1.xingyuexiezuo.com",
    ],
}


def route_url(key: str) -> str:
    """按 key 拼出完整 hash 路由地址。"""
    return SITE["entry"].rstrip("/") + SITE["hash_routes"][key]

# 登录成功的判据：URL 不再包含 login，且出现这些元素之一
LOGGED_IN_HINTS = [
    "text=创作",
    "[class*=avatar]",
    "[class*=user-info]",
]

# 登录页真实选择器（已实测于 2026-10，站点：星月写作）
# 登录页有两个 Tab：「微信登录 / 注册」和「账号密码」，默认显示微信扫码。
# 输入框是懒渲染的，必须先点「账号密码」Tab 才会出现。
LOGIN_SELECTORS = {
    # --- 切换 Tab ---
    "tab_password": [
        "text=账号密码",
        "[class*=tab]:has-text('账号密码')",
    ],
    "tab_wechat": [
        "text=微信登录",
        "text=微信登录 / 注册",
    ],
    # --- 账号密码登录（实测选择器）---
    "username": [
        'input[placeholder="请输入账号"]',
        'input[placeholder*="账号"]',
    ],
    "password": [
        'input[placeholder="请输入密码"]',
        'input[type="password"]',
    ],
    "login_btn": [
        'button:has-text("登录")',
        '[class*=login-btn]',
    ],
    # --- 协议勾选（未勾选时登录按钮点不动）---
    "agree": [
        "text=我已阅读并同意",
        "[class*=agree]",
        "[class*=protocol] input[type=checkbox]",
        'input[type="checkbox"]',
    ],
    # --- 微信扫码 ---
    "wechat_qr": [
        "[class*=qrcode]",
        "[class*=qr-code]",
        "text=请使用微信扫描二维码",
    ],
    # --- 登录成功后出现的标志 ---
    "logged_in_mark": [
        "text=我的作品",
        "text=创作中心",
        "[class*=avatar]",
        "[class*=user-info]",
        "[class*=userInfo]",
        "text=退出登录",
        "text=个人中心",
        "text=我的创作",
    ],
    # --- 确定「还在登录页」的标志（用于反向判断）---
    "login_page_mark": [
        "text=账号密码",
        "text=微信登录",
        "text=请使用微信扫描二维码",
        'input[placeholder="请输入账号"]',
        "[class*=login-box]",
    ],
    # --- 登录态在 localStorage 里的键名（命中任一即视为已登录）---
    "token_keys": [
        "token", "Token", "access_token", "accessToken",
        "userInfo", "user_info", "user", "authToken", "auth",
    ],
}

# 登录页路由（hash 路由）
LOGIN_URL = "https://xingyuexiezuo.com/#/login"


# ---------------------------------------------------------------- 作品页
# ★ 实测于 2026-10-03。注意一个坑：
#   页面上有两张**已存在的作品卡**，名字分别叫「新建作品」和「新建作品1」，
#   它们和真正的「新建作品」入口卡文字重叠！
#   所以**绝不能用 text=新建作品 去点**，必须用 class 区分：
#     - 入口卡： .create-card   （唯一）
#     - 已有卡： .book-card 但没有 .create-card
BOOK_SELECTORS = {
    # --- 侧边栏「作品」入口 ---
    "nav_books": [
        ".sidebar-container >> text=作品",
        "[class*=sidebar] >> text=作品",
        "text=作品",
    ],
    # --- ★ 新建作品入口卡（唯一正确目标）---
    "create_card": [
        ".create-card",
        ".book-card.create-card",
        ".book-card-wrapper .create-card",
        "div.create-card.cursor-pointer",
    ],
    # --- 入口卡内部的「新建作品」按钮（点它效果相同，作为备选）---
    "create_card_button": [
        ".create-card .book-card-action-button >> text=新建作品",
        ".create-card button:has-text('新建作品')",
        ".create-card >> text=新建作品",
    ],
    # --- 入口卡内部的「导入作品」按钮 ---
    "import_card_button": [
        ".create-card .book-card-action-button >> text=导入作品",
        ".create-card button:has-text('导入作品')",
    ],
    # --- 已有作品卡（用于校验/区分，不该被点）---
    "existing_card": [
        ".book-card-wrapper .book-card:not(.create-card)",
        ".book-card:not(.create-card)",
    ],
    # --- 新建作品后弹出的对话框（实测 2026-10-03）---
    # ★ 注意：页面上还有「邀请好友赚佣金」等活动弹窗，也会命中 [role=dialog]，
    #   所以必须用「标题文字」来锁定新建作品弹窗。
    "create_dialog": [
        ".n-modal:has-text('创建作品后可使用AI功能')",
        ".n-modal:has-text('作品名称')",
        "[role=dialog]:has-text('作品名称')",
        "[class*=modal]:has-text('作品名称')",
        ".n-modal:has-text('作品类型')",
    ],
    # --- 关闭活动弹窗（邀请好友 / 大奖赛等）---
    "close_activity_modal": [
        ".n-modal button[aria-label='close']",
        ".n-modal .n-base-close",
        "[role=dialog] .n-base-close",
        "[role=dialog] >> text=不再弹出",
        ".n-modal >> text=×",
    ],
    # --- 作品名称输入框（弹窗内，实测定值「新建作品」，上限 30 字）---
    "dialog_title_input": [
        ".n-modal input[placeholder='']",
        ".n-modal input[maxlength='30']",
        ".n-modal .n-input input",
        ".n-modal input[type='text']",
    ],
    # --- 作品类型：小说 / 剧本（单选卡）---
    "dialog_type_novel": [
        ".n-modal >> text=小说",
        ".n-modal [class*=type]:has-text('小说')",
        ".n-modal [class*=radio]:has-text('小说')",
    ],
    "dialog_type_script": [
        ".n-modal >> text=剧本",
        ".n-modal [class*=type]:has-text('剧本')",
        ".n-modal [class*=radio]:has-text('剧本')",
    ],
    # --- 作品简介输入框（选填，上限 500 字）---
    "dialog_intro_input": [
        ".n-modal textarea",
        ".n-modal input[placeholder*='简介']",
        ".n-modal [placeholder*='作品简介']",
    ],
    # --- 提交按钮 ---
    "dialog_confirm_btn": [
        ".n-modal button:has-text('提交')",
        ".n-modal button:has-text('确定')",
        ".n-modal button:has-text('创建')",
    ],
}


# ---------------------------------------------------------------- 运行参数

HEADLESS = os.getenv("XYX_HEADLESS", "0") == "1"  # 默认有头，方便观察
SLOW_MO = int(os.getenv("XYX_SLOW_MO", "80"))     # 每步放慢(ms)，看得清
DEFAULT_TIMEOUT = int(os.getenv("XYX_TIMEOUT", "15000"))  # 元素等待(ms)
NAV_TIMEOUT = int(os.getenv("XYX_NAV_TIMEOUT", "45000"))

# 防机器人指纹：用真实浏览器 UA，别用 headless 默认 UA
VIEWPORT = {"width": 1440, "height": 900}
LOCALE = "zh-CN"
TIMEZONE = "Asia/Shanghai"

# 浏览器可执行文件路径。留 None 则自动检测本机 Edge / Chrome，
# 都没有才回退到 Playwright 自带的 Chromium。
# 跑 `python main.py browsers` 可查看检测结果。
BROWSER_PATH = os.getenv("XYX_BROWSER") or None

# 是否允许自动检测本机浏览器（Edge 优先，风控指纹更自然，且无需下载内核）
AUTO_DETECT_BROWSER = True

# CDP 接管模式的调试端口。设成端口号（如 "9222"）则连你手动开的浏览器，
# 复用真实登录态与指纹 —— 对付风控最有效。对应 novel_publisher 的同一机制。
CDP_PORT = os.getenv("XYX_CDP_PORT") or None
