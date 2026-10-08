"""★ 一条龙：续写 → 采纳 → 关弹窗 → 审稿 → 替换。

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


class AiBothMixin:
    """★ 一条龙：续写 → 采纳 → 关弹窗 → 审稿 → 替换。"""

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
        book = self._ai_book_ok()
        if not book:
            return

        # ---- ① 剧情：跟「一键续写」一样，来自指令模板渲染 ----
        rendered = self._ai_render_plot()
        if not rendered:
            return
        plot, _used = rendered

        # ---- ② 续写参数 ----（读界面、含"字数区间写反自动交换"）
        opts = self._ai_gen_opts()
        shortcut = opts["shortcut"]
        min_words, max_words = opts["min_words"], opts["max_words"]
        max_retry = opts["max_retry"]
        gen_timeout = 300.0

        # ---- ③ 审稿参数 ----
        rv = self._ai_review_opts()
        rv_model, rv_card, rv_assoc = rv["model"], rv["card"], rv["assoc"]
        rv_req, rv_instr = rv["req"], rv["instruction"]
        rv_chapter = rv["chapter"]
        rv_replace, rv_select_all, rv_timeout = rv["replace"], rv["select_all"], rv["timeout"]
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
                from xyxbot import ai as AI
                page = self._ensure_page()

                # ★ 阶段零：流程准备（打开网站 → 保存 cookie/缓存）
                #   没登录态才做；已有则跳过（不打断用户节奏）
                prepared, why = self._ai_prepare_session()
                if not prepared:
                    self.after(0, self._on_both_done, None, why)
                    return

                if not self._ai_open_book(page, book):
                    self.after(0, self._on_both_done, None,
                               "打开作品失败——确认这本书存在")
                    return

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
