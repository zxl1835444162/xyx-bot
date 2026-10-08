"""★ 所有流程开始之前的统一准备入口（打开网站 → 保存 cookie/缓存）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot import session as S
import os

from xyxbot.login.flow import auto_login, manual_login
from xyxbot.login.state import _any_page_logged_in, _page_url, login_state_report, open_site_page, save_session

__all__ = ["prepare_session"]


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
