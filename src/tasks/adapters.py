"""任务适配器：把具体业务函数注册进任务注册表。

每个任务函数签名统一为 func(app)，app 是 App 实例（提供 browser / log）。
照着下面的样式往下加。
"""

from __future__ import annotations

from . import register_task


@register_task("打开创作台", threaded=False)
def open_studio(app):
    """登录并进入创作台，截图留档。

    有已保存的登录态就直接复用，不会被要求重新登录。
    """
    from src.platforms import get_platform

    plat = get_platform("星月写作")
    return plat.run(app)


@register_task("登录星月账号", threaded=False)
def login_site(app):
    """登录一次星月写作，成功后自动记住登录态（以后免登录）。

    会打开浏览器：若已有有效登录态则秒过；
    否则等你在浏览器里扫码或输账号密码 —— **不限时**，
    登录好了程序自己会检测到（UI 上也可以点「我已登录，立即保存」）。
    """
    from src import login as L
    from src import session as S

    if S.exists():
        info = S.describe()
        print(f"发现已保存的登录态（{info['saved_at']}，{info['cookies']} 条 cookie）")

    ok = L.ensure_login(app, wait_seconds=0)   # 0 = 不限时
    if ok:
        print("登录态已就绪 ✓  下次启动无需再次登录")
    else:
        print("未取得登录态 ✗")
    return ok


@register_task("流程准备（打开网站+保存登录态）", threaded=False)
def prepare_session_task(app):
    """★ 所有流程开始之前的准备动作。

    做三件事：
      ① 打开网站（自动注入已保存的登录态 → 多数情况直接是「已登录」）
      ② 没登录/过期 → 自动登录（环境变量）→ 再不行 → 人工扫码
      ③ ★ 把 cookie + localStorage 存到 artifacts/storage/state.json

    跑完这一次之后，直接点「续写+审稿一条龙」即可，无需重复登录。
    """
    from src import login as L

    r = L.prepare_session(app, save=True, auto=True,
                          wait_seconds=0, interactive=True)
    print(f"准备结果：{'✓ 就绪' if r['ok'] else '✗ 未就绪'} · "
          f"{r['cookies']} 条 cookie · {r['message']}")
    return r["ok"]


@register_task("校验登录态", threaded=False)
def check_session(app):
    """打开站点，确认保存的登录态现在还有效。"""
    from src import login as L

    return L.verify_session(app)


@register_task("打开作品", threaded=False)
def open_book_task(app):
    """在作品页按名字打开一个已有作品。

    ⚠ 作品名可能重复，这里用 ID 精确定位。
    想改名/选别的作品，直接改下面的 BOOK_KEYWORD 即可。
    """
    from src import books as B

    BOOK_KEYWORD = "新建作品1"     # ← 改这里
    BOOK_INDEX = None             # ← 同名多个时填 0/1/2…

    page = app.page
    ok = B.open_book(page, BOOK_KEYWORD, index=BOOK_INDEX,
                     console_pick=True, wait=3.0)
    app.shot("open_book_result")
    return ok


@register_task("新建作品", threaded=False)
def create_book(app):
    """自动化第一步：在作品页找到并点击「+ 新建作品」入口卡，创建一个新作品。

    ⚠ 站点上已有作品可能叫「新建作品」「新建作品1」，
    用文字匹配会误点。这里用 `.create-card` 类精确锁定入口卡。
    """
    from src import books as B

    page = app.page
    ok = B.create_book(page, title="", book_type="novel", intro="")
    app.shot("create_book_result")
    if ok:
        print("新建作品流程完成 ✓")
    else:
        print("新建作品流程失败 ✗（看截图 artifacts/screenshots/）")
    return ok


@register_task("AI续写正文", threaded=False)
def ai_continue_task(app):
    """打开作品 → 点「AI续写正文」→ 选细腻版 + 联想能力正常 → 填剧情 → 关联最近10章 → 开始续写。

    ★ 剧情文本来源（按优先级）：
      1. 环境变量 XY_PLOT（一次性覆盖）
      2. XY_TEMPLATE + XY_PROJECT：短代号指令模板，如 "根据 #1 的细纲续写正文"
      3. 工程文件里第 N 章填写的剧情 + 前后缀（XY_PROJECT / XY_CHAPTER）
      4. 都不给就用下面的 DEFAULT_PLOT 兜底
    """
    import os
    from src import books as B
    from src import ai as AI

    BOOK = os.environ.get("XY_BOOK", "新建作品1")
    MODEL = os.environ.get("XY_MODEL", "细腻版")
    ASSOC = os.environ.get("XY_ASSOC", "正常")
    RELATE = int(os.environ.get("XY_RELATE", "10"))
    SHORTCUT = os.environ.get("XY_SHORTCUT", "")   # ★ 快捷选项关键词
    START = os.environ.get("XY_START", "0") == "1"
    # ★ 按字数自动采纳
    AUTO_ACCEPT = os.environ.get("XY_AUTO_ACCEPT", "0") == "1"
    MIN_WORDS = int(os.environ.get("XY_MIN_WORDS", "2100"))
    MAX_WORDS = int(os.environ.get("XY_MAX_WORDS", "2300"))
    MAX_RETRY = int(os.environ.get("XY_MAX_RETRY", "5"))
    DEFAULT_PLOT = "【本章细纲】主角发现关键线索，决定连夜行动。\n请据此续写正文，保持爽文节奏。"

    # --- 组织剧情文本 ---
    plot = os.environ.get("XY_PLOT", "")
    proj_path = os.environ.get("XY_PROJECT", "")
    template = os.environ.get("XY_TEMPLATE", "")
    ch_no = os.environ.get("XY_CHAPTER", "")

    # ★ 优先：指令模板（短代号 #1 #2 …）
    if not plot and proj_path and template:
        try:
            from src import novel as N
            proj = N.NovelProject.open(proj_path)
            chk = proj.check_template(template)
            if chk["unknown"]:
                print("[task] ✗ 指令里有不存在的代号："
                      + " ".join(f"#{n}" for n in chk["unknown"]))
                return False
            if chk["empty"]:
                print("[task] ⚠ 这些章还没填细纲（用原文兜底）："
                      + " ".join(f"#{n}" for n in chk["empty"]))
            plot = proj.render_template(template)
            used = " ".join(f"#{n}" for n in chk["used"]) or "（无代号）"
            print(f"[task] 指令模板 {used} → {len(plot)} 字")
        except Exception as e:
            print(f"[task] 读工程/渲染模板失败：{e}")

    # 次选：单章渲染
    if not plot and proj_path and ch_no:
        try:
            from src import novel as N
            proj = N.NovelProject.open(proj_path)
            ch = proj.find(ch_no)
            if ch:
                plot = proj.render(ch)
                print(f"[task] 从工程取「{ch.code}」剧情（{len(plot)} 字）")
        except Exception as e:
            print(f"[task] 读工程失败：{e}")

    if not plot:
        plot = DEFAULT_PLOT
        print("[task] 未指定剧情，使用默认占位剧情")

    page = app.page
    ok = B.open_book(page, BOOK, console_pick=True, wait=3.0)
    if not ok:
        print("[task] 打开作品失败 ✗")
        return False

    ok = AI.ai_continue(page, plot=plot, model=MODEL, associate=ASSOC,
                        relate_count=RELATE, shortcut=SHORTCUT, start=START,
                        auto_accept=AUTO_ACCEPT, min_words=MIN_WORDS,
                        max_words=MAX_WORDS, max_retry=MAX_RETRY)
    app.shot("ai_continue_result")
    print(f"[task] AI续写{'已触发' if ok and START else '准备就绪' if ok else '失败'} "
          f"（{MODEL} / 联想{ASSOC} / 最近{RELATE}章"
          + (f" / 提示词{SHORTCUT}" if SHORTCUT else "")
          + (f" / 自动采纳{MIN_WORDS}~{MAX_WORDS}字" if AUTO_ACCEPT else "")
          + "）")
    return ok


@register_task("AI审稿", threaded=False)
def ai_review_task(app):
    """打开作品 → 点「AI审稿」→ 智慧版-6A + 联想正常 → 选审稿要求 → 点「生成」。

    ★ 与「AI续写正文」的区别：
        - 审稿**不投喂剧情**，它审的是**页面上当前章的内容**（待审文本留空）。
        - 承载不同：续写=居中弹窗；审稿=**右侧抽屉**。
        - 开始按钮：续写=「开始 AI 续写」；审稿=「生成」。

    ★ 环境变量：
        XY_BOOK      作品名（默认 新建作品1）
        XY_RV_MODEL  模型分类（默认 智慧版）
        XY_RV_CARD   具体模型卡片（默认 智慧版-6A；分类≠卡片名）
        XY_RV_ASSOC  联想能力（默认 正常 = 0.7）
        XY_RV_REQ    审稿要求关键词（默认 强盛集团云霄拯救过稿计划）
        XY_RV_TAB    审稿要求 tab（默认 快捷选项）
        XY_RV_TEXT   待审文本（默认空 = 沿用页面自带当前章）
        XY_RV_CHAPTER 先打开的章节关键词（如「第2章」；留空=选第 1 个）
                      ★ 不打开章节的话正文区是空的，待审文本也是空的
        XY_RV_INSTRUCTION 追加指令（会拼成「指令 + 章节正文」一起送审）
        XY_RV_START  1 = 真的点「生成」
        XY_RV_WAIT   1 = 等生成完成（几分钟很正常）
        XY_RV_REPLACE 1 = 完成后点「替换 / 插入」落盘到正文（隐含 WAIT）
        XY_RV_SELECT_ALL 0 = 替换前**不**全选正文（默认 1 = 全选）
                      ★ 全选是必须的：不全选会变成「插入」→ 前后拼接
        XY_RV_TIMEOUT 等生成的最长秒数（默认 600）
    """
    import os
    from src import books as B
    from src import ai as AI

    BOOK = os.environ.get("XY_BOOK", "新建作品1")
    MODEL = os.environ.get("XY_RV_MODEL", "智慧版")
    CARD = os.environ.get("XY_RV_CARD", "智慧版-6A")
    ASSOC = os.environ.get("XY_RV_ASSOC", "正常")
    REQ = os.environ.get("XY_RV_REQ", "")
    TAB = os.environ.get("XY_RV_TAB", "快捷选项")
    TEXT = os.environ.get("XY_RV_TEXT", "")
    CHAPTER = os.environ.get("XY_RV_CHAPTER", "")
    INSTRUCTION = os.environ.get("XY_RV_INSTRUCTION", "")
    START = os.environ.get("XY_RV_START", "0") == "1"
    REPLACE = os.environ.get("XY_RV_REPLACE", "0") == "1"
    WAIT = os.environ.get("XY_RV_WAIT", "0") == "1" or REPLACE
    SELECT_ALL = os.environ.get("XY_RV_SELECT_ALL", "1") == "1"
    TIMEOUT = int(os.environ.get("XY_RV_TIMEOUT", "600"))

    page = app.page
    if not B.open_book(page, BOOK, console_pick=True, wait=3.0):
        print("[task] 打开作品失败 ✗")
        return False

    ok = AI.ai_review(page,
                      text=TEXT,
                      model=MODEL,
                      model_card_name=CARD,
                      model_card_hint=AI.MODEL_CARD_HINT.get(CARD, ""),
                      associate=ASSOC,
                      requirement=REQ,
                      req_tab=TAB,
                      instruction=INSTRUCTION,
                      open_chapter=CHAPTER,
                      start=START,
                      wait_done=WAIT,
                      done_timeout=TIMEOUT,
                      replace=REPLACE,
                      select_all=SELECT_ALL)
    app.shot("ai_review_result")
    got = AI.current_review_requirement(page) if ok else ""
    print(f"[task] AI审稿{'已完成' if ok and REPLACE else '已触发' if ok and START else '准备就绪' if ok else '失败'} "
          f"（{MODEL}→{CARD} / 联想{ASSOC}"
          + (f" / 审稿要求{REQ or '(不改)'}" if REQ else "")
          + (f" / 追加指令{len(INSTRUCTION)}字" if INSTRUCTION else "")
          + (f" / 章节[{CHAPTER}]" if CHAPTER else "")
          + (" / 已替换落盘" if REPLACE and ok else "")
          + "）")
    if got:
        print(f"[task] 当前审稿要求：{got}")
    return ok


@register_task("续写+审稿一条龙", threaded=False)
def auto_chapter_task(app):
    """★★ 串起来跑一章：AI 续写 → 采纳 → 关弹窗 → 等正文 → AI 审稿 → 替换。

    ★ 为什么需要它（用户 2026-10-03）：
        担心「生成完之后、与审稿开始之间」的状态 —— 这个衔接处确实易错：
          ① 采纳后续写弹窗**不自动关**，模态拦掉「AI审稿」的点击
          ② 正文写入编辑器有延迟，立刻审稿会读到空/旧正文
        本任务把这两步都处理掉了。

    ★ 环境变量：
        XY_BOOK        作品名（默认 新建作品1）
        XY_AUTO_PLOT   后续剧情文本（不填则用默认一句推进剧情）
        XY_AUTO_CHAPTER 先打开章节（如「第2章」；留空=选择第一个）
        XY_AUTO_MIN / XY_AUTO_MAX  采纳字数区间（默认 100 / 5000，故意放宽）
        XY_AUTO_RETRY  最多重试次数（默认 0 = 不重试）
        XY_RV_MODEL / XY_RV_CARD / XY_RV_ASSOC  审稿模型/卡片/联想
        XY_RV_REQ      审稿要求关键词
        XY_RV_INSTRUCTION  审稿追加提示词（支持多行）
        XY_RV_TIMEOUT  等审稿完成的最长秒数（默认 600）
        XY_AUTO_NO_REVIEW  1 = 只做续写，不审稿
        XY_AUTO_NO_REPLACE 1 = 审稿后不替换落盘
    """
    import os
    from src import books as B
    from src import ai as AI

    BOOK = os.environ.get("XY_BOOK", "新建作品1")
    PLOT = os.environ.get("XY_AUTO_PLOT", "继续推进剧情。")
    CHAPTER = os.environ.get("XY_AUTO_CHAPTER", "")
    MIN_W = int(os.environ.get("XY_AUTO_MIN", "100"))
    MAX_W = int(os.environ.get("XY_AUTO_MAX", "5000"))
    RETRY = int(os.environ.get("XY_AUTO_RETRY", "0"))
    RVMODEL = os.environ.get("XY_RV_MODEL", "智慧版")
    RVCARD = os.environ.get("XY_RV_CARD", "智慧版-6A")
    RVASSOC = os.environ.get("XY_RV_ASSOC", "正常")
    RVREQ = os.environ.get("XY_RV_REQ", "强盛集团云霄拯救过稿计划")
    RVINSTR = os.environ.get("XY_RV_INSTRUCTION", "")
    RVTIMEOUT = int(os.environ.get("XY_RV_TIMEOUT", "600"))
    NO_REVIEW = os.environ.get("XY_AUTO_NO_REVIEW", "0") == "1"
    NO_REPLACE = os.environ.get("XY_AUTO_NO_REPLACE", "0") == "1"

    page = app.page
    if not B.open_book(page, BOOK, console_pick=True, wait=3.0):
        print("[task] 打开作品失败 ✗")
        return False

    # ★ 根因修复：明确传 chapter（留空=第1章），避免切到「最新章」写错章节
    chapter = CHAPTER or "第1章"
    r = AI.ai_auto_chapter(
        page,
        plot=PLOT, chapter=chapter, gen_model="细腻版", gen_associate="正常",
        relate_count=10,
        min_words=MIN_W, max_words=MAX_W,
        max_retry=RETRY, gen_timeout=300.0,
        close_dialog=True, settle=2.0,
        do_review=not NO_REVIEW,
        review_model=RVMODEL, review_card=RVCARD,
        review_card_hint=AI.MODEL_CARD_HINT.get(RVCARD, ""),
        review_associate=RVASSOC,
        review_req=RVREQ,
        review_instruction=RVINSTR,
        review_done_timeout=RVTIMEOUT,
        replace=not NO_REPLACE, select_all=True)
    app.shot("auto_chapter_result")
    print(f"[task] 一条龙：续写 {'✓' if r.get('gen') else '✗'} / "
          f"正文 {r.get('body')} 字 / "
          f"审稿 {'✓' if r.get('review') else '✗'}")
    return bool(r.get("review"))


@register_task("批量跑章", threaded=False)
def batch_chapters_task(app):
    """★★ 批量跑章：第 start ~ end 章，逐章一条龙。

    ★ 环境变量：
        XY_BOOK          作品名（默认 新建作品1）
        XY_BATCH_FROM    起始章（默认 1）
        XY_BATCH_TO      结束章（默认 10）
        XY_BATCH_PLOT    固定剧情（若指定，则所有章用同一段；不指定则空）
        XY_BATCH_PROJECT 工程 .json 路径（含指令模板，支持 #@ 当前章占位符）
        XY_BATCH_NO_NEW  1 = 缺章不自动新建
        XY_BATCH_STOP    1 = 某章失败就停
        + 续写/审稿参数同「续写+审稿一条龙」（XY_AUTO_* / XY_RV_*）
    """
    import os
    from src import books as B
    from src import ai as AI

    BOOK = os.environ.get("XY_BOOK", "新建作品1")
    START = int(os.environ.get("XY_BATCH_FROM", "1"))
    END = int(os.environ.get("XY_BATCH_TO", "10"))
    PLOT = os.environ.get("XY_BATCH_PLOT", "")
    PROJ = os.environ.get("XY_BATCH_PROJECT", "")
    NO_NEW = os.environ.get("XY_BATCH_NO_NEW", "0") == "1"
    STOP = os.environ.get("XY_BATCH_STOP", "0") == "1"

    MIN_W = int(os.environ.get("XY_AUTO_MIN", "100"))
    MAX_W = int(os.environ.get("XY_AUTO_MAX", "5000"))
    RVMODEL = os.environ.get("XY_RV_MODEL", "智慧版")
    RVCARD = os.environ.get("XY_RV_CARD", "智慧版-6A")
    RVASSOC = os.environ.get("XY_RV_ASSOC", "正常")
    RVREQ = os.environ.get("XY_RV_REQ", "强盛集团云霄拯救过稿计划")
    RVINSTR = os.environ.get("XY_RV_INSTRUCTION", "")
    RVTIMEOUT = int(os.environ.get("XY_RV_TIMEOUT", "600"))

    plot_for = None
    if not PLOT and PROJ:
        from src.novel import NovelProject
        proj = NovelProject.open(PROJ)
        tpl = proj.instruction or "#@"
        print(f"[task] 指令模板：{tpl[:50]}…")
        plot_for = lambda no: proj.render_for_batch(no, template=tpl)

    page = app.page
    if not B.open_book(page, BOOK, console_pick=True, wait=3.0):
        print("[task] 打开作品失败 ✗")
        return False

    # ★ 用户要求（2026-10-04）：一章一章边建边跑，不一次性预建所有章节。

    r = AI.ai_batch_chapters(
        page,
        start=START, end=END, plot=PLOT, plot_for=plot_for,
        gen_model="细腻版", gen_associate="正常", relate_count=10,
        min_words=MIN_W, max_words=MAX_W,
        max_retry=0, best_effort=True, gen_timeout=300.0,
        do_review=True,
        review_model=RVMODEL, review_card=RVCARD,
        review_card_hint=AI.MODEL_CARD_HINT.get(RVCARD, ""),
        review_associate=RVASSOC,
        review_req=RVREQ,
        review_instruction=RVINSTR,
        review_done_timeout=RVTIMEOUT,
        replace=True, select_all=True,
        auto_new=not NO_NEW,
        stop_on_fail=STOP)
    print(f"[task] 批量跑章：{r['ok']}/{r['total']} 成功"
          + (f"，失败章 {r['failed']}" if r["failed"] else ""))
    return r["ok"] == r["total"]


@register_task("侦察页面", threaded=False)
def recon_page(app):
    """打印当前页面的可见交互元素，便于写选择器。"""
    from src import config as C

    page = app.page
    app.goto(C.SITE["entry"])
    app.sleep(3)
    print("标题:", page.title())
    print("URL :", page.url)
    print("\n--- 可见交互元素 ---")
    seen = set()
    for it in page.locator("a, button").all()[:150]:
        try:
            if not it.is_visible():
                continue
            txt = (it.inner_text(timeout=400) or "").strip().replace("\n", " ")
            if txt and txt not in seen and len(txt) < 30:
                seen.add(txt)
                print("  •", txt)
        except Exception:
            continue
    app.shot("recon")
    return True


# ---------------------------------------------------------------- 任务模板
# 复制下面这段写你自己的任务，然后跑 main.py 就能在列表里看到
#
# @register_task("我的任务", threaded=True)
# def my_task(app):
#     from src import actions as A
#     page = app.page
#     A.click(page, ["text=某个按钮"], label="某个按钮")
