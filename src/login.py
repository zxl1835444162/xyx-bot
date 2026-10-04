"""登录态管理（基于实测的星月写作登录页结构）。

登录页有两个 Tab：
    1.「微信登录 / 注册」—— 默认显示，扫码登录
    2.「账号密码」—— 需点 Tab 才渲染输入框，可全自动登录

因此提供两条路：
    auto_login(page, user, pwd)  -> 有账号密码时全自动
    manual_login(page)           -> 没账号密码时，人工扫码/输入
    ensure_login(app)            -> 先查登录态，失效才走上面流程

★ 登录态复用（核心）
    只要登录成功一次，就立刻把 cookie + localStorage 导出到
    artifacts/storage/state.json。之后每次启动浏览器都注入这份 state，
    等同于「你早就登录过了」——**不用再扫码/输密码**。
    这套逻辑在 src/session.py，本模块负责在正确的时机调用它。

    调用关系：
        ensure_login(app)
          ├─ 注入已有 state 打开站点
          ├─ 已登录？→ 直接用，结束
          ├─ 有账号密码？→ auto_login() → 成功后 save_session()
          └─ 否则 → manual_login()        → 成功后 save_session()
"""

from __future__ import annotations

import os
import time

from playwright.sync_api import Page

from . import actions as A
from . import config as C
from . import session as S


# ------------------------------------------------------------------ 登录态保存

def save_session(app_or_context, quiet: bool = False) -> bool:
    """把当前登录态落盘，下次免登录。

    参数可以是 App 实例，也可以是 BrowserContext 本身。
    """
    ctx = getattr(app_or_context, "context", app_or_context)
    if ctx is None:
        if not quiet:
            print("[login] 无可用上下文，无法保存登录态")
        return False
    ok = S.save_from_context(ctx)
    if ok and not quiet:
        print("[login] → 下次启动将自动复用该登录态，无需再次登录")
    return ok


# ------------------------------------------------------------------ 判断

def _page_url(page: Page) -> str:
    try:
        return (page.url or "").lower()
    except Exception:
        return ""


def is_login_page(page: Page) -> bool:
    """当前是否停在登录页。"""
    url = _page_url(page)
    if "/login" in url or "/register" in url:
        return True
    for sel in C.LOGIN_SELECTORS.get("login_page_mark", []):
        try:
            if page.locator(sel).first.is_visible(timeout=600):
                return True
        except Exception:
            continue
    return False


def get_token_keys(page: Page) -> list[str]:
    """列出 localStorage 里疑似登录票据的键（调试用）。"""
    try:
        keys = page.evaluate(
            "() => Object.keys(localStorage).filter(k => "
            "/token|auth|user|login|session|uid|account/i.test(k))"
        )
        return list(keys or [])
    except Exception:
        return []


def is_logged_in_by_local_storage(page: Page) -> bool:
    """检查 localStorage 里是否有登录票据。

    星月写作是 SPA，登录态主要放 localStorage。这里是**最可靠**的判据，
    因为不依赖页面元素是否渲染完成。
    """
    try:
        val = page.evaluate(
            """() => {
                const pat = /token|auth|user|login|session|uid|account/i;
                for (const k in localStorage) {
                    if (!pat.test(k)) continue;
                    const v = localStorage.getItem(k);
                    if (!v) continue;
                    // 排除明显的空壳值
                    if (v === 'null' || v === 'undefined' || v === '{}' || v === '[]') continue;
                    return k;
                }
                return '';
            }"""
        )
        return bool(val)
    except Exception:
        return False


def _is_site_url(url: str) -> bool:
    """URL 是否真的落在星月写作站点上。

    ★ 根因修复（兜底过宽）：
      原来第 3 路兜底只判「URL 既不在登录页也不在 welcome → 已登录」，
      于是 `about:blank`、`chrome-error://`、任何**根本没打开站点**的状态
      都会被判成「已登录」，进而把一份无效的 state 保存下来。
      现在要求 URL 确实在站点域名下（或至少不是明显的空白/错误页）。
    """
    u = (url or "").strip().lower()
    if not u:
        return False
    if u in ("about:blank", "about:newtab", "chrome://newtab/"):
        return False
    if u.startswith(("chrome-error://", "edge-error://", "about:", "chrome://")):
        return False
    # 站点域名（含 api 子域）或本地文件都不算
    host = C.SITE["entry"].split("//")[-1].split("/")[0].lower()  # xingyuexiezuo.com
    return host in u


def is_logged_in(page: Page, verbose: bool = False) -> bool:
    """判断是否已登录。多路判定，任一命中即算已登录。

    判定顺序（关键：**先排除"明确在登录页"**，再看登录证据）：
        0. URL 含 login/register，或页面出现登录页标志 → 一定未登录
        1. localStorage 里有登录票据  ← SPA 最可靠的登录证据
        2. 页面出现已登录标志元素
        3. URL 既不在登录页、也不在欢迎页（兜底）

    verbose=True 时打印每一路的结果，排查用。
    """
    url = _page_url(page)

    # ---- 第 0 路：明确在登录/注册页 → 直接判未登录 ----
    if "/login" in url or "/register" in url:
        if verbose:
            print(f"    判定: URL 含 login/register → 未登录 ({url})")
        return False

    # 页面还在登录页（登录 Tab / 二维码 / 输入框可见）→ 未登录
    # 注意：这一路必须排在 localStorage 之前，
    # 否则「登录页上残留的旧 token」会造成误判
    if is_login_page(page):
        if verbose:
            print("    判定: 页面仍是登录页（登录元素可见）→ 未登录")
        return False

    # ---- 第 1 路：localStorage ----
    if is_logged_in_by_local_storage(page):
        if verbose:
            keys = get_token_keys(page)
            print(f"    判定: localStorage 有登录票据 → 已登录 {keys}")
        return True

    # ---- 第 2 路：页面元素 ----
    for sel in C.LOGIN_SELECTORS["logged_in_mark"]:
        try:
            if page.locator(sel).first.is_visible(timeout=800):
                if verbose:
                    print(f"    判定: 元素命中 {sel} → 已登录")
                return True
        except Exception:
            continue

    # ---- 第 3 路：URL 兜底（★ 要求确实在站点域名下）----
    if _is_site_url(url) and "/welcome" not in url:
        if verbose:
            print(f"    判定: 已离开登录页且非欢迎页 → 视为已登录 ({url})")
        return True

    if verbose:
        print(f"    判定: 各路均未命中 → 未登录 ({url})")
    return False


def login_state_report(page: Page) -> str:
    """生成一份人类可读的登录态报告，排查问题用。"""
    url = _page_url(page)
    lines = [f"URL: {url}"]
    lines.append(f"标题: {_safe(lambda: page.title())}")
    lines.append(f"localStorage 疑似票据键: {get_token_keys(page)}")
    lines.append(f"is_login_page: {is_login_page(page)}")
    lines.append(f"is_logged_in: {is_logged_in(page)}")
    marks = []
    for sel in C.LOGIN_SELECTORS["logged_in_mark"]:
        try:
            if page.locator(sel).first.is_visible(timeout=400):
                marks.append(sel)
        except Exception:
            continue
    lines.append(f"命中的已登录标志: {marks or '（无）'}")
    return "\n    ".join(lines)


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return f"<读取失败: {e}>"


# ------------------------------------------------------------------ 打开登录页

def open_login_page(page: Page, wait: float = 6.0) -> None:
    """打开登录页并等待渲染完成。"""
    print("[login] 打开登录页 ...")
    page.goto(C.LOGIN_URL, wait_until="domcontentloaded")
    time.sleep(wait)  # 登录页懒渲染，多等一会儿


def switch_to_password_tab(page: Page) -> bool:
    """切到「账号密码」Tab（输入框才会渲染出来）。"""
    ok = A.click(page, C.LOGIN_SELECTORS["tab_password"],
                 label="切到账号密码Tab", shot_on_fail=False)
    if ok:
        time.sleep(1.5)
    return ok


def check_agreement(page: Page) -> None:
    """勾选用户协议（没勾选时登录按钮点不动）。"""
    for sel in C.LOGIN_SELECTORS["agree"]:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=1500):
                loc.click()
                print("[login] 已勾选用户协议")
                time.sleep(0.4)
                return
        except Exception:
            continue
    print("[login] 未找到协议勾选框（可能默认已勾选）")


# ------------------------------------------------------------------ 自动登录

def auto_login(page: Page, username: str, password: str,
               save_after: bool = True,
               poll: float = 0.5) -> bool:
    """账号密码全自动登录。成功返回 True。

    注意：站点有腾讯滑块验证码。若触发，需要手动拖一下，
    此时本函数会等待你手工完成（最多 120s）。

    save_after=True 时，登录成功立刻导出登录态（下次免登录）。
    """
    open_login_page(page)
    if not switch_to_password_tab(page):
        print("[login] ✗ 没找到「账号密码」Tab")
        return False

    check_agreement(page)

    if not A.fill(page, C.LOGIN_SELECTORS["username"], username, label="账号"):
        return False
    if not A.fill(page, C.LOGIN_SELECTORS["password"], password, label="密码"):
        return False

    A.click(page, C.LOGIN_SELECTORS["login_btn"], label="登录按钮")

    # 等结果：可能直接进，也可能弹验证码
    # ★ 效率改造：原来 `sleep(2)` 粗轮询 → 登录成功那一刻平均多等 1 秒，
    #   最坏多等 2 秒。判据 `_any_page_logged_in` 只是读 localStorage /
    #   可见性，很轻，可以问得勤。改成 0.5s 轮询 + 前 1 秒更快。
    deadline = time.time() + 120
    warned = False
    while time.time() < deadline:
        if _any_page_logged_in(page.context):
            print("[login] ✓ 登录成功")
            time.sleep(0.5)     # 给站点一点时间把 token 写完（原来 1.0s）
            if save_after:
                save_session(page.context)
            return True
        # 检测是否弹出验证码
        if not warned and _has_captcha(page):
            print("[login] ⚠ 检测到验证码，请在弹出的浏览器里手动完成，"
                  "完成后脚本会自动继续 ...")
            warned = True
        time.sleep(poll)

    print("[login] ✗ 登录超时")
    try:
        print(f"    {login_state_report(page)}")
    except Exception:
        pass
    page.screenshot(path=str(C.SHOTS / "login-failed.png"), full_page=True)
    return False


def _has_captcha(page: Page) -> bool:
    """检测是否出现腾讯验证码。"""
    try:
        for f in page.frames:
            if "captcha" in (f.url or "").lower():
                return True
    except Exception:
        pass
    for sel in ["text=请完成验证", "text=拖动滑块", "[class*=captcha]"]:
        try:
            if page.locator(sel).first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


# ------------------------------------------------------------------ 人工登录

def _any_page_logged_in(context) -> bool:
    """检查 context 里**所有标签页**，任一已登录即算登录成功。

    用户可能在浏览器里新开了标签页，登录态在别的 page 上。
    """
    try:
        pages = context.pages
    except Exception:
        return False
    for pc in pages:
        try:
            if is_logged_in(pc):
                return True
        except Exception:
            continue
    return False


def manual_login(page: Page, wait_seconds: int = 300,
                 save_after: bool = True,
                 stop_event=None) -> bool:
    """人工登录：打开登录页，你在浏览器里扫码或输账号密码。

    关键设计（★ 解决"判定不准导致没记录到"的问题）：
        自动判定只是**加速**手段，不是唯一途径。本函数会一直等到：
          a) 自动判定成已登录（快），或
          b) 调用方通过 stop_event 主动喊停（用于「我已登录，立即保存」按钮），或
          c) 超过 wait_seconds 兜底超时（默认 300s，可用 0 表示不限时）

        无论走哪条路，只要最终**你确认已登录**，就会导出 cookie。

    Args:
        wait_seconds: 最长等待秒数；设 0 表示**不超时**，一直等（推荐）
        stop_event: threading.Event；被 set 时立即保存并返回 True
    """
    ctx = page.context
    open_login_page(page)
    print("=" * 60)
    print("  请在弹出的浏览器里登录星月写作（微信扫码 / 账号密码）")
    if wait_seconds:
        print(f"  最长等待 {wait_seconds} 秒；登录成功后会自动记录")
    else:
        print("  登录不限时；完成后请回软件点「我已登录，立即保存」")
    print("  ⚠ 登录后**别关浏览器窗口**，等界面提示「已就绪」")
    print("=" * 60)

    deadline = (time.time() + wait_seconds) if wait_seconds else None
    last_report = 0.0
    manual_saved = False

    while True:
        # ---- 路径 b：用户手动喊停 ----
        if stop_event is not None and stop_event.is_set():
            print("[login] 收到「我已登录」指令，立即导出登录态 ...")
            time.sleep(0.8)          # 给站点一点时间写完 token
            manual_saved = True
            if save_after:
                ok = save_session(ctx)
                if ok:
                    print("[login] ✓ 登录态已按你的确认保存")
                    return True
                print("[login] ⚠ 保存失败，仍继续等待自动判定 ...")
                stop_event.clear()
            else:
                return True

        # ---- 路径 a：自动判定 ----
        if _any_page_logged_in(ctx):
            print("[login] ✓ 自动检测到登录成功！")
            time.sleep(1.5)
            if save_after:
                save_session(ctx)
            return True

        # ---- 路径 c：兜底超时 ----
        if deadline is not None and time.time() >= deadline:
            print("[login] ✗ 超时，仍未检测到登录")
            print("    —— 超时时的页面状态 ——")
            try:
                print(f"    {login_state_report(page)}")
                print(f"    所有标签页: {[p.url for p in ctx.pages]}")
            except Exception:
                pass
            page.screenshot(path=str(C.SHOTS / "login-timeout.png"), full_page=True)
            print(f"[login] 已截图 {C.SHOTS / 'login-timeout.png'}")
            return False

        # ---- 每 30 秒打印一次诊断 ----
        now = time.time()
        if now - last_report >= 30:
            last_report = now
            if deadline:
                print(f"[login] ... 等待中（剩余 {int(deadline - now)}s）")
            else:
                print("[login] ... 等待登录中（不限时，可随时点「我已登录，立即保存」）")
            try:
                print(f"    {login_state_report(page)}")
            except Exception:
                pass

        time.sleep(1.5)


# ------------------------------------------------------------------ 统一入口

def open_site_page(page: Page, wait: float = 3.0) -> None:
    """打开站点首页（已注入登录态时，这里就是「已登录」状态）。"""
    page.goto(C.SITE["entry"], wait_until="domcontentloaded")
    time.sleep(wait)


def verify_session(app, wait: float = 3.0) -> bool:
    """打开站点，校验保存的登录态是否还有效。

    返回 True 表示「现在确实是登录状态」。
    这是 UI 上「校验登录态」按钮的实现。
    """
    page = app.page
    open_site_page(page, wait)
    ok = _any_page_logged_in(page.context)
    print(f"[login] 登录态校验: {'有效 ✓' if ok else '无效 / 已过期 ✗'}")
    print(f"    {login_state_report(page)}")
    if ok:
        # 有效就顺手刷新一份 state（站点可能轮换了 token）
        save_session(page.context, quiet=True)
    return ok


def ensure_login(app, wait_seconds: int = 0, auto: bool = True,
                 stop_event=None) -> bool:
    """确保处于登录态，全程无需再登录（只要之前登录过一次）。

    流程：
        1. 注入已保存的登录态打开站点 —— 大多数情况到这就结束了
        2. 万一过期，用环境变量里的账号密码自动登录
        3. 再不行才退回人工登录（扫码 / 手输）

    环境变量：
        XYX_USER  账号
        XYX_PWD   密码

    Args:
        auto: False 时跳过第 2 步，直接走人工登录
        wait_seconds: 人工登录的最长等待；0 = 不限时（默认，推荐）
        stop_event: 传给人工登录的「我已登录」信号

    注意：不再盲目复用「自动判定失败」的结论 ——
    只要注入了 state 且能打开站点，就算判定失败也给人一次登录机会，
    而不是直接报错退出。
    """
    page = app.page

    has_state = S.exists()
    if has_state:
        info = S.describe()
        print(f"[login] 发现已保存的登录态（{info['saved_at']}，"
              f"{info['cookies']} 条 cookie），尝试复用 ...")
    else:
        print("[login] 未发现登录态，需要登录一次")

    open_site_page(page, wait=3.0)

    print(f"[login] 当前状态诊断:\n    {login_state_report(page)}")

    if _any_page_logged_in(page.context):
        print("[login] ✓ 登录态有效，直接复用 —— 无需再次登录")
        save_session(page.context, quiet=True)
        return True

    if has_state:
        print("[login] ⚠ 保存的登录态已失效，需要重新登录")

    user = os.getenv("XYX_USER", "").strip()
    pwd = os.getenv("XYX_PWD", "").strip()

    if auto and user and pwd:
        print("[login] 检测到环境变量账号密码，尝试自动登录 ...")
        if auto_login(page, user, pwd):
            return True
        print("[login] 自动登录失败，转人工登录")

    return manual_login(page, wait_seconds, stop_event=stop_event)


# ------------------------------------------------------- ★ 流程准备（一键）

def prepare_session(app, save: bool = True, open_site: bool = True,
                    auto: bool = True, wait_seconds: int = 0,
                    stop_event=None, interactive: bool = True) -> dict:
    """★★ 「所有流程开始之前」的统一准备入口。

    用户需求（2026-10-03）：
      「在所有的流程开始之前，有一个打开网站提前配置，
        然后进行 cookie 或者缓存保存的功能，
        然后之后点击一条龙服务，就直接开始。」

    做的事情（按顺序）：
      ① 打开站点（自动注入已保存的登录态 → 多数情况直接是「已登录」）
      ② 检测登录态是否有效
      ③ 无效 → 自动登录（环境变量账号密码）→ 再不行 → 人工登录（扫码）
      ④ ★ 保存 cookie + localStorage（Playwright `storage_state`）
         到 `artifacts/storage/state.json`，下次免登录
      ⑤ 返回一份摘要（给 UI 显示「准备就绪」）

    ★ 与 `ensure_login()` 的区别：
      `ensure_login` 只保证「这次能进去」；
      `prepare_session` 额外强调 **落盘保存**，
      并把结果整理成结构化摘要（供 UI 状态灯 / 一条龙前置检查用）。

    Args:
        app:          App 实例
        save:         准备完成后是否导出登录态（默认 True）
        open_site:    是否先打开站点（默认 True）
        auto:         是否尝试环境变量自动登录
        wait_seconds: 人工登录最长等待（0 = 不限时）
        stop_event:   人工登录的「我已登录」信号
        interactive:  允许人工登录（False = 只做无人的检测+保存）

    Returns:
        dict {
          "ok": bool,              # 是否已就绪（处于登录态）
          "logged_in": bool,       # 当前是否登录
          "saved": bool,           # 登录态是否已落盘
          "cookies": int,          # cookie 条数
          "account": str,          # 账号（可能空）
          "saved_at": str,         # 保存时间
          "mode": str,             # reuse / live / auto / manual / failed
          "message": str,          # 给 UI 的一句话
        }
    """
    page = app.page
    print("=" * 60)
    print("  ★ 流程准备：打开网站 → 检查/登录 → 保存 cookie + 缓存")
    print("=" * 60)

    info = S.describe()
    if info.get("saved"):
        print(f"[prepare] 已有登录态：{info.get('saved_at')} · "
              f"{info.get('cookies')} 条 cookie"
              f"{' · ' + info['account'] if info.get('account') else ''}")
    else:
        print("[prepare] 尚无本地登录态文件，将打开网站检测"
              "（若浏览器里仍登录着，会直接把它保存下来）")

    # ① 打开站点
    if open_site:
        open_site_page(page, wait=3.0)

    # ② 检测
    logged = _any_page_logged_in(page.context)
    # ★ mode 标签要**区分两种情况**（2026-10-03 实测坑）：
    #   本地有 state 文件 + 打开后是登录的 → "reuse"（真·复用）
    #   本地**没有** state 文件、但浏览器里居然还是登录的
    #     → "live"（浏览器里本就登录着；常见于：刚点了「清除」但
    #       旧浏览器进程还活着，cookie 还在）
    #   这俩都算「就绪」，但标签不能混，否则日志会让人以为在读旧文件。
    mode = "reuse" if info.get("saved") else "live"
    if not logged:
        print(f"[prepare] 当前未登录，开始登录流程:\n    {login_state_report(page)}")
        # ③ 自动 → 人工
        user = os.getenv("XYX_USER", "").strip()
        pwd = os.getenv("XYX_PWD", "").strip()
        if auto and user and pwd:
            print("[prepare] 尝试环境变量自动登录 …")
            if auto_login(page, user, pwd):
                logged, mode = True, "auto"
        if not logged:
            if not interactive:
                print("[prepare] ✗ 未登录且不允许人工登录（interactive=False）")
                return {
                    "ok": False, "logged_in": False, "saved": S.exists(),
                    "cookies": info.get("cookies", 0),
                    "account": info.get("account", ""),
                    "saved_at": info.get("saved_at", ""),
                    "mode": "failed",
                    "message": "未登录：请先打开网站完成登录",
                }
            print("[prepare] 转人工登录（请在浏览器里完成）…")
            if manual_login(page, wait_seconds, save_after=False,
                            stop_event=stop_event):
                logged, mode = True, "manual"

    # ④ 保存 cookie + 缓存
    saved = False
    if logged and save:
        # 关掉可能还开着的登录页 tab，回到站点首页再导 state
        try:
            if _page_url(page).find("login") >= 0:
                open_site_page(page, wait=1.5)
        except Exception:
            pass
        saved = save_session(page.context, quiet=True)
        print(f"[prepare] 登录态已落盘: {'✓' if saved else '✗'}")

    after = S.describe()
    # ★★ 根因修复（ok 虚高）：
    #   原来 `ok = logged and (saved or after.get("saved"))` ——
    #   而 `after["saved"]` 只是「本地存在 state 文件」，可能是**上一轮留下的旧文件**。
    #   于是「本轮判定未登录 + 本地有旧 state」也会返回 ok=True，
    #   调用方（一条龙前置检查）就会带着一份无效登录态继续跑。
    #
    #   现在语义收紧：
    #     usable = 本次真的落了盘 或 本次复用了**已有的** state 且判定为已登录
    #     ok     = 确实处于登录态 且 有一份可用的 state
    usable = bool(saved or (info.get("saved") and logged))
    ok = bool(logged and usable)
    msg = ("准备就绪 · 已保存 cookie 与缓存，可直接点「一条龙」"
           if ok else "尚未就绪：需要登录后保存")
    print(f"[prepare] {'✓' if ok else '✗'} {msg} "
          f"（mode={mode}, cookies={after.get('cookies')}）")
    print("=" * 60)
    return {
        "ok": ok,
        "logged_in": bool(logged),
        "saved": usable,
        "cookies": after.get("cookies", 0),
        "account": after.get("account", ""),
        "saved_at": after.get("saved_at", ""),
        "mode": mode,
        "message": msg,
    }


def is_ready(auto_verify: bool = False) -> dict:
    """不启动浏览器，只看**本地是否已有可用的登录态文件**。

    给 UI 做「准备状态灯」用（不阻塞、不开浏览器）。
    """
    info = S.describe()
    ok = bool(info.get("saved"))
    return {
        "ok": ok,
        "saved": ok,
        "cookies": info.get("cookies", 0),
        "account": info.get("account", ""),
        "saved_at": info.get("saved_at", ""),
        "age": S.age_text(),
        "message": (f"已有登录态（{info.get('saved_at')} · "
                    f"{info.get('cookies')} 条 cookie）"
                    if ok else "尚无登录态：点「① 打开网站并保存」先准备"),
    }
