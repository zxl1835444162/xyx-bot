"""① ~ ④ 的控件构建（目标 / 范围 / 指令模板 / 细纲来源）。

本文件由 `xyxbot/ui/pages/run.py` 拆分而来（class split），
只搬位置、不改逻辑：方法体、注释、超时值全部原样。
"""

from __future__ import annotations

from xyxbot.ui.defaults import (
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
from xyxbot.ui.theme import (COLOR, F, BrandButton, Card, CheckBox, Collapsible,
                     DarkEntry, DimLabel, TitleLabel, bind_configure,
                     bind_wheel)
import tkinter as tk


class RunFormMixin:
    """① ~ ④ 的控件构建（目标 / 范围 / 指令模板 / 细纲来源）。"""

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
        bind_wheel(self._tpl_text, self._on_mousewheel)

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
        bind_wheel(self._tpl_preview, self._on_mousewheel)

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
            bind_wheel(w, self._ch_scroll)

        self._project = None
        self._ch_entries = {}

    # ---------------------------------------------------------- ⑤ 高级参数

    def _run_build_params(self, parent):
        col = Collapsible(parent, title="⑤ 高级参数（续写 / 审稿 · 一般不用改）")
        col.pack(fill="x", pady=(0, 8))
        self._run_col_params = col
        b = col.body

        # 下面每段各管一组控件。**顺序 = 界面从上到下的顺序，不要调换**：
        # Tk 里控件的创建顺序决定它们在父容器里的叠放次序。
        self._run_params_shortcut(b)
        self._run_params_words(b)
        self._run_params_review_model(b)
        self._run_params_review_instruction(b)
        self._run_params_review_switches(b)
        self._run_params_solo_chapter(b)
        self._run_params_wrapper(b)
        self._run_params_solo_tools(b)

    def _run_params_shortcut(self, b):
        """续写提示词（快捷选项关键词）。"""
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

    def _run_params_words(self, b):
        """生成字数（自动采纳 + 下限/上限/最多重生成）。"""
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

    def _run_params_review_model(self, b):
        """审稿模型 / 卡片 / 联想 + 审稿要求。"""
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

    def _run_params_review_instruction(self, b):
        """追加指令（拼在待审正文前面）。"""
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
        bind_wheel(self._rv_instr_text, self._on_mousewheel)

    def _run_params_review_switches(self, b):
        """替换前全选 / 完成后替换 / 审稿超时。"""
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

    def _run_params_solo_chapter(self, b):
        """单章工具用的「先打开章节」（兼容字段）。"""
        # 兼容字段：单章流程要的「先打开章节」输入框
        r6 = tk.Frame(b, bg=COLOR["bg_card"])
        r6.pack(fill="x", pady=(8, 0))
        tk.Label(r6, text="单章工具：先打开章节", font=F(9),
                 bg=COLOR["bg_card"], fg=COLOR["text_dim"]).pack(side="left")
        self._rv_chapter_entry = DarkEntry(
            r6, placeholder="留空=第1章", icon="☰", width=180, height=34)
        self._rv_chapter_entry.pack(side="left", padx=(4, 0))

    def _run_params_wrapper(self, b):
        """统一前缀 / 后缀（默认收起）。"""
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

    def _run_params_solo_tools(self, b):
        """单章工具（备用）+「续写到第几章」下拉。"""
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
_EMPTY_RESULTS = "还没有结果。跑完的每一章会在这里列出来。"
