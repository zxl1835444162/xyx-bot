"""进度条与逐章结果表。

本文件由 `xyxbot/ui/pages/run.py` 拆分而来（class split），
只搬位置、不改逻辑：方法体、注释、超时值全部原样。
"""

from __future__ import annotations

from xyxbot.runplan import (Check, Progress, format_checks,
                         has_blocking_error, preflight)
from xyxbot.ui.theme import (COLOR, F, BrandButton, Card, CheckBox, Collapsible,
                     DarkEntry, DimLabel, TitleLabel, bind_configure,
                     bind_wheel)
import tkinter as tk


class RunProgressMixin:
    """进度条与逐章结果表。"""

    # ============================================================ 进度渲染

    def _run_draw_progress(self):
        c = getattr(self, "_run_progress_canvas", None)
        if c is None:
            return
        p = getattr(self, "_run_progress", Progress())
        try:
            w = c.winfo_width()
            h = int(c.winfo_height()) or 18
        except Exception:
            return
        if w < 10:
            return
        c.delete("all")
        r = h / 2
        c.create_rectangle(0, 0, w, h, fill=COLOR["bg_card_hi"], outline="")
        pct = p.percent / 100.0
        if pct > 0:
            fill = COLOR["success"] if not p.failed else COLOR["brand"]
            if p.aborted:
                fill = COLOR["warning"]
            c.create_rectangle(0, 0, max(2, w * pct), h, fill=fill, outline="")
        # 进度文字压在条上
        c.create_text(w / 2, h / 2, text=f"{p.percent:.0f}%",
                      font=F(8, True),
                      fill=COLOR["text_on_brand"] if pct > 0.15
                      else COLOR["text_dim"])

    def _run_render_progress(self):
        p = getattr(self, "_run_progress", Progress())
        try:
            self._run_progress_lbl.config(text=p.line())
            self._run_timing_lbl.config(text=p.timing_line())
        except Exception:
            pass
        self._run_draw_progress()

    def _run_progress_sink(self, ev: dict):
        """`ai_batch_chapters(on_progress=...)` 的回调 —— **在 pw 线程里**。

        所以必须先 `after(0, ...)` 转回 tk 主线程再碰控件。
        """
        try:
            self.after(0, self._run_apply_progress, ev)
        except Exception:
            pass

    def _run_apply_progress(self, ev: dict):
        p = getattr(self, "_run_progress", None)
        if p is None:
            return
        p.apply(ev)
        self._run_render_progress()
        if ev.get("phase") == "start":
            no = ev.get("no")
            tot = ev.get("total")
            self.log(f"—— 第 {no} 章开始（{ev.get('index')}/{tot}）——", "brand")
        elif ev.get("phase") == "done":
            self._run_add_result_row(ev)

    def _run_add_result_row(self, ev: dict):
        if getattr(self, "_run_result_rows", 0) == 0:
            try:
                self._run_empty_lbl.pack_forget()
            except Exception:
                pass
        self._run_result_rows += 1
        try:
            self._run_results_data.append(dict(ev))
        except Exception:
            pass

        ok = bool(ev.get("ok"))
        aborted = bool(ev.get("aborted"))
        no = ev.get("no")
        secs = float(ev.get("elapsed") or 0.0)
        words = ev.get("words") or 0
        reason = ev.get("reason") or ""

        from xyxbot.runplan import fmt_duration
        if aborted:
            icon, col, tail = "⏹", COLOR["warning"], "已中止"
        elif ok:
            icon, col, tail = "✓", COLOR["success"], f"{words} 字"
        else:
            icon, col, tail = "✗", COLOR["danger"], reason or "失败"

        row = tk.Frame(self._run_res_list, bg=COLOR["bg_card"])
        row.pack(fill="x", pady=1)
        tk.Label(row, text=icon, font=F(9, True), bg=COLOR["bg_card"],
                 fg=col).pack(side="left")
        tk.Label(row, text=f" 第 {no} 章", font=F(9, True),
                 bg=COLOR["bg_card"], fg=COLOR["text"]).pack(side="left")
        tk.Label(row, text=f"  {tail}", font=F(9), bg=COLOR["bg_card"],
                 fg=col if not ok else COLOR["text_dim"]).pack(side="left")
        tk.Label(row, text=f"  {fmt_duration(secs)}", font=F(8),
                 bg=COLOR["bg_card"],
                 fg=COLOR["text_mute"]).pack(side="right")
        try:
            self._run_res_canvas.yview_moveto(1.0)
        except Exception:
            pass

        level = "warn" if aborted else ("ok" if ok else "err")
        if ok:
            self.log(f"✓ 第{no}章完成：{words} 字，{fmt_duration(secs)}", "ok")
        elif aborted:
            self.log(f"⏹ 第{no}章已中止（{fmt_duration(secs)}）", "warn")
        else:
            self.log(f"✗ 第{no}章失败：{reason or '未记录原因'}"
                     f"（{fmt_duration(secs)}）", level)
