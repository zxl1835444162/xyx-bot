"""⑥⑦ 进度区与逐章结果表。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from xyxbot.ui.theme import (COLOR, F, BrandButton, Card, CheckBox, Collapsible,
                     DarkEntry, DimLabel, TitleLabel, bind_configure,
                     bind_wheel)
import tkinter as tk


class RunProgressMixin:
    """⑥⑦ 进度区与逐章结果表。"""

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
