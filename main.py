"""命令行入口。

架构参考 novel-publisher-mac：
    src/platforms/   平台适配器注册表（一个站点一个类）
    src/tasks/       任务注册表（一个流程一个函数）
    src/app.py       App 主类，把浏览器 / 平台 / 任务串起来

常用命令：
    python main.py login        登录一次，保存登录态（之后免登录）
    python main.py session      查看登录态详情
    python main.py check        检查登录态是否有效
    python main.py diag         诊断登录态（排查"为什么没记录到 cookie"）
    python main.py recon        侦察页面，打印可见元素（写选择器用）
    python main.py logout       清除登录态
    python main.py books        列出作品页上的所有作品（带 ID）
    python main.py open <名字>  打开指定作品（同名可加 --index N）
    python main.py ai <作品名>  AI 续写正文（细腻版 + 联想正常 + 最近10章）
    python main.py review <作品名>  AI 审稿（智慧版-6A + 联想正常 + 指定审稿要求）
    python main.py tasks        列出所有已注册任务
    python main.py platforms    列出所有已注册平台
    python main.py run <任务名>  执行指定任务
    python main.py studio       快捷：登录并进创作台
    python main.py browsers     检测本机可用浏览器
"""

from __future__ import annotations

import sys

# ★★ 必须在任何 print 之前执行：Windows 上输出被重定向到文件/管道时，
#   Python 会用系统代码页(GBK)，而日志里的 ⚠/✓ 不在 GBK 里 →
#   `python main.py batch > log.txt` 会直接崩掉（实测）。
from xyxbot.console import enable_utf8

enable_utf8()

from xyxbot import config as C


# ---------------------------------------------------------------- 命令实现

def cmd_login() -> None:
    from xyxbot.app import App
    from xyxbot.login import ensure_login

    with App(headless=False) as app:
        ok = ensure_login(app)
    print("\n登录态已保存，下次启动无需再次登录 ✓" if ok else "\n未取得登录态 ✗")
    sys.exit(0 if ok else 1)


def cmd_session() -> None:
    """查看登录态详情。"""
    from xyxbot import session as S

    if not S.exists():
        print("尚未保存登录态。执行 `python main.py login` 登录一次即可。")
        sys.exit(1)

    info = S.describe()
    print("登录态详情")
    print("-" * 40)
    print(f"  保存时间 : {info['saved_at']}")
    print(f"  已过时长 : {S.age_text()}")
    print(f"  Cookie   : {info['cookies']} 条")
    print(f"  文件大小 : {info['size']}")
    print(f"  文件路径 : {info['path']}")
    if info.get("account"):
        print(f"  登录账号 : {info['account']}")


def cmd_check() -> None:
    from xyxbot.app import App
    from xyxbot import login as L

    with App(headless=False) as app:
        ok = L.verify_session(app)
    sys.exit(0 if ok else 1)


def cmd_recon() -> None:
    from xyxbot.app import App

    with App(headless=False) as app:
        app.run_task("侦察页面")


def cmd_logout() -> None:
    from xyxbot import session as S

    S.clear()
    print("[login] 本地登录态已清除，下次使用需重新登录")


def cmd_tasks() -> None:
    from xyxbot.tasks import list_task_names

    print("已注册任务：")
    for n in list_task_names():
        print("  •", n)


def cmd_platforms() -> None:
    from xyxbot.platforms import all_platforms

    print("已注册平台：")
    for name, p in all_platforms().items():
        print(f"  • {name}  {p.url}")
        if p.login_hint:
            print(f"      登录方式: {p.login_hint}")


def cmd_run() -> None:
    if len(sys.argv) < 3:
        print("用法: python main.py run <任务名>")
        print("可用任务见: python main.py tasks")
        sys.exit(1)
    from xyxbot.app import App

    with App(headless=False) as app:
        ok = app.run_task(sys.argv[2])
    sys.exit(0 if ok else 1)


def cmd_studio() -> None:
    from xyxbot.app import App

    with App(headless=False) as app:
        app.run_platform("星月写作")


def cmd_browsers() -> None:
    from xyxbot.browser_detector import test_browser_detection

    test_browser_detection()


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


def cmd_selftest() -> None:
    """环境自检：检查 tkinter / 数据目录 / Playwright / 浏览器内核，
    并且**真的把界面构造一遍**（打包版排障和 CI 验证都靠它）。

    `--no-ui`     跳过界面冒烟，只做环境检查
    `--window`    强制做「窗口真的显示出来了吗」的探测（会显示窗口）
    `--no-window` 强制不做（CI 环境自动关闭）
    """
    from xyxbot.selftest import run_selftest

    wp = None
    if "--window" in sys.argv:
        wp = True
    elif "--no-window" in sys.argv:
        wp = False
    sys.exit(run_selftest(smoke_ui="--no-ui" not in sys.argv, window_probe=wp))


def cmd_diag() -> None:
    """诊断登录态：排查「为什么没记录到 cookie」。"""
    import runpy

    from xyxbot import config as C

    # ★ 打包（.app / .exe）之后，开发期脚本没被打进去，直接 run_path 会报
    #   FileNotFoundError。这里先说清楚。
    script = C.ROOT / "tools" / "diag" / "diag_login.py"
    if not script.exists():
        print("diag 是开发期脚本（tools/diag/diag_login.py），打包版里没有它。")
        print("请改用：python main.py session   查看登录态详情")
        sys.exit(2)

    sys.argv = ["diag_login.py"]
    runpy.run_path(str(script), run_name="__main__")


COMMANDS = {
    "login": cmd_login,
    "session": cmd_session,
    "prepare": cmd_prepare,
    "check": cmd_check,
    "diag": cmd_diag,
    "selftest": cmd_selftest,
    "recon": cmd_recon,
    "logout": cmd_logout,
    "books": cmd_books,
    "open": cmd_open,
    "ai": cmd_ai,
    "review": cmd_review,
    "auto": cmd_auto,
    "batch": cmd_batch,
    "tasks": cmd_tasks,
    "platforms": cmd_platforms,
    "run": cmd_run,
    "studio": cmd_studio,
    "browsers": cmd_browsers,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("可用命令:", ", ".join(COMMANDS))
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
