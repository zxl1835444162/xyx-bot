"""「任务中心」页。

从 `ui/main_window.py` 拆出的独立页面（架构改良阶段二）。
"""

from __future__ import annotations

import tkinter as tk

from ..theme import COLOR, F, BrandButton, DimLabel


class TasksPage:
    """「任务中心」页：列出全部已注册任务，一键执行。

    任务来源是 `src.tasks.list_task_names()`（装饰器注册表）。
    """

    def _page_tasks(self, parent):
        self._page_header(parent, "任务中心", "选择并执行自动化流程")

        names = self._task_names()
        if not names:
            DimLabel(parent, "暂无已注册任务").pack(anchor="w")
            return

        grid = tk.Frame(parent, bg=COLOR["bg_root"])
        grid.pack(fill="both", expand=True)

        for i, name in enumerate(names):
            card = tk.Frame(grid, bg=COLOR["bg_card"],
                            highlightbackground=COLOR["border"],
                            highlightthickness=1)
            card.grid(row=i // 2, column=i % 2, sticky="nsew",
                      padx=(0 if i % 2 == 0 else 10, 0), pady=(0, 10))
            grid.grid_columnconfigure(i % 2, weight=1)

            inner = tk.Frame(card, bg=COLOR["bg_card"])
            inner.pack(fill="both", expand=True, padx=16, pady=14)

            tk.Label(inner, text="▤", font=F(14), bg=COLOR["bg_card"],
                     fg=COLOR["brand"]).pack(anchor="w")
            tk.Label(inner, text=name, font=F(11, True), bg=COLOR["bg_card"],
                     fg=COLOR["text"]).pack(anchor="w", pady=(6, 3))
            tk.Label(inner, text="点击执行该自动化流程", font=F(9),
                     bg=COLOR["bg_card"],
                     fg=COLOR["text_mute"]).pack(anchor="w", pady=(0, 12))

            BrandButton(inner, "执行任务", width=110, height=32,
                        style="primary", bg=COLOR["bg_card"],
                        command=lambda n=name: self._run_task(n)).pack(anchor="w")
