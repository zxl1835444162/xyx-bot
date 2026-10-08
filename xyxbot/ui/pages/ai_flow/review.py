"""一键审稿（单章工具）。

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


class AiReviewMixin:
    """一键审稿（单章工具）。"""

    # -------------------------------------------------- AI 审稿

    def _ai_review_go(self):
        """一键：打开作品 → 打开「AI审稿」抽屉 → 选模型/联想/审稿要求 → 点「生成」。

        ★ 与 `_ai_go`（续写）的区别：
            - 续写要**渲染指令模板**当剧情投喂；审稿**不需要**，
              它审的是**页面上当前章的内容**（待审文本留空 = 沿用）。
            - 续写点「开始 AI 续写」；审稿点「生成」。
            - 承载不同：续写=居中弹窗；审稿=**右侧抽屉**。
        """
        book = self._ai_book_ok()
        if not book:
            return

        # 读参数
        rv = self._ai_review_opts()
        model, card, assoc = rv["model"], rv["card"], rv["assoc"]
        req, instruction = rv["req"], rv["instruction"]
        chapter = rv["chapter"]
        # ★ 审稿流程开关
        wait_done = rv["wait_done"]
        do_replace, select_all = rv["replace"], rv["select_all"]
        done_timeout = rv["timeout"]
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
                from xyxbot import ai as AI
                page = self._ensure_page()   # 复用同一个浏览器页（线程绑定）

                if not self._ai_open_book(page, book):
                    self.after(0, self._on_review_done, False,
                               "打开作品失败——确认这本书存在")
                    return

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
