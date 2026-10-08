"""审稿与批量：review / batch。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations


import sys

__all__ = ["cmd_batch", "cmd_review"]


def cmd_review() -> None:
    """AI 审稿（★ 与 `ai` 同级功能，但走**右侧抽屉**而非弹窗）。

    用法:
        python main.py review <作品名> [--req "强盛集团云霄拯救过稿计划"]
                             [--model 智慧版] [--card 智慧版-6A]
                             [--assoc 正常] [--tab 快捷选项] [--index N]
                             [--chapter 第2章] [--instruction "..."]
                             [--no-select-all]
                             [--go] [--wait] [--replace] [--timeout 600]

    说明:
        - 不带 --go 只把抽屉填好，不点「生成」（安全预览）
        - ★ 会先自动打开作品，再点「AI审稿」
        - ★ 待审文本**默认沿用页面自带的当前章内容**（无需传文本）
        - --req "关键词"：按文字定位选中「审稿要求」里的提示词
        - --card：分类与卡片名不同（分类=智慧版，卡片=智慧版-6A）
        - ★ --chapter "第2章"：审稿前先打开这一章（留空=选第 1 个章节项）
          （不打开章节的话正文区是空的，待审文本也是空的）
        - ★ --instruction "..."：在**自带章节正文**基础上再追加一段提示词
          （类似「指令模板」的写法，会拼成「提示词 + 正文」一起送审）；
          支持多行，写多行时用 $'...\n...' 或直接换行续写
          （例：--instruction $'第一行要求\n第二行要求'）
        - ★ --no-select-all：替换前**不**全选正文（默认会全选）。
          默认全选是因为「替换 / 插入」是智能双模：没选中就变成「插入」，
          原文还留着 → 结果跟原稿前后拼接。
        - ★ --wait：等审稿生成完成（几分钟很正常）；与 --go 一起用
        - ★ --replace：完成后点「替换 / 插入」落盘到正文（隐含 --wait）
        - --timeout N：等生成的最长秒数（默认 600）
        - --index N：站点上有同名作品时指定第几本（从 0 开始）
    """
    args = sys.argv[2:]
    if not args:
        print("用法: python main.py review <作品名> "
              "[--req '强盛集团云霄拯救过稿计划'] [--card 智慧版-6A] "
              "[--chapter 第2章] [--instruction '...'] "
              "[--go --wait --replace]")
        sys.exit(1)

    book = args[0]
    go = "--go" in args
    wait = "--wait" in args or "--replace" in args
    do_replace = "--replace" in args
    select_all = "--no-select-all" not in args

    def _val(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    model = _val("--model", "智慧版")
    card = _val("--card", "智慧版-6A")
    assoc = _val("--assoc", "正常")
    req = _val("--req", "")
    tab = _val("--tab", "快捷选项")
    chapter = _val("--chapter", "")
    instruction = _val("--instruction", "")
    tmo = _val("--timeout", "600")
    done_timeout = int(tmo) if tmo.isdigit() else 600
    ix = _val("--index", "")
    idx = int(ix) if ix and ix.lstrip("-").isdigit() else None

    from xyxbot.app import App
    from xyxbot import books as B
    from xyxbot import ai as AI

    with App(headless=False) as app:
        if not B.open_book(app.page, book, console_pick=(idx is None),
                           index=idx, wait=3.0):
            print("✗ 打开作品失败")
            sys.exit(1)
        ok = AI.ai_review(app.page,
                          model=model,
                          model_card_name=card,
                          model_card_hint=AI.MODEL_CARD_HINT.get(card, ""),
                          associate=assoc,
                          requirement=req,
                          req_tab=tab,
                          instruction=instruction,
                          open_chapter=chapter,
                          start=go,
                          wait_done=wait,
                          done_timeout=done_timeout,
                          replace=do_replace,
                          select_all=select_all)
        if ok:
            print(f"[review] 当前审稿要求："
                  f"{AI.current_review_requirement(app.page)}")
            if do_replace:
                print("[review] ✓ 审稿结果已替换落盘到正文")
    sys.exit(0 if ok else 1)



def cmd_batch() -> None:
    """★★ 批量跑章：第 start ~ end 章，逐章一条龙。

    用法:
        python main.py batch <作品名> --from 3 --to 10
                             [--plot "固定剧情"]     # 不指定则用指令模板(需要 --project)
                             [--project 工程.json]   # 指令模板来源（含 #@ 当前章）
                             [--min 100] [--max 5000]
                             [--rv-req "强盛集团云霄拯救过稿计划"]
                             [--rv-card 智慧版-6A] [--rv-assoc 正常]
                             [--rv-instruction "提示词…"]
                             [--no-review] [--no-replace] [--rv-timeout 600]
                             [--no-new]              # 缺章不自动新建
                             [--stop-on-fail]        # 某章失败就停

    说明:
        - ★ 每章：确保章节存在 → 切到该章 → 渲染 plot → 一条龙 → 下一章
        - ★ 指令模板里用 `#@`（或 {{当前章}}）代表「当前正在生成的这一章」，
            逐章自动替换成该章细纲；`#N` 仍是绝对章号
        - ★ 缺章默认自动点「新建章节」补建（标题自动递增）
    """
    args = sys.argv[2:]
    if not args:
        print("用法: python main.py batch <作品名> --from 3 --to 10 "
              "[--project 工程.json]")
        sys.exit(1)

    book = args[0]

    def _val(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    def _int(flag, default):
        v = _val(flag, "")
        return int(v) if v and v.lstrip("-").isdigit() else default

    start = _int("--from", 1)
    end = _int("--to", 1)
    if end < start:
        print("✗ --to 不能小于 --from"); sys.exit(1)

    plot = _val("--plot", "")
    project_path = _val("--project", "")
    min_words = _int("--min", 100)
    max_words = _int("--max", 5000)
    # ★★ 2026-10-07 修 bug：`cmd_batch` 原来**没有定义 max_retry**，却在下面
    #   `max_retry=max_retry` 处使用它 —— 那个赋值是在 `cmd_auto` 里的局部变量，
    #   到这里就是 NameError（`python main.py batch …` 直接崩）。
    #   一直没被发现：GUI 走另一条路径（_ai_batch_go → ai_batch_chapters），
    #   而未定义名扫描器以前把整文件的赋值都当模块全局（跨函数误判）。
    max_retry = _int("--retry", 5)
    no_review = "--no-review" in args
    do_replace = "--no-replace" not in args
    do_new = "--no-new" not in args
    stop_on_fail = "--stop-on-fail" in args
    rv_req = _val("--rv-req", "")
    rv_card = _val("--rv-card", "智慧版-6A")
    rv_model = _val("--rv-model", "智慧版")
    rv_assoc = _val("--rv-assoc", "正常")
    rv_instr = _val("--rv-instruction", "")
    rv_timeout = _int("--rv-timeout", 600)

    from xyxbot.app import App
    from xyxbot import books as B
    from xyxbot import ai as AI
    from xyxbot import login as L

    # ★ 指令模板渲染来源
    plot_for = None
    if not plot and project_path:
        from xyxbot.novel import NovelProject
        proj = NovelProject.open(project_path)
        tpl = proj.instruction or "#@"
        has_cur = bool(proj.CUR_RE.search(tpl))
        tag = "含 #@ 当前章" if has_cur else "无 #@，每章剧情相同"
        print(f"[batch] 指令模板（{tag}）：{tpl[:50]}…")
        plot_for = lambda no: proj.render_for_batch(no, template=tpl)
    elif not plot:
        print("⚠ 既没给 --plot 也没给 --project，每章 plot 为空"
              "（续写框会留空，看站点是否自带内容）")

    with App(headless=False) as app:
        # 阶段零：准备
        st = L.is_ready()
        if not st["ok"]:
            pr = L.prepare_session(app, save=True, auto=True,
                                   wait_seconds=0, interactive=True)
            if not pr["ok"]:
                print(f"✗ 准备未完成：{pr['message']}"); sys.exit(1)

        if not B.open_book(app.page, book, console_pick=False, wait=3.0):
            print("✗ 打开作品失败"); sys.exit(1)

        # ★ 用户要求（2026-10-04）：一章一章边建边跑，不一次性预建所有章节。
        #   缺章由 ai_batch_chapters 循环内逐章 ensure_chapter(no) 处理。

        r = AI.ai_batch_chapters(
            app.page,
            start=start, end=end,
            plot=plot, plot_for=plot_for,
            gen_model="细腻版", gen_associate="正常", relate_count=10,
            min_words=min_words, max_words=max_words,
            max_retry=max_retry, best_effort=True, gen_timeout=300.0,
            do_review=not no_review,
            review_model=rv_model, review_card=rv_card,
            review_card_hint=AI.MODEL_CARD_HINT.get(rv_card, ""),
            review_associate=rv_assoc,
            review_req=rv_req,
            review_instruction=rv_instr,
            review_done_timeout=rv_timeout,
            replace=do_replace, select_all=True,
            auto_new=do_new,
            stop_on_fail=stop_on_fail)
        sys.exit(0 if r["ok"] == r["total"] else 1)
