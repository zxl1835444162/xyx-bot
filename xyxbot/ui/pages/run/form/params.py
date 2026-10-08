"""⑤ 高级参数（续写/审稿 + 单章工具备用）。

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


class RunParamsMixin:
    """⑤ 高级参数（续写/审稿 + 单章工具备用）。"""

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
