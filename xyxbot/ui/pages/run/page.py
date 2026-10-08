"""页面骨架与顶部状态条（还差什么 / 上次跑到哪 / 接着上次继续）。

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


class RunPageMixin:
    """页面骨架与顶部状态条（还差什么 / 上次跑到哪 / 接着上次继续）。"""

    # ------------------------------------------------------------ 小工具

    def _run_check(self, parent, text, var, **kw):
        """建一个 CheckBox 并绑到 BooleanVar。

        ★ theme.CheckBox 点击时**自己翻转**内部状态，然后把**新状态**
          作为参数回调过来 —— 所以这里直接 ``var.set(bool(v))`` 即可，
          千万不要在 command 里再翻一次（会翻两下）。
        """
        return CheckBox(parent, text, checked=bool(var.get()),
                        command=lambda v: var.set(bool(v)), **kw)


    # ============================================================ 页面骨架

    def _page_run(self, parent):
        self._page_header(parent, "跑章",
                          "从某一章到某一章，自动续写 → 采纳 → 审稿 → 替换")

        # 页面级状态（切页不销毁，所以能一直保留）
        self._run_progress = Progress()
        self._run_result_rows = 0
        # ★ 逐章结果的原始数据（导出 CSV 用）
        self._run_results_data: list = []
        self._run_started_at = None
        self._run_last_checks = []
        self._run_site_chapters = None

        self._run_build_status(parent)
        self._run_build_target(parent)
        self._run_build_range(parent)
        self._run_build_template(parent)
        self._run_build_notes(parent)
        self._run_build_params(parent)
        self._run_build_progress(parent)

        # 回填上次保存的配置（作品/范围/模板/参数一起回来）
        self._restore_ws()
        self._refresh_run_status()
        self._refresh_run_last()
        self._refresh_run_todo()

    # ---------------------------------------------------------- 状态条

    def _run_build_status(self, parent):
        card = Card(parent)
        card.pack(fill="x", pady=(0, 10))
        b = card.body

        row = tk.Frame(b, bg=COLOR["bg_card"])
        row.pack(fill="x")

        self._run_status_dot = tk.Label(row, text="●", font=F(13),
                                        bg=COLOR["bg_card"],
                                        fg=COLOR["warning"])
        self._run_status_dot.pack(side="left", padx=(0, 8))
        self._run_status_lbl = tk.Label(row, text="正在读取环境…", font=F(10, True),
                                        bg=COLOR["bg_card"], fg=COLOR["text"])
        self._run_status_lbl.pack(side="left")

        BrandButton(row, "刷新状态", width=96, height=30, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=self._refresh_run_status).pack(side="right")

        self._run_status_sub = DimLabel(b, "", size=8)
        self._run_status_sub.pack(anchor="w", pady=(6, 0))

        # ★★ 主操作 + 进度就放在最上面（2026-10-04 实测后的调整）
        #
        #   第一版把「开始跑章 / 停止 / 进度」放在整页最底下（流水线的末尾），
        #   结果在 1180x980 的窗口里**必须滚动才能按到开始按钮** —— 对一个
        #   "只有一条流程"的工具来说这是硬伤（用户打开就是要按它）。
        #   现在：状态 + 主操作 + 进度常驻顶部，配置在中间，结果在底部。
        act = tk.Frame(b, bg=COLOR["bg_card"])
        act.pack(fill="x", pady=(12, 0))

        self._btn_run_start = BrandButton(
            act, "▶  开始跑章", width=190, height=46, bg=COLOR["bg_card"],
            command=self._run_start)
        self._btn_run_start.pack(side="left")
        # 兼容旧字段：ai_flow 用它改文字/禁用
        self._btn_ai_batch = self._btn_run_start

        self._btn_run_stop = BrandButton(
            act, "■  停止", width=112, height=46, style="ghost",
            bg=COLOR["bg_card"], command=self._run_stop)
        self._btn_run_stop.pack(side="left", padx=(10, 0))
        self._btn_run_stop.set_enabled(False)

        BrandButton(act, "预检（不跑）", width=132, height=46, style="ghost",
                    bg=COLOR["bg_card"],
                    command=self._run_precheck_deep).pack(side="left",
                                                          padx=(10, 0))

        self._run_progress_canvas = tk.Canvas(
            act, height=34, width=150, bg=COLOR["bg_card"],
            highlightthickness=0, bd=0)
        self._run_progress_canvas.pack(side="right", fill="x", expand=True,
                                       padx=(16, 0))
        # ★ 守卫版：进度条画布在 Configure 里重绘，裸绑会死循环（见 theme.bind_configure）
        bind_configure(self._run_progress_canvas, self._run_draw_progress)

        self._run_progress_lbl = tk.Label(
            b, text="尚未开始", font=F(10, True), bg=COLOR["bg_card"],
            fg=COLOR["text_dim"], anchor="w")
        self._run_progress_lbl.pack(fill="x", pady=(8, 0))
        self._run_timing_lbl = DimLabel(b, "", size=9)
        self._run_timing_lbl.pack(anchor="w", pady=(2, 0))

        # ---------------------------------------------------------------
        # ★★ 「还差什么」（2026-10-04）
        #   用户抱怨"操作很分散" —— 原来要自己记住：登录了吗？分章了吗？
        #   作品名填了吗？范围对吗？现在由界面直接列出**缺的那几项**，
        #   每项配一个按钮把你送到该去的地方，不用满界面找。
        # ---------------------------------------------------------------
        self._run_todo_box = tk.Frame(b, bg=COLOR["bg_card"])
        self._run_todo_box.pack(fill="x", pady=(10, 0))

    def _refresh_run_status(self):
        """刷新顶部状态条：登录态 / 已载入的小说 / 站点已知章节。"""
        # ★ 登录态用 `_prepare_state()`（它给了 age / message）；
        #   `_session_info()` 只有 saved/account/cookies，没有"多久以前"。
        try:
            st = self._prepare_state() or {}
        except Exception:
            st = {}
        saved = bool(st.get("saved"))
        age = st.get("age") or ""

        # 本地细纲
        proj = getattr(self, "_project", None)
        if proj is not None:
            novel_txt = f"细纲：{proj.name}（{len(proj.chapters)} 章）"
        else:
            novel_txt = "细纲：还没载入小说文件"

        book = ""
        try:
            book = self._ai_book_entry.get().strip()
        except Exception:
            pass
        book_txt = f"作品：{book}" if book else "作品：还没填"

        site = self._run_site_chapters
        site_txt = (f"站点已知章节：{min(site)}~{max(site)} 章"
                    if site else "站点章节：未检测")

        self._run_status_dot.config(
            fg=COLOR["success"] if saved else COLOR["warning"])
        self._run_status_lbl.config(
            text=("登录态已就绪" if saved else "登录态未保存 —— 去「准备」页保存一次"))
        self._run_status_sub.config(
            text=f"{novel_txt}   ·   {book_txt}   ·   {site_txt}"
                 + (f"   ·   登录态保存于 {age}" if age else ""))

    # ---------------------------------------------------------- ★ 还差什么

    def _run_missing(self) -> list:
        """返回「开跑前还缺的东西」，每项是 (说明, 按钮文字, 回调)。

        纯只读检查，不联网。
        """
        out = []
        # ① 登录态
        try:
            st = self._prepare_state() or {}
        except Exception:
            st = {}
        if not st.get("saved"):
            out.append(("保存登录态（登录一次后长期免登录）",
                        "去准备", lambda: self.show_page("setup")))
        # ② 本地细纲
        if getattr(self, "_project", None) is None:
            out.append(("载入本地小说并分章（每章的 #@ 细纲来自它）",
                        "展开④", self._run_open_notes))
        # ③ 作品名
        try:
            book = self._ai_book_entry.get().strip()
        except Exception:
            book = ""
        if not book:
            out.append(("填「目标作品」—— 站点上那本书的名字",
                        "定位", lambda: self._ai_book_entry.focus()))
        # ④ 跑章范围
        start = self._run_read_int(self._batch_start_entry, 0)
        end = self._run_read_int(self._batch_end_entry, 0)
        if start < 1 or end < 1 or end < start:
            out.append(("填「跑章范围」—— 两个框还是空的（灰色示例不算数）",
                        "定位", lambda: self._batch_start_entry.focus()))
        return out

    def _refresh_run_todo(self):
        """重画「还差什么」这一行。"""
        box = getattr(self, "_run_todo_box", None)
        if box is None:
            return
        for w in box.winfo_children():
            w.destroy()

        todos = self._run_missing()
        if not todos:
            line = tk.Frame(box, bg=COLOR["bg_card"])
            line.pack(fill="x")
            tk.Label(line, text="✓", font=F(10, True), bg=COLOR["bg_card"],
                     fg=COLOR["success"]).pack(side="left")
            tk.Label(line, text="  一切就绪，可以点「开始跑章」",
                     font=F(9, True), bg=COLOR["bg_card"],
                     fg=COLOR["success"]).pack(side="left")
            return

        head = tk.Frame(box, bg=COLOR["bg_card"])
        head.pack(fill="x")
        tk.Label(head, text="还差这几项：", font=F(9, True),
                 bg=COLOR["bg_card"], fg=COLOR["warning"]).pack(side="left")

        for text, btn_label, cb in todos:
            line = tk.Frame(box, bg=COLOR["bg_card"])
            line.pack(fill="x", pady=1)
            tk.Label(line, text="  ·", font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["warning"]).pack(side="left")
            tk.Label(line, text=" " + text, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text_dim"]).pack(side="left")
            if cb is not None:
                BrandButton(line, btn_label, width=76, height=26,
                            style="ghost", bg=COLOR["bg_card"], font_size=8,
                            command=cb).pack(side="left", padx=(8, 0))

    def _run_open_notes(self):
        """展开 ④ 细纲来源，并把滚动条带过去。"""
        col = getattr(self, "_run_col_notes", None)
        if col is not None:
            try:
                col.set_open(True)
            except Exception:
                pass
        try:
            self._scroll_canvas.yview_moveto(1.0)
        except Exception:
            pass
        self.log("展开「④ 细纲来源」—— 选本地 txt 后点「开始分章」", "info")

    # ---------------------------------------------------------- ★ 上次跑到哪

    def _refresh_run_last(self):
        """刷新 ② 里的「上次跑到 …」提示。"""
        lbl = getattr(self, "_run_last_lbl", None)
        if lbl is None:
            return
        try:
            from xyxbot.workspace import last_run
            r = last_run()
        except Exception:
            r = {"ok": False}
        if r.get("ok"):
            lbl.config(text=f"上次跑到 第{r['done']}章"
                            f"（{r.get('at') or '—'}）→ 可点右边接着跑")
        else:
            lbl.config(text="还没有「上次跑到哪」的记录（跑完一次就会记住）")

    def _run_continue_last(self):
        """★ 接着上次继续：自动把范围设成「下一段」。"""
        try:
            from xyxbot.workspace import last_run, next_run_range
            rng = next_run_range()
            r = last_run()
        except Exception as e:
            self.log(f"读上次进度失败：{e}", "err")
            return
        if not rng:
            self.log("还没有「上次跑到哪」的记录，先手动填范围跑一次", "warn")
            return
        start, end = rng
        self._batch_start_entry.set(str(start))
        self._batch_end_entry.set(str(end))
        self._refresh_run_range_hint()
        self.log(f"接着上次继续：上次跑到第{r['done']}章 → "
                 f"本次跑 第{start}~{end} 章（沿用上次的段长 {end - start + 1}）",
                 "brand")
        self.status.set_status(f"已设好第 {start}~{end} 章", "ok")
