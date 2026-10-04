"""AI 续写 / 审稿 / 一条龙 / 批量跑章（界面侧编排）。

从 ui/main_window.py 拆出的独立模块（架构改良阶段二）。

★ 依赖（由 MRO 解析）：_collect_notes / _save_ws / _get_instruction /
  _set_preview（chapters、config_io）、_ensure_page / _run_guarded（窗口）。
"""

from __future__ import annotations


from ..defaults import (
    DEFAULT_MAX_RETRY,
    DEFAULT_MAX_WORDS,
    DEFAULT_MIN_WORDS,
    DEFAULT_REVIEW_ASSOCIATE,
    DEFAULT_REVIEW_CARD,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_REVIEW_TAB,
    DEFAULT_REVIEW_TIMEOUT,
)


class AiFlowMixin:
    """AI 流程（界面侧）。"""

    def _ai_go(self):
        """一键：打开作品 → 用「指令模板」渲染出文本 → AI 续写。"""
        import threading

        if self._project is None:
            self.log("还没有分章，先选文件分章", "warn")
            return
        book = self._ai_book_entry.get().strip()
        if not book:
            self.log("请填写「作品名称」（站点上那本书的名字）", "warn")
            return
        # ★ 同名多本时指定第几本
        _idx, ok = self._parse_book_index()
        if not ok:
            return

        # ★ 快捷选项（提示词）关键词
        shortcut = self._ai_shortcut_entry.get().strip()
        if shortcut:
            self.log(f"快捷选项将按关键词定位：{shortcut}", "info")

        # ★ 按字数自动采纳参数
        auto_accept = bool(self._ai_auto_var.get())

        def _int_or(entry, default):
            t = entry.get().strip()
            return int(t) if t.isdigit() else default

        min_words = _int_or(self._ai_min_entry, DEFAULT_MIN_WORDS)
        max_words = _int_or(self._ai_max_entry, DEFAULT_MAX_WORDS)
        max_retry = _int_or(self._ai_retry_entry, DEFAULT_MAX_RETRY)
        if auto_accept and min_words > max_words:
            self.log(f"字数区间写反了（{min_words}~{max_words}），已自动交换", "warn")
            min_words, max_words = max_words, min_words
        if auto_accept:
            self.log(f"自动采纳已开启：{min_words}~{max_words} 字，"
                     f"最多重生成 {max_retry} 次", "info")

        # ① 回写细纲 → 取指令模板
        self._collect_notes()
        self._project.instruction = self._get_instruction()
        tpl = self._project.instruction
        if not tpl:
            self.log("「指令模板」是空的，先写点什么（比如 #1）", "warn")
            return

        # ② 校验代号
        chk = self._project.check_template(tpl)
        if chk["unknown"]:
            self.log("✗ 指令里有不存在的代号："
                     + " ".join(f"#{n}" for n in chk["unknown"])
                     + f"（共 {len(self._project.chapters)} 章）", "err")
            return
        if chk["empty"]:
            self.log("⚠ 这些章还没填细纲，会用原文兜底："
                     + " ".join(f"#{n}" for n in chk["empty"]), "warn")

        # ③ 渲染
        # ★★ 根因修复：原来没传 `current=` → 模板里的 `#@`（以及 {{当前章}}/
        #    {{本章}}/#当前章）会**原样**送进站点，而 UI 文案一直在教用户
        #    「#@ = 当前章」。现在按「续写到第几章」下拉解析当前章。
        cur_no = self._resolve_current_chapter_no()
        if cur_no is not None and self._project.CUR_RE.search(tpl):
            self.log(f"[ai] 「当前章」占位符 → 第{cur_no}章", "info")
        plot = self._project.render_template(tpl, current=cur_no)
        if not plot.strip():
            self.log("指令模板渲染出来是空的，检查一下 #N 写对没", "err")
            return
        self._set_preview(plot, f"✓ 待发送（{len(plot)} 字）")

        used = " ".join(f"#{n}" for n in chk["used"]) or "（无代号）"
        self.log(f"一键续写：作品《{book}》 用 {used} 合成 {len(plot)} 字", "brand")
        self._save_ws(silent=True)      # ★ 记住这次配置
        self.status.set_status("AI 续写中…", "warn")
        if hasattr(self._btn_ai_go, "set_text"):
            self._btn_ai_go.set_text("续写中…")

        def worker():
            try:
                from src import books as B
                from src import ai as AI
                page = self._ensure_page()   # 复用同一个浏览器页（线程绑定）

                # ★ 必须先打开作品，否则停在首页，找不到「AI续写正文」按钮
                self.after(0, self.log, f"打开作品《{book}》…", "brand")
                if not B.open_book(page, book, console_pick=False,
                                   index=self._ai_book_index, wait=3.0):
                    self.after(0, self._on_ai_fail,
                               f"打开作品「{book}」失败——"
                               f"确认这本书存在（同名多本请填「作品名称」时加 --index）")
                    return
                self.after(0, self.log, "✓ 已进入作品编辑器", "ok")

                ok = AI.ai_continue(page, plot=plot, model="细腻版",
                                    associate="正常", relate_count=10,
                                    shortcut=shortcut,
                                    start=True,
                                    auto_accept=auto_accept,
                                    min_words=min_words,
                                    max_words=max_words,
                                    max_retry=max_retry)
                # ★ 取回字数决策细节（各轮字数 / 结果说明）
                detail = ""
                try:
                    d = AI.LAST_DECISION
                    if d:
                        detail = f"{d.get('reason', '')}"
                        if d.get("tries"):
                            detail += f"；各轮字数 {d['tries']}"
                except Exception:
                    pass
                self.after(0, self._on_ai_done, ok, used, detail)
            except Exception as e:
                self.after(0, self._on_ai_fail, str(e))

        self.session.submit(worker)

    def _on_ai_done(self, ok, used, detail=""):
        if hasattr(self._btn_ai_go, "set_text"):
            self._btn_ai_go.set_text("一键续写")
        if ok:
            self.log(f"✓ 已触发 AI 续写（{used}）", "ok")
            self.status.set_status("AI 续写已触发", "ok")
        else:
            self.log(f"✗ AI 续写失败（{used}），看 artifacts/screenshots/", "err")
            self.status.set_status("AI 续写失败", "err")
        # ★ 显示「按字数自动决策」的细节
        if detail:
            self.log(f"  字数决策：{detail}", "brand")

    def _on_ai_fail(self, msg):
        if hasattr(self._btn_ai_go, "set_text"):
            self._btn_ai_go.set_text("一键续写")
        self.log(f"AI 续写异常：{msg}", "err")
        self.status.set_status("AI 续写异常", "err")

    # -------------------------------------------------- AI 审稿

    def _ai_review_go(self):
        """一键：打开作品 → 打开「AI审稿」抽屉 → 选模型/联想/审稿要求 → 点「生成」。

        ★ 与 `_ai_go`（续写）的区别：
            - 续写要**渲染指令模板**当剧情投喂；审稿**不需要**，
              它审的是**页面上当前章的内容**（待审文本留空 = 沿用）。
            - 续写点「开始 AI 续写」；审稿点「生成」。
            - 承载不同：续写=居中弹窗；审稿=**右侧抽屉**。
        """
        import threading

        book = self._ai_book_entry.get().strip()
        if not book:
            self.log("请填写「作品名称」（站点上那本书的名字）", "warn")
            return
        _idx, ok = self._parse_book_index()
        if not ok:
            return

        # 读参数
        model = (self._rv_model_entry.get().strip()
                 or DEFAULT_REVIEW_MODEL)
        card = (self._rv_card_entry.get().strip()
                or DEFAULT_REVIEW_CARD)
        assoc = (self._rv_assoc_entry.get().strip()
                 or DEFAULT_REVIEW_ASSOCIATE)
        req = self._rv_req_entry.get().strip()
        # ★★ 追加指令（待审文本是自带章节正文的，这里再补一段提示词）
        instruction = self._rv_instr_text.get("1.0", "end").strip()
        # ★ 先打开章节
        chapter = self._rv_chapter_entry.get().strip()
        # ★ 审稿流程开关
        wait_done = bool(self._rv_wait_var.get())
        do_replace = bool(self._rv_replace_var.get())
        select_all = bool(self._rv_select_all_var.get())
        tout = self._rv_timeout_entry.get().strip()
        done_timeout = int(tout) if tout.isdigit() else DEFAULT_REVIEW_TIMEOUT
        if do_replace and not wait_done:
            self.log("「替换 / 插入」需要先等生成完成，已自动勾上「等生成完成」",
                     "warn")
            wait_done = True
            self._rv_wait_var.set(True)

        self.log(f"AI审稿：作品《{book}》 模型 {model}→{card}，"
                 f"联想 {assoc}，审稿要求「{req or '(不改)'}」"
                 + (f"，追加提示词 {len(instruction)} 字"
                    f"（{instruction.count(chr(10)) + 1} 行）"
                    if instruction else "")
                 + (f"，先开章节「{chapter}」" if chapter else "")
                 + (f"，等生成 {done_timeout}s" if wait_done else "")
                 + ("，完成后替换落盘" if do_replace else ""), "brand")
        self._save_ws(silent=True)      # ★ 记住这次配置
        self.status.set_status("AI 审稿中…", "warn")
        if hasattr(self._btn_ai_review, "set_text"):
            self._btn_ai_review.set_text("审稿中…")

        def worker():
            try:
                from src import books as B
                from src import ai as AI
                page = self._ensure_page()   # 复用同一个浏览器页（线程绑定）

                self.after(0, self.log, f"打开作品《{book}》…", "brand")
                if not B.open_book(page, book, console_pick=False,
                                   index=self._ai_book_index, wait=3.0):
                    self.after(0, self._on_review_done, False,
                               "打开作品失败——确认这本书存在")
                    return
                self.after(0, self.log, "✓ 已进入作品编辑器", "ok")

                ok = AI.ai_review(page,
                                  model=model,
                                  model_card_name=card,
                                  model_card_hint=AI.MODEL_CARD_HINT.get(card, ""),
                                  associate=assoc,
                                  requirement=req,
                                  req_tab=DEFAULT_REVIEW_TAB,
                                  instruction=instruction,
                                  open_chapter=chapter,
                                  start=True,
                                  wait_done=wait_done,
                                  done_timeout=done_timeout,
                                  replace=do_replace,
                                  select_all=select_all)
                # ★ 回读实际选中的审稿要求
                got = ""
                try:
                    got = AI.current_review_requirement(page)
                except Exception:
                    pass
                self.after(0, self._on_review_done, ok, got,
                           do_replace and wait_done)
            except Exception as e:
                self.after(0, self._on_review_done, False, str(e))

        self.session.submit(worker)

    def _on_review_done(self, ok, info="", replaced=False):
        if hasattr(self._btn_ai_review, "set_text"):
            self._btn_ai_review.set_text("AI审稿")
        if ok:
            tail = "，已替换落盘到正文" if replaced else "（已触发生成）"
            self.log(f"✓ AI 审稿完成{tail}（审稿要求：{info[:40]}）", "ok")
            self.status.set_status("AI 审稿完成", "ok")
        else:
            self.log(f"✗ AI 审稿失败：{info}（看 artifacts/screenshots/）", "err")
            self.status.set_status("AI 审稿失败", "err")

    # -------------------------------------------------- ★ 续写 + 审稿 一条龙

    def _ai_both_go(self):
        """★★ 一键走完一章：AI 续写 → 采纳 → 关弹窗 → 等正文 → AI 审稿 → 替换。

        ★ 为什么要串联（用户 2026-10-03）：
            「一章生成完了，我有些担心**生成完之后、与审稿开始之间的状态**」
            —— 这个衔接处确实最容易出问题：
              ① 采纳后续写弹窗**不自动关**，模态会拦掉「AI审稿」的点击
              ② 正文写入编辑器有延迟，立刻审稿会读到空/旧正文
            串联函数 `AI.ai_auto_chapter()` 把这两步都处理掉了。

        ★ 字数区间（2026-10-04 修正）：
            原实现把区间写死成 100~5000 + `max_retry=0`，理由是
            「让字数限制宽一点，避免重试」。但这等于**字数限制完全失效**
            （任何字数都算达标），与用户「2700 竟然过了 2100-2300」的
            报障直接冲突。现在改为**严格使用界面上设置的区间与重试次数**。
        """
        import threading

        book = self._ai_book_entry.get().strip()
        if not book:
            self.log("请填写「作品名称」（站点上那本书的名字）", "warn")
            return
        _idx, ok = self._parse_book_index()
        if not ok:
            return

        # ---- ① 剧情：跟「一键续写」一样，来自指令模板渲染 ----
        if self._project is None:
            self.log("还没有分章，先选文件分章", "warn")
            return
        self._collect_notes()
        self._project.instruction = self._get_instruction()
        tpl = self._project.instruction
        if not tpl:
            self.log("「指令模板」是空的，先写点什么（比如 #1）", "warn")
            return
        chk = self._project.check_template(tpl)
        if chk["unknown"]:
            self.log("✗ 指令里有不存在的代号："
                     + " ".join(f"#{n}" for n in chk["unknown"]), "err")
            return
        # ★★ 同上：必须传 current，否则 `#@` 会原样送进站点
        plot = self._project.render_template(
            tpl, current=self._resolve_current_chapter_no())
        self._set_preview(plot, f"✓ 待发送（{len(plot)} 字）")

        # ---- ② 续写参数 ----
        shortcut = self._ai_shortcut_entry.get().strip()

        def _int_or(entry, default):
            t = entry.get().strip()
            return int(t) if t.isdigit() else default

        # ★★ 修正（2026-10-04 用户报「2700 字竟然过了 2100-2300 的限制」）：
        #    原实现把区间写死成 100~5000（`... , 100) or 100`），
        #    重试次数更是硬编码 `max_retry=0`，理由写在注释里是
        #    「让字数限制宽一点，避免重试」。
        #    但这两条叠加 = **字数限制完全失效**：只生成一轮 + 兜底必采纳
        #    ⇒ 任何字数都算"达标"。用户就是这样被 2700 字蒙过去的。
        #    现在：**严格使用界面上的区间与重试次数**。
        min_words = _int_or(self._ai_min_entry, DEFAULT_MIN_WORDS)
        max_words = _int_or(self._ai_max_entry, DEFAULT_MAX_WORDS)
        max_retry = _int_or(self._ai_retry_entry, DEFAULT_MAX_RETRY)
        if min_words > max_words:
            min_words, max_words = max_words, min_words
        gen_timeout = 300.0

        # ---- ③ 审稿参数 ----
        rv_model = self._rv_model_entry.get().strip() or DEFAULT_REVIEW_MODEL
        rv_card = self._rv_card_entry.get().strip() or DEFAULT_REVIEW_CARD
        rv_assoc = (self._rv_assoc_entry.get().strip()
                    or DEFAULT_REVIEW_ASSOCIATE)
        rv_req = self._rv_req_entry.get().strip()
        rv_instr = self._rv_instr_text.get("1.0", "end").strip()
        rv_chapter = self._rv_chapter_entry.get().strip()
        rv_replace = bool(self._rv_replace_var.get())
        rv_select_all = bool(self._rv_select_all_var.get())
        rv_tout = self._rv_timeout_entry.get().strip()
        rv_timeout = int(rv_tout) if rv_tout.isdigit() else DEFAULT_REVIEW_TIMEOUT
        auto_close = bool(self._auto_both_close_var.get())

        self.log("★ 一条龙：续写 → 采纳 → 关弹窗 → 审稿 → 替换", "brand")
        # ★ 修正（2026-10-05）：原来这条日志写死「（不重试）」，
        #   但实际传下去的是 max_retry（界面上的值），文案与行为不符、会误导。
        self.log(f"  续写：细腻版/正常，字数 {min_words}~{max_words}"
                 f"（最多重生成 {max_retry} 次），剧情 {len(plot)} 字", "dim")
        self.log(f"  审稿：{rv_model}→{rv_card}，要求「{rv_req or '(不改)'}」"
                 + (f"，提示词 {len(rv_instr)} 字" if rv_instr else "")
                 + (f"，先开章节「{rv_chapter}」" if rv_chapter else ""),
                 "dim")
        self._save_ws(silent=True)
        self.status.set_status("一条龙执行中…", "warn")
        if hasattr(self._btn_ai_both, "set_text"):
            self._btn_ai_both.set_text("执行中…")

        def worker():
            try:
                from src import books as B
                from src import ai as AI
                from src import login as L
                page = self._ensure_page()

                # ★ 阶段零：流程准备（打开网站 → 保存 cookie/缓存）
                #   没登录态才做；已有则跳过（不打断用户节奏）
                st = L.is_ready()
                if not st["ok"]:
                    self.after(0, self.log,
                               "尚未准备：先打开网站并保存登录态…", "warn")
                    pr = L.prepare_session(
                        self._app, save=True, auto=True,
                        wait_seconds=0, interactive=True)
                    if not pr["ok"]:
                        self.after(0, self._on_both_done, None,
                                   f"准备未完成：{pr['message']}")
                        return
                    self.after(0, self.log, "✓ 准备就绪", "ok")
                    self.after(0, self._prepare_refresh)
                else:
                    self.after(0, self.log, f"已有登录态，跳过准备（{st['age']}）",
                               "dim")

                self.after(0, self.log, f"打开作品《{book}》…", "brand")
                if not B.open_book(page, book, console_pick=False,
                                   index=self._ai_book_index, wait=3.0):
                    self.after(0, self._on_both_done, None,
                               "打开作品失败——确认这本书存在")
                    return
                self.after(0, self.log, "✓ 已进入作品编辑器", "ok")

                # ★★ 先开章节（用户填了关键词就用，留空默认「第1章」）。
                #    ★ 根因修复（2026-10-03）：之前这里 `rv_chapter` 留空就不开章，
                #      然后 ai_auto_chapter 阶段零遇到正文为空时会无参 open_chapter
                #      → 打开「倒序列表第0个 = 最新章」，把第1章的内容写进了第4章。
                #      现在：明确传 chapter，留空 = 第1章，绝不切到「最新章」。
                chapter = rv_chapter or "第1章"
                self.after(0, self.log,
                           f"打开章节「{chapter}」…", "brand")

                r = AI.ai_auto_chapter(
                    page,
                    # 续写
                    plot=plot, chapter=chapter,
                    gen_model="细腻版",
                    gen_associate="正常", relate_count=10,
                    shortcut=shortcut,
                    min_words=min_words, max_words=max_words,
                    # ★★ 修正（2026-10-04）：原来硬编码 `max_retry=0`
                    #    ⇒ 一章只生成一轮，字数不达标也直接过。
                    #    改为真正使用界面上的「最多重生成」。
                    max_retry=max_retry, best_effort=True,
                    gen_timeout=gen_timeout,
                    # 衔接
                    close_dialog=auto_close, settle=2.0,
                    # 审稿
                    do_review=True,
                    review_model=rv_model, review_card=rv_card,
                    review_card_hint=AI.MODEL_CARD_HINT.get(rv_card, ""),
                    review_associate=rv_assoc,
                    review_req=rv_req, req_tab=DEFAULT_REVIEW_TAB,
                    review_instruction=rv_instr,
                    review_done_timeout=rv_timeout,
                    replace=rv_replace, select_all=rv_select_all)
                self.after(0, self._on_both_done, r, "")
            except Exception as e:
                self.after(0, self._on_both_done, None, str(e))

        # ★ 统一互斥：任务没跑完就再点 → 友好提示，不并发操作浏览器
        self._run_guarded("续写+审稿一条龙", worker, btn=self._btn_ai_both)

    def _on_both_done(self, r, err=""):
        if hasattr(self._btn_ai_both, "set_text"):
            self._btn_ai_both.set_text("续写 + 审稿 一条龙")
        if err:
            self.log(f"✗ 一条龙异常：{err}", "err")
            self.status.set_status("一条龙异常", "err")
            return
        if not r:
            self.log("✗ 一条龙失败", "err")
            self.status.set_status("一条龙失败", "err")
            return
        gen = r.get("gen") or {}
        self.log(f"  续写：{gen.get('reason', '?')}", "brand")
        self.log(f"  正文：{r.get('body')} 字", "brand")
        if r.get("review"):
            self.log("✓ 一条龙完成：续写 + 审稿 + 替换全部走完", "ok")
            self.status.set_status("一条龙完成", "ok")
        else:
            self.log("⚠ 续写完成，但审稿阶段未成功（看 artifacts/screenshots/）",
                     "warn")
            self.status.set_status("审稿阶段失败", "warn")

    # -------------------------------------------------- ★ 批量跑章

    def _ai_batch_go(self):
        """★★ 批量跑章：第 start ~ end 章，逐章一条龙。

        ★ 用户需求（2026-10-03）：
          「我现有小说有100章，能不能指定生成第3到第10章，
            他就自动替换我的指令模板，自动切换左侧的章节」
        → 每章：切章节 → 用「#@ = 当前章」渲染指令模板 → 一条龙。
          缺章自动新建（左栏没有「第N章」就点「新建章节」补）。
        """
        import threading

        book = self._ai_book_entry.get().strip()
        if not book:
            self.log("请填写「作品名称」（站点上那本书的名字）", "warn")
            return

        # ★★ 根因修复：批量路径原本**不解析**「第几本」，却直接使用
        #    `self._ai_book_index` → 用的是上一次单章/一条龙留下的**陈旧索引**，
        #    可能打开错误的同名作品。现在与其它入口走同一个 helper。
        _idx, ok = self._parse_book_index()
        if not ok:
            return

        # ---- 范围解析 ----
        def _int_or(entry, default):
            t = entry.get().strip()
            return int(t) if t.isdigit() else default

        start = _int_or(self._batch_start_entry, 0)
        end = _int_or(self._batch_end_entry, 0)
        if start < 1 or end < 1:
            self.log("「起始章」「结束章」都要填正整数（如 3 和 10）", "warn")
            return
        if end < start:
            self.log("结束章不能小于起始章", "warn")
            return

        # ---- 指令模板（渲染来源）----
        if self._project is None:
            self.log("还没有分章，先选文件分章", "warn")
            return
        self._collect_notes()
        self._project.instruction = self._get_instruction()
        tpl = self._project.instruction
        if not tpl:
            self.log("「指令模板」是空的，先写点什么（用 #@ 代表当前章）", "warn")
            return
        chk = self._project.check_template(tpl)
        if chk["unknown"]:
            self.log("✗ 指令里有不存在的代号："
                     + " ".join(f"#{n}" for n in chk["unknown"]), "err")
            return

        # ★ plot 来源：每章用「当前章」渲染一次。
        #   用 render_for_batch：模板里没有 #@ 时，把 #N（如 #1）自动当作「当前章」，
        #   避免「一直定在第一章」（用户 2026-10-04 反馈）。
        proj = self._project
        has_cur = bool(proj.CUR_RE.search(tpl))
        has_code = bool(proj.CODE_RE.search(tpl))
        if has_code and not has_cur:
            self.log("⚠ 指令模板里用的是 #N（如 #1），批量跑章已自动把它当作"
                     "「当前章」处理（每章用各自的大纲）", "warn")
        elif not has_cur and not has_code:
            self.log("⚠ 指令模板里既没有 #@ 也没有 #N，每章都会用同一段文本"
                     "（若是故意如此可忽略）", "warn")
        plot_for = lambda no: proj.render_for_batch(no, template=tpl)

        # ---- 续写 / 审稿参数（复用一条龙的那套）----
        shortcut = self._ai_shortcut_entry.get().strip()

        # ★★ 修正（2026-10-04 用户报「2700 字竟然过了 2100-2300 的限制」）：
        #    原实现把区间**写死**成 `_int_or(,_entry, 100) or 100` /
        #    `... 5000) or 5000` —— 只有当界面上**留空**时才落到 100/5000 兜底，
        #    但如果界面上填着 2100/2300，这里拿到的本来是 2100/2300 ...
        #    真正的元凶在下面：`max_retry=0` 硬编码（见调用处），
        #    导致**一轮定生死**，而旧的"尽力而为"分支会无脑采纳最后一轮。
        #    现在：区间严格用**界面上的值**（默认走 DEFAULT_*），
        #    重试次数也真正使用界面上的「最多重生成」。
        min_words = _int_or(self._ai_min_entry, DEFAULT_MIN_WORDS)
        max_words = _int_or(self._ai_max_entry, DEFAULT_MAX_WORDS)
        max_retry = _int_or(self._ai_retry_entry, DEFAULT_MAX_RETRY)
        if min_words > max_words:
            min_words, max_words = max_words, min_words
        rv_model = self._rv_model_entry.get().strip() or DEFAULT_REVIEW_MODEL
        rv_card = self._rv_card_entry.get().strip() or DEFAULT_REVIEW_CARD
        rv_assoc = (self._rv_assoc_entry.get().strip()
                    or DEFAULT_REVIEW_ASSOCIATE)
        rv_req = self._rv_req_entry.get().strip()
        rv_instr = self._rv_instr_text.get("1.0", "end").strip()
        rv_replace = bool(self._rv_replace_var.get())
        rv_select_all = bool(self._rv_select_all_var.get())
        rv_tout = self._rv_timeout_entry.get().strip()
        rv_timeout = int(rv_tout) if rv_tout.isdigit() else DEFAULT_REVIEW_TIMEOUT
        do_new = bool(self._batch_autonew_var.get())
        # ★ 2026-10-04 新增：某章失败就停（原来只有后端参数，界面没入口）
        try:
            stop_on_fail = bool(self._batch_stop_on_fail_var.get())
        except Exception:
            stop_on_fail = False

        # ★★ 清掉上一次的「停止」标记 —— 否则新任务一开始就会被立刻中止
        from src import ai as _AI
        _AI.clear_cancel()

        total = end - start + 1
        self.log(f"★ 批量跑章：第 {start}~{end} 章（共 {total} 章），"
                 f"缺章自动新建={'是' if do_new else '否'}"
                 + ("，某章失败就停" if stop_on_fail else ""), "brand")
        self.log(f"  指令模板含 #@（当前章占位符）= {'是' if has_cur else '否'}；"
                 f"若没有，每章剧情都一样", "dim")
        self._save_ws(silent=True)
        self.status.set_status(f"批量跑章 {start}~{end} 执行中…", "warn")
        if hasattr(self, "_run_progress") and hasattr(self, "_run_draw_progress"):
            try:
                from src.runplan import Progress
                self._run_progress = Progress(total=total)
                self._run_render_progress()
            except Exception:
                pass
        if hasattr(self._btn_ai_batch, "set_text"):
            self._btn_ai_batch.set_text(f"执行中 0/{total}")

        def worker():
            try:
                from src import books as B
                from src import ai as AI
                from src import login as L
                page = self._ensure_page()

                # 阶段零：准备
                st = L.is_ready()
                if not st["ok"]:
                    self.after(0, self.log, "尚未准备，先打开网站保存登录态…", "warn")
                    pr = L.prepare_session(self._app, save=True, auto=True,
                                           wait_seconds=0, interactive=True)
                    if not pr["ok"]:
                        self.after(0, self._on_batch_done, None,
                                   f"准备未完成：{pr['message']}")
                        return
                    self.after(0, self.log, "✓ 准备就绪", "ok")
                else:
                    self.after(0, self.log, f"已有登录态，跳过准备（{st['age']}）", "dim")

                # 打开作品
                self.after(0, self.log, f"打开作品《{book}》…", "brand")
                if not B.open_book(page, book, console_pick=False,
                                   index=self._ai_book_index, wait=3.0):
                    self.after(0, self._on_batch_done, None, "打开作品失败")
                    return

                # ★ 用户要求（2026-10-04）：不要一次性建好所有章节，
                #   要「一章一章边建边跑」—— 缺章由 ai_batch_chapters 循环内
                #   逐章 ensure_chapter(no) 处理，这里不再预建。

                # ★★ 逐章进度：真正接到 ai_batch_chapters 上
                #   （2026-10-04 修复：原来这里也定义了 _progress，但**没有传**
                #    → 按钮上的"执行中 N/M"和"—— 第 N/M 章 ——"从来没出现过）
                r = AI.ai_batch_chapters(
                    page,
                    start=start, end=end,
                    plot_for=plot_for,
                    gen_model="细腻版", gen_associate="正常", relate_count=10,
                    shortcut=shortcut,
                    min_words=min_words, max_words=max_words,
                    # ★★ 修正（2026-10-04）：原来是硬编码 `max_retry=0`
                    #    ⇒ 一章只生成一轮，字数不达标也直接过
                    #    ⇒ 用户 2700 字（上限 2300）被当"完成"。
                    #    改为真正使用界面上的「最多重生成」。
                    max_retry=max_retry, best_effort=True, gen_timeout=300.0,
                    do_review=True,
                    review_model=rv_model, review_card=rv_card,
                    review_card_hint=AI.MODEL_CARD_HINT.get(rv_card, ""),
                    review_associate=rv_assoc,
                    review_req=rv_req, req_tab=DEFAULT_REVIEW_TAB,
                    review_instruction=rv_instr,
                    review_done_timeout=rv_timeout,
                    replace=rv_replace, select_all=rv_select_all,
                    stop_on_fail=stop_on_fail,
                    auto_new=do_new,
                    on_progress=getattr(self, "_run_progress_sink", None),
                    should_stop=AI.cancel_requested)
                self.after(0, self._on_batch_done, r, "")
            except Exception as e:
                self.after(0, self._on_batch_done, None, str(e))

        # ★ 统一互斥：任务没跑完就再点 → 友好提示，不并发操作浏览器
        started = self._run_guarded(f"批量跑章({start}~{end})", worker,
                                    btn=self._btn_ai_batch)
        # ★ 只有真的跑起来了才让「停止」可点
        if started:
            self._run_set_stop_enabled(True)
        else:
            self._run_set_stop_enabled(False)

    def _on_batch_done(self, r, err=""):
        # ★ 收尾：恢复按钮、关掉「停止」、清掉中止标记（免得下次开局就被中止）
        if hasattr(self._btn_ai_batch, "set_text"):
            self._btn_ai_batch.set_text("▶  开始跑章")
        self._run_set_stop_enabled(False)
        try:
            from src import ai as _AI
            _AI.clear_cancel()
        except Exception:
            pass
        if hasattr(self, "_run_render_progress"):
            try:
                self._run_render_progress()
            except Exception:
                pass

        if err:
            self.log(f"✗ 批量跑章异常：{err}", "err")
            self.status.set_status("批量跑章异常", "err")
            return
        if not r:
            self.log("✗ 批量跑章失败", "err")
            self.status.set_status("批量跑章失败", "err")
            return

        ok = r.get("ok", 0)
        total = r.get("total", 0)
        failed = r.get("failed", [])
        aborted = bool(r.get("aborted"))
        overall = r.get("elapsed") or 0.0

        # ★★ 记下「上次跑到哪」——界面上给一个「接着上次继续」按钮。
        #    连载场景（今天 3~10、明天 11~20）就不用每次重新算章号了。
        #    取**成功跑完的最高章号**（失败/中止的章不算，那些要重跑）。
        try:
            from src.workspace import note_batch_run
            done_nos = [int(x.get("no") or 0)
                        for x in (r.get("results") or []) if x.get("ok")]
            note_batch_run(max(done_nos) if done_nos else 0, int(total or 0))
            if hasattr(self, "_refresh_run_todo"):
                self._refresh_run_todo()
        except Exception as e:
            self.log(f"（记录上次进度失败，忽略：{e}）", "dim")

        # ★★ 中止要走**独立分支**：既不能说"全部成功"，也不该报成"失败"，
        #   否则用户会以为是自己跑挂了。
        if aborted:
            self.log(f"⏹ 批量跑章已停止：完成 {ok}/{total} 章"
                     + (f"，失败章 {failed}" if failed else "")
                     + (f"，共耗时 {overall:.0f}s" if overall else ""), "warn")
            self.status.set_status(f"已停止（完成 {ok}/{total}）", "warn")
            if failed:
                self.log(f"   有 {len(failed)} 个失败章，可点「从失败章重跑」", "info")
            return

        if total and ok == total:
            self.log(f"✓ 批量跑章完成：{ok}/{total} 章全部成功"
                     + (f"，共耗时 {overall:.0f}s" if overall else ""), "ok")
            self.status.set_status(f"批量跑章完成 {ok}/{total}", "ok")
        else:
            self.log(f"⚠ 批量跑章结束：{ok}/{total} 成功"
                     + (f"，失败章 {failed}" if failed else ""), "warn")
            self.status.set_status(f"批量跑章 {ok}/{total}（有失败）", "warn")
            if failed:
                self.log(f"   可点「从失败章重跑」把范围设成第 {min(failed)} 章起",
                         "info")
