"""① 目标作品与跑章范围（含「接着上次继续」的提示）。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from xyxbot.ui.theme import (COLOR, F, BrandButton, Card, CheckBox, Collapsible,
                     DarkEntry, DimLabel, TitleLabel, bind_configure,
                     bind_wheel)
import tkinter as tk


class RunTargetMixin:
    """① 目标作品与跑章范围（含「接着上次继续」的提示）。"""

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
