"""作品类命令：books / open / prepare。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations


import sys

__all__ = ["cmd_books", "cmd_open", "cmd_prepare"]


def cmd_books() -> None:
    """列出作品页上的所有作品（带 ID，用于确认定位依据）。"""
    from xyxbot.app import App
    from xyxbot import books as B

    with App(headless=False) as app:
        page = app.page
        if not B.goto_books(page):
            sys.exit(1)
        books = B.list_books(page)
        if not books:
            print("作品页上没有找到任何作品")
            sys.exit(1)
        print(f"\n共 {len(books)} 部作品：\n")
        print(f"  {'序号':<6}{'名字':<24}{'ID':<12}{'字数':<8}创建时间")
        print("  " + "-" * 62)
        for b in books:
            print(f"  [{b['index']}]   {b['title']:<20s}{b['book_id']:<12s}"
                  f"{b['words']:<8s}{b['created']}")



def cmd_open() -> None:
    """打开一个已有作品。

    用法:
        python main.py open <作品名关键词>
        python main.py open <作品名> --index 2      # 同名时选第几个
    """
    if len(sys.argv) < 3:
        print("用法: python main.py open <作品名关键词> [--index N]")
        print("例:   python main.py open 新建作品1")
        print("      python main.py open 自动化测试 --index 0")
        sys.exit(1)

    kw = sys.argv[2]
    idx = None
    if "--index" in sys.argv:
        try:
            idx = int(sys.argv[sys.argv.index("--index") + 1])
        except (IndexError, ValueError):
            print("✗ --index 后面要跟一个整数")
            sys.exit(1)

    from xyxbot.app import App
    from xyxbot import books as B

    with App(headless=False) as app:
        ok = B.open_book(app.page, kw, index=idx, console_pick=(idx is None))
    sys.exit(0 if ok else 1)



def cmd_prepare() -> None:
    """★ 流程准备：打开网站 → 检测/登录 → 保存 cookie 与缓存。

    用法:
        python main.py prepare            # 打开网站，检查/登录并保存
        python main.py prepare --no-open  # 不打开网站，只做本地状态检查
        python main.py prepare --clear    # 清除已保存的登录态（登出）

    说明:
        - 这是「所有流程开始之前」的准备动作，跑一次之后**长期免登录**
        - 保存位置：artifacts/storage/state.json
        - 一条龙 `auto` 默认会先做这一步（可用 --no-prepare 跳过）
    """
    args = sys.argv[2:]
    from xyxbot import login as L

    if "--clear" in args:
        from xyxbot import session as S

        S.clear()
        print("[prepare] 已清除登录态")
        return

    from xyxbot.app import App

    with App(headless=False) as app:
        r = L.prepare_session(
            app, save=True,
            open_site=("--no-open" not in args),
            auto=True, wait_seconds=0, interactive=True)
    print("\n" + "=" * 56)
    print(f"  准备结果：{'✓ 就绪' if r['ok'] else '✗ 未就绪'}")
    print(f"  登录     : {'是' if r['logged_in'] else '否'}（{r['mode']}）")
    print(f"  已保存   : {'是' if r['saved'] else '否'}")
    print(f"  cookie   : {r['cookies']} 条")
    if r.get("account"):
        print(f"  账号     : {r['account']}")
    if r.get("saved_at"):
        print(f"  保存时间 : {r['saved_at']}")
    print(f"  {r['message']}")
    print("=" * 56)
    sys.exit(0 if r["ok"] else 1)
