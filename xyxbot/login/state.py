"""登录态判定与存取 + 站点页打开/校验（多路判定，任一命中即算已登录）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import config as C
from xyxbot import session as S
from playwright.sync_api import Page
import time

__all__ = ["_any_page_logged_in", "_is_site_url", "_page_url", "_safe", "get_token_keys", "is_logged_in", "is_logged_in_by_local_storage", "is_login_page", "is_ready", "login_state_report", "open_login_page", "open_site_page", "save_session", "verify_session"]


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



# ------------------------------------------------------------------ 统一入口

def open_site_page(page: Page, wait: float = 3.0) -> None:
    """打开站点首页（已注入登录态时，这里就是「已登录」状态）。

    ★ 效率改造（2026-10-05，用户报「点击作品后，寻找按钮的过程很长」）：
      原实现是 `goto` 后**固定 `time.sleep(wait)`**。调用方 goto_books 传
      wait=2.5 ⇒ **每次开作品都白等 2.5 秒**（实测 goto_books 整段 2.78s，
      其中绝大部分是这 2.5s）。
      现在改成**条件等待「页面真的渲染出内容」**：SPA 骨架出现即返回
      （实测通常 0.3~0.8s），不用再吃满固定时长。
      超时仍用 `max(wait, 3.0)` —— 比原来更宽容，页面慢时最坏不会更差。
    """
    page.goto(C.SITE["entry"], wait_until="domcontentloaded")
    # ★ 条件等待：等 body 里有「可观的」实际内容（不是空骨架/白屏）。
    #   ★ 2026-10-05 修正：原来只判 `innerText 非空`，但 SPA 加载初期
    #     body 里可能就有零星的静态文字（如标题），判据太弱、会提前返回，
    #     导致后续「找作品卡」失败。改成要求**内容达到一定长度**（>20 字），
    #     这是一个更可靠的"首页真的渲染了"信号；超时仍用 max(wait,3.0)。
    try:
        from xyxbot.waiting import wait_until as _wait_until
        _wait_until(
            lambda: bool(page.evaluate(
                "() => (document.body && (document.body.innerText || '').trim().length > 20)")),
            timeout=max(float(wait), 3.0), interval=0.08,
            desc="站点首页渲染")
    except Exception:
        # 极端情况下页面对象异常 → 退回固定等待，保证行为不退化
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
