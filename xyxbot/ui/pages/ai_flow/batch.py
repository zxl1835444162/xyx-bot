"""批量跑章（逐章一条龙 + 进度 + 中止）。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from xyxbot.ui.defaults import (
    DEFAULT_MAX_RETRY,
    DEFAULT_MAX_WORDS,
    DEFAULT_MIN_WORDS,
    DEFAULT_REVIEW_ASSOCIATE,
    DEFAULT_REVIEW_CARD,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_REVIEW_TAB,
    DEFAULT_REVIEW_TIMEOUT,
)

from xyxbot.ui.pages.ai_flow.shared import _int_or


class AiBatchMixin:
    """批量跑章（逐章一条龙 + 进度 + 中止）。"""

    # -------------------------------------------------- ★ 批量跑章

    def _ai_batch_go(self):
        """★★ 批量跑章：第 start ~ end 章，逐章一条龙。

        ★ 用户需求（2026-10-03）：
          「我现有小说有100章，能不能指定生成第3到第10章，
            他就自动替换我的指令模板，自动切换左侧的章节」
        → 每章：切章节 → 用「#@ = 当前章」渲染指令模板 → 一条龙。
          缺章自动新建（左栏没有「第N章」就点「新建章节」补）。
        """
        # ★★ 根因修复（保留）：批量路径原本**不解析**「第几本」，却直接使用
        #    `self._ai_book_index` → 用的是上一次单章/一条龙留下的**陈旧索引**，
        #    可能打开错误的同名作品。现在与其它入口走同一个 helper（内部即解析）。
        book = self._ai_book_ok()
        if not book:
            return

        # ---- 范围解析 ----
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

        # ---- 续写 / 审稿参数（与一条龙同一套读取）----
        # ★★ 修正（2026-10-04 用户报「2700 字竟然过了 2100-2300 的限制」）：
        #    原实现把区间写死、并硬编码 `max_retry=0`（一轮定生死 + 旧"尽力而为"
        #    分支无脑采纳最后一轮）⇒ 字数限制完全失效。现在区间与重试次数
        #    都严格取界面上的值 —— 具体说明见 `_ai_gen_opts` 的文档串。
        opts = self._ai_gen_opts()
        shortcut = opts["shortcut"]
        min_words, max_words = opts["min_words"], opts["max_words"]
        max_retry = opts["max_retry"]
        rv = self._ai_review_opts()
        rv_model, rv_card, rv_assoc = rv["model"], rv["card"], rv["assoc"]
        rv_req, rv_instr = rv["req"], rv["instruction"]
        rv_replace, rv_select_all = rv["replace"], rv["select_all"]
        rv_timeout = rv["timeout"]
        do_new = bool(self._batch_autonew_var.get())
        # ★ 2026-10-04 新增：某章失败就停（原来只有后端参数，界面没入口）
        try:
            stop_on_fail = bool(self._batch_stop_on_fail_var.get())
        except Exception:
            stop_on_fail = False

        # ★★ 清掉上一次的「停止」标记 —— 否则新任务一开始就会被立刻中止
        from xyxbot import ai as _AI
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
                from xyxbot.runplan import Progress
                self._run_progress = Progress(total=total)
                self._run_render_progress()
            except Exception:
                pass
        if hasattr(self._btn_ai_batch, "set_text"):
            self._btn_ai_batch.set_text(f"执行中 0/{total}")

        def worker():
            try:
                from xyxbot import ai as AI
                page = self._ensure_page()

                # 阶段零：准备
                prepared, why = self._ai_prepare_session()
                if not prepared:
                    self.after(0, self._on_batch_done, None, why)
                    return

                # 打开作品
                if not self._ai_open_book(page, book):
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
            from xyxbot import ai as _AI
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
            from xyxbot.workspace import note_batch_run
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
