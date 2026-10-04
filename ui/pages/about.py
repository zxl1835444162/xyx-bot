"""「关于本机」页。

从 `ui/main_window.py` 拆出的独立页面（架构改良阶段二）。
"""

from __future__ import annotations

import tkinter as tk

from ..theme import COLOR, F, Card, DimLabel, TitleLabel


class AboutPage:
    """「关于本机」页：版本号 / 授权用户 / 技术底座等静态信息。"""

    def _page_about(self, parent):
        # ★ 延迟导入：APP_NAME/COMPANY/VERSION 定义在 ui/main_window.py，
        #   而 main_window 会 import 本模块 → 顶层导入会循环。
        from ..main_window import APP_NAME, COMPANY, VERSION

        self._page_header(parent, "关于本机", "版本与授权信息")

        card = Card(parent)
        card.pack(fill="both", expand=True)
        b = card.body

        tk.Label(b, text="赵", font=F(30, True), bg=COLOR["brand"],
                 fg=COLOR["text_on_brand"], width=2, height=1).pack(anchor="w")
        TitleLabel(b, f"{COMPANY} · {APP_NAME}", size=14).pack(anchor="w", pady=(12, 4))
        DimLabel(b, "AI 内容工业化生产平台", size=10).pack(anchor="w")

        line = tk.Frame(b, bg=COLOR["border"], height=1)
        line.pack(fill="x", pady=16)

        for k, v in [
            ("版本号", VERSION),
            ("版本类型", "Enterprise Edition"),
            ("授权用户", self._username),
            ("技术底座", "Playwright · Chromium / Edge"),
            ("目标平台", "星月写作"),
        ]:
            r = tk.Frame(b, bg=COLOR["bg_card"])
            r.pack(fill="x", pady=4)
            tk.Label(r, text=k, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text_dim"], width=12, anchor="w").pack(side="left")
            tk.Label(r, text=v, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text"]).pack(side="left")
