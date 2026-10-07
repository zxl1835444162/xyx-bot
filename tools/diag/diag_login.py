# -*- coding: utf-8 -*-
"""诊断登录态：看看为什么 cookie 没被记录。

用法：
    .venv312\\Scripts\\python.exe diag_login.py

会做这些事：
    1. 检查本地有没有 state.json / metadata
    2. 打开浏览器访问星月写作（复用已有登录态）
    3. 打印 URL、cookie 清单、localStorage、判定结果
    4. 若判定为已登录 → 直接导出保存
    5. 否则提示你应该怎么做

全程只读 + 最后按需保存，不会破坏你现有登录态。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 仓库根（tools/<组>/ -> tools -> 根）
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xyxbot import config as C
from xyxbot import session as S
from xyxbot.browser import open_browser


def line(title: str = ""):
    print("\n" + "=" * 64)
    if title:
        print(f"  {title}")
        print("=" * 64)


def main():
    line("星月写作 登录态诊断")

    # ---------- 1. 本地文件 ----------
    line("1. 本地登录态文件")
    print(f"  state.json       : {'存在' if S.exists() else '不存在'}")
    if S.exists():
        info = S.describe()
        print(f"    保存时间: {info['saved_at']}")
        print(f"    已过时长: {S.age_text()}")
        print(f"    cookie  : {info['cookies']} 条")
        print(f"    大小    : {info['size']}")
    print(f"  session_meta.json: {'存在' if S.META_FILE.exists() else '不存在'}")
    print(f"  state.json       : "
          f"{'存在' if (C.STORAGE / 'state.json').exists() else '不存在'}")

    # ---------- 2. 起浏览器 ----------
    line("2. 打开站点检查（复用已有登录态）")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser, ctx = open_browser(p, headless=False)
        if ctx is None:
            print("  ✗ 浏览器启动失败")
            return 1

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(C.SITE["entry"], wait_until="domcontentloaded")
        except Exception as e:
            print(f"  ✗ 打不开站点: {e}")
            browser.close()
            return 1
        time.sleep(5)

        line("3. 页面状态")
        print(f"  URL    : {page.url}")
        try:
            print(f"  标题   : {page.title()}")
        except Exception:
            pass

        line("4. Cookie 清单")
        cookies = ctx.cookies()
        if cookies:
            for c in cookies:
                v = str(c.get("value", ""))
                print(f"  • {c['name']:36s} = {v[:44]}{'…' if len(v) > 44 else ''}")
                print(f"    domain={c['domain']}")
        else:
            print("  （没有任何 cookie）")
        print(f"\n  合计 {len(cookies)} 条")

        line("5. localStorage")
        try:
            ls = page.evaluate(
                "() => { const o={}; for (const k in localStorage) "
                "{ o[k]=String(localStorage.getItem(k)).slice(0,70); } return o; }"
            )
            if ls:
                for k, v in ls.items():
                    print(f"  • {k} = {v}")
            else:
                print("  （空）")
        except Exception as e:
            print(f"  读取失败: {e}")

        line("6. 判定结果")
        from xyxbot import login as L

        print("  " + L.login_state_report(page).replace("\n", "\n  "))
        print(f"  is_login_page: {L.is_login_page(page)}")
        logged = L.is_logged_in(page, verbose=True)

        # ---------- 7. 结论 ----------
        line("7. 结论")
        if logged:
            print("  ✓ 判定为【已登录】—— 现在导出登录态")
            ok = S.save_from_context(ctx)
            if ok:
                info = S.describe()
                print(f"  ✓ 已保存：{info['cookies']} 条 cookie，{info['size']}")
                print("  → 以后启动会自动复用，无需再登录")
            else:
                print("  ✗ 保存失败，看上面的错误信息")
        else:
            print("  ⚠ 判定为【未登录】")
            print("\n  可能的原因：")
            print("    a) 浏览器里确实还没登录 → 请先登录，然后重跑本脚本")
            print("    b) 已登录但被判定拦住了 → 看第 4/5 节，")
            print("       如果 cookie 或 localStorage 里其实有 token，")
            print("       说明前一次会话没有被保存下来")
            print("\n  怎么办：")
            print("    1. 确认浏览器里已经登录成功（能看到你的昵称/作品）")
            print("    2. 保持浏览器别关，打开软件 → 星月账号 → 「我已登录，立即保存」")
            print("    3. 或直接重跑本脚本（它登录成功时会自动保存）")

        line("诊断结束 —— 浏览器保持 25 秒供你观察")
        try:
            time.sleep(25)
        except KeyboardInterrupt:
            pass
        try:
            browser.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
