"""登录流程：账号密码自动登录 / 人工扫码 / 确保处于登录态。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import actions as A
from xyxbot import config as C
from xyxbot import session as S
from playwright.sync_api import Page
import os
import time

from xyxbot.login.state import _any_page_logged_in, login_state_report, open_login_page, open_site_page, save_session

__all__ = ["_has_captcha", "auto_login", "check_agreement", "ensure_login", "manual_login", "switch_to_password_tab"]


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
