"""③ 指令模板 / ④ 细纲来源（折叠区）。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from xyxbot.ui.theme import (COLOR, F, BrandButton, Card, CheckBox, Collapsible,
                     DarkEntry, DimLabel, TitleLabel, bind_configure,
                     bind_wheel)
import tkinter as tk


class RunNotesMixin:
    """③ 指令模板 / ④ 细纲来源（折叠区）。"""

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
