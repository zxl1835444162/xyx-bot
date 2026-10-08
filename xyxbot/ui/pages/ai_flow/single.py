"""一键续写（单章工具）。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations


class AiSingleMixin:
    """一键续写（单章工具）。"""

    # -------------------------------------------------- 一键续写

    def _ai_go(self):
        """一键：打开作品 → 用「指令模板」渲染出文本 → AI 续写。"""
        book = self._ai_book_ok()
        if not book:
            return

        opts = self._ai_gen_opts()
        shortcut = opts["shortcut"]
        auto_accept = opts["auto_accept"]
        min_words, max_words = opts["min_words"], opts["max_words"]
        max_retry = opts["max_retry"]
        if shortcut:
            self.log(f"快捷选项将按关键词定位：{shortcut}", "info")
        if auto_accept:
            self.log(f"自动采纳已开启：{min_words}~{max_words} 字，"
                     f"最多重生成 {max_retry} 次", "info")

        rendered = self._ai_render_plot()
        if not rendered:
            return
        plot, used = rendered

        self.log(f"一键续写：作品《{book}》 用 {used} 合成 {len(plot)} 字", "brand")
        self._save_ws(silent=True)      # ★ 记住这次配置
        self.status.set_status("AI 续写中…", "warn")
        if hasattr(self._btn_ai_go, "set_text"):
            self._btn_ai_go.set_text("续写中…")

        def worker():
            try:
                from xyxbot import ai as AI
                page = self._ensure_page()   # 复用同一个浏览器页（线程绑定）

                # ★ 必须先打开作品，否则停在首页，找不到「AI续写正文」按钮
                if not self._ai_open_book(page, book):
                    self.after(0, self._on_ai_fail,
                               f"打开作品「{book}」失败——"
                               f"确认这本书存在（同名多本请填「作品名称」时加 --index）")
                    return

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
