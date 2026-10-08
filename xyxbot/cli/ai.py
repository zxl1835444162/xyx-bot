"""续写类命令：ai（单章续写）/ auto（一条龙）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations


import sys

__all__ = ["cmd_ai", "cmd_auto"]


def cmd_ai() -> None:
    """AI 续写正文。

    用法:
        python main.py ai <作品名> [--plot "剧情"] [--template "根据 #1 续写"]
                           [--chapter N] [--project xx.novel.json] [--index N]
                           [--shortcut "强盛集团云霄"]
                           [--model 细腻版] [--assoc 正常] [--relate 10] [--go]
                           [--auto-accept] [--min-words 2100] [--max-words 2300]
                           [--max-retry 5]

    说明:
        - 不带 --go 只把弹窗填好，不点「开始 AI 续写」（安全预览）
        - ★ 会先自动打开作品，再点「AI续写正文」
        - --index N：站点上有同名作品时指定第几本（从 0 开始）
        - --shortcut "关键词"：★ 按文字定位选中「快捷选项」里的提示词
          （不记第几行，站点改版/顺序变动都不怕）
        - ★ --auto-accept：生成后按字数自动决策：
            字数 ∈ [min-words, max-words] → 点「采纳使用」
            不够 / 超了 → 点「重新生成」，循环直到达标
        - --min-words / --max-words / --max-retry：配合 --auto-accept 用
        - --template "..." + --project：把指令模板里的 #1 #2 替换成
          工程里对应章节你填的细纲（★ 推荐用法）
        - --chapter N + --project：只取该章（前缀+细纲+后缀），不带代号
        - --plot：直接给一段剧情文本，优先级最高
    """
    args = sys.argv[2:]
    if not args:
        print("用法: python main.py ai <作品名> [--plot 剧情] "
              "[--template '根据 #1 续写'] [--project x.json] [--go]")
        sys.exit(1)

    book = args[0]
    plot = ""
    chapter = None
    project = ""
    template = ""
    model = "细腻版"
    assoc = "正常"
    relate = 10
    go = "--go" in args
    idx = None
    auto_accept = "--auto-accept" in args

    def _val(flag, default=None):
        if flag in args:
            i = args.index(flag)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    plot = _val("--plot", "")
    ch = _val("--chapter")
    chapter = int(ch) if ch and ch.isdigit() else None
    project = _val("--project", "")
    template = _val("--template", "")
    model = _val("--model", "细腻版")
    assoc = _val("--assoc", "正常")
    rl = _val("--relate", "10")
    relate = int(rl) if rl.isdigit() else 10
    ix = _val("--index", "")
    idx = int(ix) if ix and ix.lstrip("-").isdigit() else None
    shortcut = _val("--shortcut", "")

    mw = _val("--min-words", "2100")
    min_words = int(mw) if mw.isdigit() else 2100
    xw = _val("--max-words", "2300")
    max_words = int(xw) if xw.isdigit() else 2300
    mr = _val("--max-retry", "5")
    max_retry = int(mr) if mr.isdigit() else 5

    # ★ 优先：--template（短代号指令模板）
    if not plot and project and template:
        from xyxbot import novel as N
        proj = N.NovelProject.open(project)
        chk = proj.check_template(template)
        if chk["unknown"]:
            print("✗ 指令里有不存在的代号："
                  + " ".join(f"#{n}" for n in chk["unknown"])
                  + f"（共 {len(proj.chapters)} 章）")
            sys.exit(1)
        if chk["empty"]:
            print("⚠ 这些章还没填细纲（会用原文兜底）："
                  + " ".join(f"#{n}" for n in chk["empty"]))
        plot = proj.render_template(template)
        used = " ".join(f"#{n}" for n in chk["used"]) or "（无代号）"
        print(f"[ai] 指令模板 {used} → {len(plot)} 字")
    # 次选：--chapter N（单章渲染）
    elif not plot and project and chapter:
        from xyxbot import novel as N
        proj = N.NovelProject.open(project)
        c = proj.find(chapter)
        if c:
            plot = proj.render(c)
            print(f"[ai] 取自工程 {c.code}，共 {len(plot)} 字")

    from xyxbot.app import App
    from xyxbot import books as B
    from xyxbot import ai as AI

    with App(headless=False) as app:
        if not B.open_book(app.page, book, console_pick=(idx is None),
                           index=idx, wait=3.0):
            print("✗ 打开作品失败")
            sys.exit(1)
        ok = AI.ai_continue(app.page, plot=plot, model=model, associate=assoc,
                            relate_count=relate, shortcut=shortcut, start=go,
                            auto_accept=auto_accept, min_words=min_words,
                            max_words=max_words, max_retry=max_retry)
    sys.exit(0 if ok else 1)



def cmd_auto() -> None:
    """★ 一条龙：AI 续写 → 采纳 → 关弹窗 → 等正文 → AI 审稿 → 替换。

    用法:
        python main.py auto <作品名> [--plot "后续剧情"] [--chapter 第2章]
                             [--min 100] [--max 5000] [--no-retry]
                             [--rv-req "强盛集团云霄拯救过稿计划"]
                             [--rv-card 智慧版-6A] [--rv-assoc 正常]
                             [--rv-instruction "提示词…"]
                             [--no-review] [--no-replace] [--rv-timeout 600]

    说明:
        - ★ 这是把「AI续写正文」和「AI审稿」**串起来**跑，中间不用人工干预
        - ★ 字数区间默认很宽（100~5000）且**不重试**，尽量一次过
        - --no-review：只跑到续写 + 采纳完成（不审稿）
        - --rv-instruction：审稿的追加提示词（支持多行）
        - 衔接处会自动关掉续写弹窗（模态会拦点击）并等正文写入
    """
    args = sys.argv[2:]
    if not args:
        print("用法: python main.py auto <作品名> [--plot '后续剧情'] "
              "[--min 100 --max 5000] [--rv-req '关键词']")
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
        return int(v) if v and v.isdigit() else default

    plot = _val("--plot", "")
    chapter = _val("--chapter", "")
    min_words = _int("--min", 100)
    max_words = _int("--max", 5000)
    max_retry = _int("--retry", 0)
    no_review = "--no-review" in args
    do_replace = "--no-replace" not in args
    rv_req = _val("--rv-req", "")
    rv_card = _val("--rv-card", "智慧版-6A")
    rv_model = _val("--rv-model", "智慧版")
    rv_assoc = _val("--rv-assoc", "正常")
    rv_instr = _val("--rv-instruction", "")
    rv_timeout = _int("--rv-timeout", 600)
    ix = _val("--index", "")
    idx = int(ix) if ix and ix.lstrip("-").isdigit() else None
    # ★★ 是否先做「流程准备」（打开网站 → 登录 → 保存 cookie/缓存）
    #    --prepare     = 强制先准备
    #    --no-prepare  = 跳过准备（默认：有登录态就跳过，没有才准备）
    do_prepare = "--prepare" in args
    no_prepare = "--no-prepare" in args

    from xyxbot.app import App
    from xyxbot import books as B
    from xyxbot import ai as AI
    from xyxbot import login as L

    with App(headless=False) as app:
        # ===== ★ 阶段 0：流程准备（一条龙之前）=====
        if do_prepare or not no_prepare:
            st = L.is_ready()
            if do_prepare or not st["ok"]:
                print(f"\n[auto] 流程准备：{st['message']}")
                pr = L.prepare_session(app, save=True, auto=True,
                                       wait_seconds=0, interactive=True)
                if not pr["ok"]:
                    print(f"[auto] ✗ 准备未完成：{pr['message']}")
                    sys.exit(1)
                print("[auto] ✓ 准备就绪，开始一条龙")
            else:
                print(f"\n[auto] 已有登录态，跳过准备（{st['message']}）")

        if not B.open_book(app.page, book, console_pick=(idx is None),
                           index=idx, wait=3.0):
            print("✗ 打开作品失败")
            sys.exit(1)
        # ★ 根因修复：明确传 chapter（留空=第1章），避免切到「最新章」写错章节
        chapter = chapter or "第1章"
        r = AI.ai_auto_chapter(
            app.page,
            plot=plot, chapter=chapter, gen_model="细腻版", gen_associate="正常",
            relate_count=10,
            min_words=min_words, max_words=max_words,
            max_retry=max_retry,
            gen_timeout=300.0,
            close_dialog=True, settle=2.0,
            do_review=not no_review,
            review_model=rv_model, review_card=rv_card,
            review_card_hint=AI.MODEL_CARD_HINT.get(rv_card, ""),
            review_associate=rv_assoc,
            review_req=rv_req,
            review_instruction=rv_instr,
            review_done_timeout=rv_timeout,
            replace=do_replace, select_all=True)
        ok = bool(r.get("review"))
        sys.exit(0 if ok else 1)
