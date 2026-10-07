"""「运行配置」页。

从 `ui/main_window.py` 拆出的独立页面（架构改良阶段二）。

★ 为什么用 mixin 而不是独立函数：
  页面方法大量读写 MainWindow 的控件字段（`self._browser_entry` 等）。
  拆成独立函数就得传一堆参数或引入上下文对象，改动面爆炸；
  mixin 让方法继续以 `self` 访问，**调用点零改动**，可以一页一页迁。
"""

from __future__ import annotations

import tkinter as tk

from ..theme import COLOR, F, BrandButton, Card, DarkEntry, DimLabel, TitleLabel


class SettingsPage:
    """「运行配置」页：浏览器内核路径 + 只读运行参数展示。"""

    # ------------------------------------------------------------------ 页面

    def _page_settings(self, parent, header: bool = True):
        """运行配置页。

        Args:
            header: 是否自己画页头。`False` 时用于被「准备」页组合进去
                    （否则会出现两个页头）。
        """
        if header:
            self._page_header(parent, "运行配置", "浏览器与运行参数")

        card = Card(parent)
        card.pack(fill="both", expand=True)
        b = card.body

        TitleLabel(b, "浏览器内核").pack(anchor="w")
        DimLabel(b, "默认自动检测本机 Edge / Chrome，优先使用真实内核以获得更自然的指纹",
                 size=9).pack(anchor="w", pady=(3, 12))

        row = tk.Frame(b, bg=COLOR["bg_card"])
        row.pack(fill="x", pady=(0, 14))
        # ★ 初值从持久化的 _browser_path_value 回填（切页会销毁控件，值要另存）
        self._browser_entry = DarkEntry(row, placeholder="留空则自动检测",
                                        icon="⚙", width=520, height=40)
        if getattr(self, "_browser_path_value", ""):
            self._browser_entry.set(self._browser_path_value)
        self._browser_entry.pack(side="left")
        BrandButton(row, "自动检测", width=100, height=40, style="ghost",
                    bg=COLOR["bg_card"],
                    command=self._detect_browser).pack(side="left", padx=(10, 0))

        line = tk.Frame(b, bg=COLOR["border"], height=1)
        line.pack(fill="x", pady=12)

        TitleLabel(b, "运行参数").pack(anchor="w", pady=(0, 10))
        for label, value in [
            ("运行模式", "有头（可视化）"),
            ("操作延迟", "随机 0.25 ~ 0.9 秒 / 步"),
            ("页面超时", "15 秒（元素） / 45 秒（导航）"),
            ("登录态存储", "artifacts/storage/"),
        ]:
            r = tk.Frame(b, bg=COLOR["bg_card"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=label, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text_dim"], width=12, anchor="w").pack(side="left")
            tk.Label(r, text=value, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text"]).pack(side="left")

    # ------------------------------------------------------------------ 交互

    def _detect_browser(self):
        """自动检测本机 Edge/Chrome，并把结果写进输入框与持久字段。"""
        try:
            from xyxbot.browser_detector import BrowserDetector
            path = BrowserDetector.get_recommended_browser()
            if path:
                self._browser_entry.set(path)
                self._browser_path_value = path   # ★ 同步到持久值
                self.log(f"检测到浏览器：{path}", "ok")
            else:
                self.log("未检测到可用浏览器", "warn")
        except Exception as e:
            self.log(f"检测失败：{e}", "err")
