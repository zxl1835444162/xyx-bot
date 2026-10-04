"""「跑章」页 —— 本项目**唯一的主流程**（2026-10-04 界面重设计）。

设计目标（用户原话）：
    「我在操作上感觉很分散……我仅仅使用的功能，仅有这个流水化的
      从某章到某章的续写。」

所以这一页把整条流水线按**从上到下**排成一列，一页配完就能开跑：

    状态条  →  ① 目标作品  →  ② 跑章范围  →  ③ 每章指令（核心）
            →  ④ 细纲来源(折叠)  →  ⑤ 高级参数(折叠)
            →  ⑥ 预检 / 开始 / 停止
            →  ⑦ 进度 + ETA + 逐章结果

★ 关于控件命名：页面里所有 `self._ai_*` / `self._rv_*` / `self._batch_*` /
  `self._tpl_*` / `self._ch_*` / `self._novel_*` 都**沿用原来的名字**，
  这样 `config_io.py`（记住/回填）、`chapters.py`（分章/模板/细纲）、
  `ai_flow.py`（跑章编排）**一行都不用改**。

★ 依赖（由 MRO 解析）：`_page_header` / `log` / `status` / `_run_guarded` /
  `_ensure_page`（窗口）、`_restore_ws` / `_save_ws`（config_io）、
  `_do_split` / `_set_tpl` / `_get_instruction` / `_collect_notes` /
  `_update_tpl_preview` / `_render_chapters` / `_resolve_current_chapter_no` /
  `_parse_book_index`（chapters）、`_ai_batch_go`（ai_flow）。
"""

from __future__ import annotations

import tkinter as tk

from ..defaults import (
    DEFAULT_MAX_RETRY,
    DEFAULT_MAX_WORDS,
    DEFAULT_MIN_WORDS,
    DEFAULT_REVIEW_ASSOCIATE,
    DEFAULT_REVIEW_CARD,
    DEFAULT_REVIEW_MODEL,
    DEFAULT_REVIEW_REQ,
    DEFAULT_REVIEW_SELECT_ALL,
    DEFAULT_REVIEW_TIMEOUT,
    DEFAULT_REVIEW_WAIT,
    DEFAULT_SHORTCUT,
)
from ..theme import (COLOR, F, BrandButton, Card, CheckBox, Collapsible,
                     DarkEntry, DimLabel, TitleLabel, bind_configure)
from src.runplan import (Check, Progress, format_checks,
                         has_blocking_error, preflight)

# 结果表在没有结果时显示的字
_EMPTY_RESULTS = "还没有结果。跑完的每一章会在这里列出来。"


class RunMixin:
    """「跑章」页的构建 + 进度/预检/停止的界面逻辑。"""

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
            from src.workspace import last_run
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
            from src.workspace import last_run, next_run_range
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

    # ---------------------------------------------------------- ① 目标作品

    def _run_build_target(self, parent):
        card = Card(parent)
        card.pack(fill="x", pady=(0, 10))
        b = card.body
        TitleLabel(b, "① 目标作品").pack(anchor="w")
        DimLabel(b, "站点上那本书的名字（不是本地 txt 的名字）",
                 size=9).pack(anchor="w", pady=(3, 8))

        row = tk.Frame(b, bg=COLOR["bg_card"])
        row.pack(fill="x")
        self._ai_book_entry = DarkEntry(row, placeholder="例如：新建作品12",
                                        icon="▣", width=280, height=38)
        self._ai_book_entry.pack(side="left")

        tk.Label(row, text="同名第几本", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left", padx=(12, 0))
        self._ai_idx_entry = DarkEntry(row, placeholder="如 0", icon="#",
                                       width=104, height=38)
        self._ai_idx_entry.pack(side="left", padx=(4, 0))
        DimLabel(row, "（从 0 开始，只有同名多本时才需要）",
                 size=8).pack(side="left", padx=(8, 0), pady=(6, 0))

        # ★ 兼容字段：单章流程用它暂存解析出的索引
        self._ai_book_index = None

    # ---------------------------------------------------------- ② 跑章范围

    def _run_build_range(self, parent):
        card = Card(parent)
        card.pack(fill="x", pady=(0, 10))
        b = card.body
        TitleLabel(b, "② 跑章范围").pack(anchor="w")
        DimLabel(b, "每章都会：切到该章 → 用指令模板渲染剧情 → 续写 → 采纳 → 审稿 → 替换",
                 size=9).pack(anchor="w", pady=(3, 8))

        row = tk.Frame(b, bg=COLOR["bg_card"])
        row.pack(fill="x")
        tk.Label(row, text="第", font=F(10), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left")
        # ★★ 占位符故意写成「如 3」而不是「3」（2026-10-04 截图验收发现）：
        #   原来占位符是裸数字，界面上看起来**和真填了一模一样** ——
        #   用户以为范围已经设好，点「开始跑章」却被告知"没填范围"。
        #   加上「如」字就一眼看出是示例。
        self._batch_start_entry = DarkEntry(row, placeholder="如 3", icon="▤",
                                            width=110, height=38)
        # ★ DarkEntry 的实际可输入区 = 控件宽 - 56px（图标占 40px + 右边距）。
        #   所以数值框给到 110px 左右才够放 4~6 位数字，否则会被截断。
        self._batch_start_entry.pack(side="left", padx=(4, 0))
        tk.Label(row, text="章  →  第", font=F(10), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left", padx=(8, 0))
        self._batch_end_entry = DarkEntry(row, placeholder="如 10", icon="▤",
                                          width=110, height=38)
        self._batch_end_entry.pack(side="left", padx=(4, 0))
        tk.Label(row, text="章", font=F(10), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left", padx=(4, 0))

        self._batch_autonew_var = tk.BooleanVar(value=True)
        self._run_check(row, "缺章自动新建", self._batch_autonew_var,
                        width=150, height=38).pack(side="left", padx=(14, 0))
        self._batch_stop_on_fail_var = tk.BooleanVar(value=False)
        self._run_check(row, "某章失败就停", self._batch_stop_on_fail_var,
                        width=160, height=38).pack(side="left", padx=(8, 0))

        self._run_range_hint = DimLabel(b, "", size=8)
        self._run_range_hint.pack(anchor="w", pady=(8, 0))

        # ★★ 「接着上次继续」（2026-10-04）——连载场景专用：
        #    今天跑 3~10、明天跑 11~20，不用每次重新算章号。
        last_row = tk.Frame(b, bg=COLOR["bg_card"])
        last_row.pack(fill="x", pady=(8, 0))
        self._run_last_lbl = DimLabel(last_row, "", size=8)
        self._run_last_lbl.pack(side="left")
        BrandButton(last_row, "接着上次继续", width=132, height=28,
                    style="ghost", bg=COLOR["bg_card"], font_size=8,
                    command=self._run_continue_last).pack(side="left",
                                                          padx=(10, 0))
        BrandButton(last_row, "拉结束章到最新", width=132, height=28,
                    style="ghost", bg=COLOR["bg_card"], font_size=8,
                    command=self._run_range_to_latest).pack(side="left",
                                                            padx=(8, 0))

        # 范围一变就刷新提示（"站点现有 1~7 章，3~10 需新建 3 章"）
        for e in (self._batch_start_entry, self._batch_end_entry):
            try:
                e.bind("<KeyRelease>", lambda _e: self._refresh_run_range_hint())
                e.bind("<FocusOut>", lambda _e: self._refresh_run_range_hint())
            except Exception:
                pass

    def _run_read_int(self, entry, default=0) -> int:
        t = ""
        try:
            t = (entry.get() or "").strip()
        except Exception:
            return default
        return int(t) if t.isdigit() else default

    def _refresh_run_range_hint(self):
        try:
            start = self._run_read_int(self._batch_start_entry, 0)
            end = self._run_read_int(self._batch_end_entry, 0)
        except Exception:
            return
        site = self._run_site_chapters
        if start < 1 or end < 1 or end < start:
            self._run_range_hint.config(text="")
            return
        n = end - start + 1
        if not site:
            self._run_range_hint.config(text=f"共 {n} 章（站点现有章节未知，"
                                             f"点「预检」可以查）")
            return
        miss = [c for c in range(start, end + 1) if c not in site]
        if not miss:
            self._run_range_hint.config(
                text=f"共 {n} 章 · 站点上都已经存在")
        else:
            head = "、".join(f"第{c}章" for c in miss[:5])
            tail = f" 等 {len(miss)} 章" if len(miss) > 5 else ""
            self._run_range_hint.config(
                text=f"共 {n} 章 · 需要新建 {len(miss)} 章（{head}{tail}）"
                     f" · 站点现有 {min(site)}~{max(site)} 章")

    # ---------------------------------------------------------- ③ 指令模板

    def _run_build_template(self, parent):
        card = Card(parent)
        card.pack(fill="x", pady=(0, 10))
        b = card.body
        TitleLabel(b, "③ 每章指令（核心）").pack(anchor="w")
        DimLabel(b, "这段文字会作为站点的「后续剧情」逐章发送。"
                    "写 #@ 表示「当前章的细纲」，批量跑章时每章自动替换成各自的细纲。",
                 size=9).pack(anchor="w", pady=(3, 8))

        self._code_hint = DimLabel(b, "", size=8)
        self._code_hint.pack(anchor="w", pady=(0, 6))

        # ★ 大编辑器：用户那段模板约 250 字，原来的 3 行框完全不够用
        self._tpl_text = tk.Text(b, height=9, font=F(10), bd=0,
                                 bg=COLOR["bg_card_hi"], fg=COLOR["text"],
                                 insertbackground=COLOR["text"],
                                 highlightthickness=1,
                                 highlightbackground=COLOR["border"],
                                 wrap="word", padx=10, pady=8)
        self._tpl_text.pack(fill="x")
        self._tpl_text.insert("1.0", "#@")
        self._tpl_text.bind("<KeyRelease>",
                            lambda e: self._update_tpl_preview())
        self._tpl_text.bind("<MouseWheel>", self._on_mousewheel)

        quick = tk.Frame(b, bg=COLOR["bg_card"])
        quick.pack(anchor="w", pady=(8, 0))
        DimLabel(quick, "载入常用：", size=8).pack(side="left")
        for label, tpl in [
            ("只放细纲（#@）", "#@"),
            ("本章细纲 + 前文", "前文：#1\n\n本章细纲：#@"),
            ("本章 + 后一章走向", "本章细纲：#@\n下一章走向：#2"),
        ]:
            BrandButton(quick, label, width=130, height=28, style="ghost",
                        bg=COLOR["bg_card"], font_size=8,
                        command=lambda t=tpl: self._set_tpl(t)).pack(
                side="left", padx=(6, 0))
        BrandButton(quick, "清空", width=56, height=28, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=lambda: self._set_tpl("")).pack(
            side="left", padx=(10, 0))

        # 预览
        prd = tk.Frame(b, bg=COLOR["bg_card"])
        prd.pack(fill="x", pady=(10, 0))
        prow = tk.Frame(prd, bg=COLOR["bg_card"])
        prow.pack(fill="x")
        DimLabel(prow, "当前章替换后的效果", size=9).pack(side="left")
        self._tpl_state = DimLabel(prow, "", size=8)
        self._tpl_state.pack(side="left", padx=(8, 0))
        BrandButton(prow, "刷新预览", width=92, height=26, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=self._update_tpl_preview).pack(side="right")

        self._tpl_preview = tk.Text(prd, height=4, font=F(9), bd=0,
                                    bg=COLOR["bg_card_hi"],
                                    fg=COLOR["text_dim"],
                                    highlightthickness=1,
                                    highlightbackground=COLOR["border"],
                                    wrap="word", padx=10, pady=8)
        self._tpl_preview.pack(fill="x", pady=(4, 0))
        self._tpl_preview.configure(state="disabled")
        self._tpl_preview.bind("<MouseWheel>", self._on_mousewheel)

        # 兼容旧字段（chapters._update_tpl_preview 会用到 _ai_preview）
        self._ai_preview = None

    # ---------------------------------------------------------- ④ 细纲来源

    def _run_build_notes(self, parent):
        col = Collapsible(parent, title="④ 细纲来源（本地小说文件 · 分章）")
        col.pack(fill="x", pady=(0, 8))
        self._run_col_notes = col
        b = col.body

        DimLabel(b, "每章的 #@ 细纲来自本地小说分章结果。只需配置一次，"
                    "之后跑章不用再管。", size=9).pack(anchor="w", pady=(6, 8))

        row = tk.Frame(b, bg=COLOR["bg_card"])
        row.pack(fill="x")
        self._novel_entry = DarkEntry(
            row, placeholder="点右边「选择文件」，或把 txt 拖进来",
            icon="▥", width=460, height=38)
        self._novel_entry.pack(side="left")
        BrandButton(row, "选择文件", width=104, height=38,
                    bg=COLOR["bg_card"],
                    command=self._pick_novel).pack(side="left", padx=(10, 0))

        hist_row = tk.Frame(b, bg=COLOR["bg_card"])
        hist_row.pack(fill="x", pady=(8, 0))
        self._hist_lbl = DimLabel(hist_row, "最近：", size=8)
        self._hist_lbl.pack(side="left", pady=(4, 0))
        self._hist_box = tk.Frame(hist_row, bg=COLOR["bg_card"])
        self._hist_box.pack(side="left", fill="x")

        btns = tk.Frame(b, bg=COLOR["bg_card"])
        btns.pack(anchor="w", pady=(12, 4))
        BrandButton(btns, "开始分章", width=120, height=34,
                    bg=COLOR["bg_card"],
                    command=self._do_split).pack(side="left")
        BrandButton(btns, "另存工程", width=104, height=34, style="ghost",
                    bg=COLOR["bg_card"],
                    command=self._save_project).pack(side="left", padx=(8, 0))
        BrandButton(btns, "打开工程", width=104, height=34, style="ghost",
                    bg=COLOR["bg_card"],
                    command=self._open_project).pack(side="left", padx=(8, 0))
        self._split_hint = DimLabel(b, "还没选文件。", size=9)
        self._split_hint.pack(anchor="w", pady=(10, 4))

        # ---------------- 章节列表（填每章细纲）----------------
        head = tk.Frame(b, bg=COLOR["bg_card"])
        head.pack(fill="x", pady=(14, 0))
        self._ch_head = TitleLabel(head, "章节列表")
        self._ch_head.pack(side="left")
        self._ch_info = DimLabel(head, "分章后这里会列出每一章", size=9)
        self._ch_info.pack(side="left", padx=(10, 0), pady=(4, 0))

        wrap = tk.Frame(b, bg=COLOR["bg_card"], height=260)
        wrap.pack(fill="x", pady=(10, 4))
        wrap.pack_propagate(False)
        self._ch_canvas = tk.Canvas(wrap, bg=COLOR["bg_card"],
                                    highlightthickness=0, bd=0)
        self._ch_canvas.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(wrap, orient="vertical",
                          command=self._ch_canvas.yview)
        sb.pack(side="right", fill="y")
        self._ch_canvas.configure(yscrollcommand=sb.set)

        self._ch_list = tk.Frame(self._ch_canvas, bg=COLOR["bg_card"])
        self._ch_win = self._ch_canvas.create_window((0, 0),
                                                     window=self._ch_list,
                                                     anchor="nw")
        # ★★ 用守卫版：在 <Configure> 里改 Canvas 配置会再触发 <Configure>，
        #    macOS 上就是死循环（主线程永远回不到事件循环 → 界面卡住转圈）。
        bind_configure(self._ch_list,
                       lambda: self._ch_canvas.configure(
                           scrollregion=self._ch_canvas.bbox("all")))
        bind_configure(self._ch_canvas,
                       lambda: self._ch_canvas.itemconfig(
                           self._ch_win, width=self._ch_canvas._cfg_w))
        for w in (self._ch_canvas, self._ch_list):
            w.bind("<MouseWheel>", self._ch_scroll)

        self._project = None
        self._ch_entries = {}

    # ---------------------------------------------------------- ⑤ 高级参数

    def _run_build_params(self, parent):
        col = Collapsible(parent, title="⑤ 高级参数（续写 / 审稿 · 一般不用改）")
        col.pack(fill="x", pady=(0, 8))
        self._run_col_params = col
        b = col.body

        # ---- 续写 ----
        r1 = tk.Frame(b, bg=COLOR["bg_card"])
        r1.pack(fill="x", pady=(8, 0))
        tk.Label(r1, text="续写提示词（快捷选项）", font=F(9),
                 bg=COLOR["bg_card"], fg=COLOR["text_dim"]).pack(anchor="w")
        r1b = tk.Frame(b, bg=COLOR["bg_card"])
        r1b.pack(fill="x", pady=(4, 0))
        self._ai_shortcut_entry = DarkEntry(
            r1b, placeholder="填关键词，如：强盛集团云霄", icon="✎",
            width=380, height=36)
        self._ai_shortcut_entry.pack(side="left")
        BrandButton(r1b, "填入默认", width=96, height=36, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=lambda: self._ai_shortcut_entry.set(
                        DEFAULT_SHORTCUT)).pack(side="left", padx=(8, 0))
        try:
            self._ai_shortcut_entry.set(DEFAULT_SHORTCUT)
        except Exception:
            pass

        # ---- 字数 ----
        r2 = tk.Frame(b, bg=COLOR["bg_card"])
        r2.pack(fill="x", pady=(14, 0))
        tk.Label(r2, text="生成字数（决定是否「重新生成」）", font=F(9),
                 bg=COLOR["bg_card"], fg=COLOR["text_dim"]).pack(anchor="w")
        r2b = tk.Frame(b, bg=COLOR["bg_card"])
        r2b.pack(fill="x", pady=(4, 0))
        self._ai_auto_var = tk.BooleanVar(value=True)
        self._run_check(r2b, "按字数自动采纳", self._ai_auto_var,
                        width=170, height=36).pack(side="left")
        tk.Label(r2b, text="下限", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left", padx=(14, 0))
        self._ai_min_entry = DarkEntry(r2b, placeholder="2100", icon="↓",
                                       width=112, height=36)
        self._ai_min_entry.pack(side="left", padx=(4, 0))
        tk.Label(r2b, text="上限", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left", padx=(10, 0))
        self._ai_max_entry = DarkEntry(r2b, placeholder="2300", icon="↑",
                                       width=112, height=36)
        self._ai_max_entry.pack(side="left", padx=(4, 0))
        tk.Label(r2b, text="最多重生成", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left", padx=(10, 0))
        self._ai_retry_entry = DarkEntry(r2b, placeholder="3", icon="↻",
                                         width=92, height=36)
        self._ai_retry_entry.pack(side="left", padx=(4, 0))
        try:
            self._ai_min_entry.set(str(DEFAULT_MIN_WORDS))
            self._ai_max_entry.set(str(DEFAULT_MAX_WORDS))
            self._ai_retry_entry.set(str(DEFAULT_MAX_RETRY))
        except Exception:
            pass
        DimLabel(b, "把下限填 1 就等于「不校验字数、生成完直接采纳」"
                    "（字数要求可以写在上面③的指令里）",
                 size=8).pack(anchor="w", pady=(5, 0))

        # ---- 审稿 ----
        r3 = tk.Frame(b, bg=COLOR["bg_card"])
        r3.pack(fill="x", pady=(14, 0))
        tk.Label(r3, text="AI 审稿", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(anchor="w")
        r3b = tk.Frame(b, bg=COLOR["bg_card"])
        r3b.pack(fill="x", pady=(4, 0))
        for label, attr, width, dflt in (
            ("模型", "_rv_model_entry", 104, DEFAULT_REVIEW_MODEL),
            ("卡片", "_rv_card_entry", 124, DEFAULT_REVIEW_CARD),
            ("联想", "_rv_assoc_entry", 84, DEFAULT_REVIEW_ASSOCIATE),
        ):
            tk.Label(r3b, text=label, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text_dim"]).pack(side="left", padx=(0 if label == "模型" else 10, 0))
            e = DarkEntry(r3b, placeholder=dflt, icon="◈", width=width,
                          height=36)
            e.pack(side="left", padx=(4, 0))
            setattr(self, attr, e)
            try:
                e.set(dflt)
            except Exception:
                pass

        r3c = tk.Frame(b, bg=COLOR["bg_card"])
        r3c.pack(fill="x", pady=(8, 0))
        tk.Label(r3c, text="审稿要求", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left")
        self._rv_req_entry = DarkEntry(
            r3c, placeholder="填关键词，如：强盛集团云霄拯救过稿计划",
            icon="✎", width=330, height=36)
        self._rv_req_entry.pack(side="left", padx=(4, 0))
        BrandButton(r3c, "填入默认", width=96, height=36, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=lambda: self._rv_req_entry.set(
                        DEFAULT_REVIEW_REQ)).pack(side="left", padx=(8, 0))
        try:
            self._rv_req_entry.set(DEFAULT_REVIEW_REQ)
        except Exception:
            pass

        # 追加指令
        r4 = tk.Frame(b, bg=COLOR["bg_card"])
        r4.pack(fill="x", pady=(10, 0))
        tk.Label(r4, text="追加指令（拼在待审正文前面，可留空）", font=F(9),
                 bg=COLOR["bg_card"], fg=COLOR["text_dim"]).pack(anchor="w")
        self._rv_instr_text = tk.Text(r4, height=3, font=F(9), bd=0,
                                      bg=COLOR["bg_card_hi"],
                                      fg=COLOR["text"],
                                      insertbackground=COLOR["text"],
                                      highlightthickness=1,
                                      highlightbackground=COLOR["border"],
                                      wrap="word", padx=8, pady=6)
        self._rv_instr_text.pack(fill="x", pady=(4, 0))
        self._rv_instr_text.bind("<MouseWheel>", self._on_mousewheel)

        # 开关
        r5 = tk.Frame(b, bg=COLOR["bg_card"])
        r5.pack(fill="x", pady=(12, 0))
        self._rv_select_all_var = tk.BooleanVar(
            value=DEFAULT_REVIEW_SELECT_ALL)
        self._run_check(r5, "替换前全选正文", self._rv_select_all_var,
                        width=170, height=34).pack(side="left")
        self._rv_replace_var = tk.BooleanVar(value=True)
        self._run_check(r5, "完成后替换到正文", self._rv_replace_var,
                        width=180, height=34).pack(side="left", padx=(8, 0))
        self._rv_wait_var = tk.BooleanVar(value=DEFAULT_REVIEW_WAIT)
        tk.Label(r5, text="审稿超时", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left", padx=(12, 0))
        self._rv_timeout_entry = DarkEntry(r5, placeholder="600", icon="⏱",
                                           width=106, height=34)
        self._rv_timeout_entry.pack(side="left", padx=(4, 0))
        tk.Label(r5, text="秒", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left", padx=(4, 0))
        try:
            self._rv_timeout_entry.set(str(DEFAULT_REVIEW_TIMEOUT))
        except Exception:
            pass

        # 兼容字段：单章流程要的「先打开章节」输入框
        r6 = tk.Frame(b, bg=COLOR["bg_card"])
        r6.pack(fill="x", pady=(8, 0))
        tk.Label(r6, text="单章工具：先打开章节", font=F(9),
                 bg=COLOR["bg_card"], fg=COLOR["text_dim"]).pack(side="left")
        self._rv_chapter_entry = DarkEntry(
            r6, placeholder="留空=第1章", icon="☰", width=180, height=34)
        self._rv_chapter_entry.pack(side="left", padx=(4, 0))

        # ---- 统一前后缀（默认收起）----
        r7 = tk.Frame(b, bg=COLOR["bg_card"])
        r7.pack(fill="x", pady=(14, 0))
        self._use_wrap = tk.BooleanVar(value=False)
        CheckBox(r7, "给每章剧情套统一前缀 / 后缀", checked=False,
                 command=lambda v: (self._use_wrap.set(bool(v)),
                                    self._toggle_wrap()),
                 width=280, height=34).pack(side="left")
        wr = tk.Frame(b, bg=COLOR["bg_card"])
        wr.pack(fill="x", pady=(6, 0))
        self._prefix_entry = DarkEntry(wr, placeholder="统一前缀", icon="↑",
                                       width=280, height=34)
        self._prefix_entry.pack(side="left")
        self._suffix_entry = DarkEntry(wr, placeholder="统一后缀（可留空）",
                                       icon="↓", width=280, height=34)
        self._suffix_entry.pack(side="left", padx=(10, 0))
        self._wrap_widgets = [wr]
        wr.pack_forget()

        # ---- ★ 单章工具（备用，收进最里面）----
        col_solo = Collapsible(b, title="单章工具（备用：只跑一章）")
        col_solo.pack(fill="x", pady=(14, 0))
        sb = col_solo.body
        DimLabel(sb, "只处理「单章工具：先打开章节」指定的那一章。"
                     "上面的批量跑章才是主用法。", size=8).pack(
            anchor="w", pady=(6, 8))
        srow = tk.Frame(sb, bg=COLOR["bg_card"])
        srow.pack(anchor="w")
        self._btn_ai_go = BrandButton(srow, "一键续写", width=140, height=36,
                                      bg=COLOR["bg_card"],
                                      command=self._ai_go)
        self._btn_ai_go.pack(side="left")
        self._btn_ai_review = BrandButton(srow, "AI审稿", width=120, height=36,
                                          style="ghost", bg=COLOR["bg_card"],
                                          command=self._ai_review_go)
        self._btn_ai_review.pack(side="left", padx=(8, 0))
        self._btn_ai_both = BrandButton(srow, "续写+审稿一条龙", width=180,
                                        height=36, bg=COLOR["bg_card"],
                                        command=self._ai_both_go)
        self._btn_ai_both.pack(side="left", padx=(8, 0))
        self._auto_both_close_var = tk.BooleanVar(value=True)
        self._run_check(sb, "续写后自动关弹窗（接着审稿）",
                        self._auto_both_close_var,
                        width=260, height=32).pack(anchor="w", pady=(8, 0))

        # 「续写到第几章」下拉（chapters 模块要用；放在最里面，避免误导）
        ar = tk.Frame(sb, bg=COLOR["bg_card"])
        ar.pack(fill="x", pady=(10, 0))
        tk.Label(ar, text="当前章（预览用）", font=F(9), bg=COLOR["bg_card"],
                 fg=COLOR["text_dim"]).pack(side="left")
        self._ai_ch_var = tk.StringVar(value="（先分章）")
        self._ai_ch_menu = tk.OptionMenu(ar, self._ai_ch_var, "（先分章）")
        self._ai_ch_menu.config(bg=COLOR["bg_card_hi"], fg=COLOR["text"],
                                activebackground=COLOR["brand"],
                                activeforeground="#fff",
                                font=F(9), bd=0, highlightthickness=0,
                                highlightbackground=COLOR["bg_card"],
                                relief="flat", width=20)
        self._ai_ch_menu["menu"].config(bg=COLOR["bg_card_hi"],
                                       fg=COLOR["text"], font=F(9))
        self._ai_ch_menu.pack(side="left", padx=(6, 0))
        self._ai_ch_menu["menu"].delete(0, "end")
        self._ai_ch_menu["menu"].add_command(label="（先分章）",
                                            command=lambda: None)

    # ---------------------------------------------------------- ⑦ 结果

    def _run_build_progress(self, parent):
        card = Card(parent)
        card.pack(fill="both", expand=True)
        b = card.body
        TitleLabel(b, "逐章结果").pack(anchor="w")
        DimLabel(b, "每章跑完都会在这里留一行（成功/失败/中止 + 字数 + 耗时）。"
                    "开始/停止/进度条在上面状态条里，不用滚下来。",
                 size=9).pack(anchor="w", pady=(3, 0))

        head = tk.Frame(b, bg=COLOR["bg_card"])
        head.pack(fill="x", pady=(14, 0))
        BrandButton(head, "从失败章重跑", width=140, height=28, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=self._run_retry_failed).pack(side="right")
        BrandButton(head, "清空结果", width=90, height=28, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=self._run_clear_results).pack(side="right",
                                                          padx=(0, 8))
        # ★ 结果导出（2026-10-04）：跑完 20 章总要有地方留痕/交给别人看
        BrandButton(head, "导出 CSV", width=96, height=28, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=self._run_export_results).pack(side="left",
                                                           padx=(10, 0))
        BrandButton(head, "复制失败章号", width=120, height=28, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=self._run_copy_failed).pack(side="left",
                                                        padx=(8, 0))

        wrap = tk.Frame(b, bg=COLOR["bg_card"], height=200)
        wrap.pack(fill="x", pady=(8, 4))
        wrap.pack_propagate(False)
        self._run_res_canvas = tk.Canvas(wrap, bg=COLOR["bg_card"],
                                         highlightthickness=0, bd=0)
        self._run_res_canvas.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(wrap, orient="vertical",
                          command=self._run_res_canvas.yview)
        sb.pack(side="right", fill="y")
        self._run_res_canvas.configure(yscrollcommand=sb.set)

        self._run_res_list = tk.Frame(self._run_res_canvas,
                                       bg=COLOR["bg_card"])
        self._run_res_win = self._run_res_canvas.create_window(
            (0, 0), window=self._run_res_list, anchor="nw")
        # ★ 守卫版：滚动区两处 Configure（裸绑在 macOS 上会死循环）
        bind_configure(self._run_res_list,
                       lambda: self._run_res_canvas.configure(
                           scrollregion=self._run_res_canvas.bbox("all")))
        bind_configure(self._run_res_canvas,
                       lambda: self._run_res_canvas.itemconfig(
                           self._run_res_win,
                           width=self._run_res_canvas._cfg_w))

        self._run_empty_lbl = DimLabel(b, _EMPTY_RESULTS, size=8)
        self._run_empty_lbl.pack(anchor="w")

        self._run_checks_box = tk.Frame(b, bg=COLOR["bg_card"])
        self._run_checks_box.pack(fill="x", pady=(12, 0))

    # ============================================================ 预检

    def _run_local_checks(self) -> list:
        """本地预检（瞬时，不开浏览器）。"""
        book = ""
        try:
            book = self._ai_book_entry.get().strip()
        except Exception:
            pass
        start = self._run_read_int(self._batch_start_entry, 0)
        end = self._run_read_int(self._batch_end_entry, 0)

        try:
            st = self._prepare_state() or {}
            logged = bool(st.get("saved"))
            age = st.get("age") or ""
        except Exception:
            logged, age = False, ""

        # 模板 / 细纲状态
        tpl, unknown, empty, preview_len = "", [], [], 0
        proj = getattr(self, "_project", None)
        try:
            self._collect_notes()
            proj = getattr(self, "_project", None)
            if proj is not None:
                proj.instruction = self._get_instruction()
                tpl = proj.instruction or ""
        except Exception:
            tpl = ""
        if proj is not None and tpl:
            try:
                chk = proj.check_template(tpl)
                unknown = list(chk.get("unknown") or [])
                empty = list(chk.get("empty") or [])
            except Exception:
                pass
            try:
                rendered = proj.render_for_batch(
                    self._resolve_current_chapter_no() or 1, template=tpl)
                preview_len = len(rendered or "")
            except Exception:
                preview_len = 0

        return preflight(
            book=book, start=start, end=end,
            site_chapters=self._run_site_chapters,
            auto_new=bool(self._batch_autonew_var.get()),
            template=tpl, unknown_codes=unknown, empty_codes=empty,
            logged_in=logged, session_age=age,
            has_project=proj is not None,
            project_name=(proj.name if proj is not None else ""),
            project_chapters=(len(proj.chapters) if proj is not None else 0),
            preview_len=preview_len)

    def _run_show_checks(self, checks: list) -> None:
        for w in self._run_checks_box.winfo_children():
            w.destroy()
        self._run_last_checks = list(checks)
        DimLabel(self._run_checks_box, "预检结果", size=9).pack(anchor="w")
        colors = {"ok": COLOR["success"], "warn": COLOR["warning"],
                  "err": COLOR["danger"]}
        for c in checks:
            line = tk.Frame(self._run_checks_box, bg=COLOR["bg_card"])
            line.pack(fill="x", pady=1)
            tk.Label(line, text=c.icon(), font=F(9, True),
                     bg=COLOR["bg_card"],
                     fg=colors.get(c.level, COLOR["text_dim"])).pack(side="left")
            tk.Label(line, text=" " + c.title, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text"]).pack(side="left")
            if c.detail:
                tk.Label(line, text="  " + c.detail, font=F(8),
                         bg=COLOR["bg_card"],
                         fg=COLOR["text_mute"]).pack(side="left")
        for ln in format_checks(checks):
            self.log("预检 " + ln, "info")

    def _run_precheck(self, deep: bool = False) -> list:
        """跑预检；`deep=True` 时另外起一个后台任务去站点上核对作品与章节。"""
        checks = self._run_local_checks()
        self._run_show_checks(checks)
        if deep:
            self._run_precheck_deep_async()
        return checks

    def _run_precheck_deep(self):
        self._run_precheck(deep=True)

    def _run_precheck_deep_async(self):
        """后台：打开作品 → 读站点章节号 → 再补一轮预检。"""
        book = ""
        try:
            book = self._ai_book_entry.get().strip()
        except Exception:
            pass
        if not book:
            self.log("预检：没填作品名，跳过站点核对", "warn")
            return
        _idx, ok = self._parse_book_index()
        if not ok:
            return

        def worker():
            from src import books as B
            from src import ai as AI
            try:
                page = self._ensure_page()
            except Exception as e:
                self.after(0, self.log, f"预检：浏览器起不来（{e}）", "err")
                return
            try:
                self.after(0, self.log, f"预检：正在核对作品《{book}》…", "brand")
                if not B.open_book(page, book, console_pick=False,
                                   index=self._ai_book_index, wait=3.0):
                    self.after(0, self._run_precheck_deep_done, None,
                               "打不开这个作品 —— 确认名字对不对")
                    return
                nos = AI.chapter_numbers(page)
                self.after(0, self._run_precheck_deep_done, nos, "")
            except Exception as e:
                self.after(0, self._run_precheck_deep_done, None, str(e))

        self._run_guarded("跑章预检", worker)

    def _run_precheck_deep_done(self, nos, err: str = ""):
        if err:
            self.log(f"预检：站点核对失败 —— {err}", "warn")
            self._run_show_checks(self._run_local_checks()
                                  + [Check("err", "站点核对失败", err)])
            self._refresh_run_status()
            return
        if nos is None:
            self._run_show_checks(self._run_local_checks()
                                  + [Check("err", "作品打不开")])
            self._refresh_run_status()
            return
        self._run_site_chapters = list(nos)
        self.log(f"预检：站点上《{self._ai_book_entry.get().strip()}》"
                 f"共 {len(nos)} 章"
                 + (f"（{min(nos)}~{max(nos)}）" if nos else ""), "ok")
        self._refresh_run_range_hint()
        self._refresh_run_status()
        self._run_show_checks(self._run_local_checks())

    # ============================================================ 开始 / 停止

    def _run_start(self):
        """开始跑章：先预检，有阻塞问题就拒绝开跑。"""
        import threading

        checks = self._run_precheck(deep=False)
        if has_blocking_error(checks):
            bad = [c for c in checks if c.is_error]
            self.log(f"✗ 预检没通过（{len(bad)} 项阻塞），已取消开跑", "err")
            for c in bad:
                self.log(f"    ✗ {c.title} —— {c.detail}", "err")
            self.status.set_status("预检未通过", "err")
            return
        warns = [c for c in checks if c.level == "warn"]
        for c in warns:
            self.log(f"⚠ {c.title} —— {c.detail}", "warn")

        # 重置进度
        self._run_clear_results()
        self._run_progress = Progress()
        self._run_draw_progress()

        if hasattr(self, "_run_col_params"):
            self._run_col_params.set_open(False)
        if hasattr(self, "_run_col_notes"):
            self._run_col_notes.set_open(False)

        # 交给 ai_flow 的批量实现（它读的是同一批控件）
        self._ai_batch_go()

    def _run_stop(self):
        """请求停止：协作式取消，最长一个轮询周期（≤0.25s）生效。"""
        from src import ai as AI

        if not AI.cancel_requested():
            AI.request_cancel()
            self.log("⏹ 已请求停止 —— 正在等当前步骤退出（通常几秒内）", "warn")
            self.status.set_status("正在停止…", "warn")
        else:
            self.log("⏹ 停止请求已经发出过了，稍等", "info")

    def _run_set_stop_enabled(self, on: bool):
        """开关「停止」按钮（只有任务真的跑起来了才让它可点）。"""
        btn = getattr(self, "_btn_run_stop", None)
        if btn is None:
            return
        try:
            btn.set_enabled(bool(on))
        except Exception:
            pass

    def _run_clear_results(self):
        for w in self._run_res_list.winfo_children():
            w.destroy()
        self._run_result_rows = 0
        self._run_results_data = []
        try:
            self._run_empty_lbl.pack(anchor="w")
        except Exception:
            pass

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

        from src.runplan import fmt_duration
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

    # ============================================================ 结果处理

    def _run_range_to_latest(self):
        """把「结束章」拉到站点已知的最新章（保留起始章）。"""
        site = self._run_site_chapters
        if not site:
            self.log("还不知道站点上有哪些章 —— 先点「预检（不跑）」查一次",
                     "warn")
            return
        end = max(site)
        start = self._run_read_int(self._batch_start_entry, 0) or 1
        if start > end:
            start = end
        self._batch_start_entry.set(str(start))
        self._batch_end_entry.set(str(end))
        self._refresh_run_range_hint()
        self.log(f"结束章已设为站点最新章：第 {end} 章", "brand")

    def _run_export_results(self):
        """把逐章结果导出成 CSV（UTF-8-BOM，Excel 打开不乱码）。"""
        rows = list(getattr(self, "_run_results_data", []) or [])
        if not rows:
            self.log("还没有结果可导出", "warn")
            return
        try:
            import csv
            from datetime import datetime

            from src import config as C

            out_dir = C.ARTIFACTS / "exports"
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / f"跑章结果-{datetime.now():%Y%m%d-%H%M%S}.csv"
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["章号", "结果", "字数", "耗时秒", "原因"])
                for r in rows:
                    verdict = ("中止" if r.get("aborted")
                               else ("成功" if r.get("ok") else "失败"))
                    w.writerow([
                        r.get("no", ""), verdict, r.get("words") or "",
                        f"{float(r.get('elapsed') or 0):.1f}",
                        r.get("reason") or "",
                    ])
            self.log(f"✓ 结果已导出（{len(rows)} 行）：{p}", "ok")
            self.status.set_status("结果已导出", "ok")
        except Exception as e:
            self.log(f"导出失败：{e}", "err")

    def _run_copy_failed(self):
        """把失败章号复制到剪贴板（形如 ``5,7,9``）。"""
        p = getattr(self, "_run_progress", None)
        failed = list(getattr(p, "failed", []) or [])
        if not failed:
            self.log("没有失败章，不用复制", "info")
            return
        txt = ",".join(str(x) for x in failed)
        try:
            self.clipboard_clear()
            self.clipboard_append(txt)
        except Exception as e:
            self.log(f"写剪贴板失败（{e}），失败章号：{txt}", "warn")
            return
        self.log(f"已复制失败章号到剪贴板：{txt}", "ok")
        self.status.set_status(f"已复制 {len(failed)} 个失败章号", "ok")

    def _run_retry_failed(self):
        from src.runplan import next_retry_range

        p = getattr(self, "_run_progress", Progress())
        end = self._run_read_int(self._batch_end_entry, 0)
        rng = next_retry_range(p, end)
        if not rng:
            self.log("没有失败章，不用重跑", "info")
            return
        start, end2 = rng
        self._batch_start_entry.set(str(start))
        self._batch_end_entry.set(str(end2))
        self._refresh_run_range_hint()
        skipped = [x for x in range(start, end2 + 1) if x not in p.failed]
        self.log(f"已把范围改成 第{start}~{end2} 章（{len(p.failed)} 个失败章）"
                 + (f"；注意第 {'、'.join(map(str, skipped))} 章会重跑一遍"
                    if skipped else ""), "brand")
        self.status.set_status(f"已设好重跑范围 {start}~{end2}", "ok")
