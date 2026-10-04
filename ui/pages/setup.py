"""「准备」页 —— 一次性配置：登录态 + 运行环境（2026-10-04 界面重设计）。

用户原话：
    「我在操作上感觉很分散……我仅仅使用的功能，仅有这个流水化的
      从某章到某章的续写。」

所以把"每次作业都不变、只在环境变化时才动"的东西全部收到这里：

    * 登录态（打开网站 → 登录 → 保存 cookie/缓存；之后长期免登录）
    * 浏览器内核（Edge / Chrome / 内置 Chromium）与运行参数

★ 本页不重写登录逻辑，而是**组合**既有的两个页面实现：
    `_page_account(header=False)`  +  `_page_settings(header=False)`
  这样它们各自的按钮/回调/字段全部照旧生效，零重复代码。
"""

from __future__ import annotations

import tkinter as tk

from ..theme import COLOR, F, BrandButton, Card, DimLabel, TitleLabel


class SetupMixin:
    """「准备」页。"""

    def _page_setup(self, parent):
        self._page_header(parent, "准备",
                          "一次性配置：登录态 + 运行环境。跑章之前确保这里是绿的")

        # ★ 顶部一句"现在到底准备好了没"，省得还要自己判断
        card = Card(parent)
        card.pack(fill="x", pady=(0, 12))
        b = card.body
        row = tk.Frame(b, bg=COLOR["bg_card"])
        row.pack(fill="x")
        self._setup_dot = tk.Label(row, text="●", font=F(13),
                                   bg=COLOR["bg_card"], fg=COLOR["warning"])
        self._setup_dot.pack(side="left", padx=(0, 8))
        self._setup_lbl = tk.Label(row, text="正在读取…", font=F(11, True),
                                   bg=COLOR["bg_card"], fg=COLOR["text"])
        self._setup_lbl.pack(side="left")
        BrandButton(row, "刷新", width=80, height=30, style="ghost",
                    bg=COLOR["bg_card"], font_size=8,
                    command=self._refresh_setup).pack(side="right")
        self._setup_sub = DimLabel(b, "", size=8)
        self._setup_sub.pack(anchor="w", pady=(6, 0))

        # 组合既有的两块实现（各自不画页头）
        self._page_account(parent, header=False)
        self._page_settings(parent, header=False)

        # 本地小说那份"细纲"在跑章页④，这里只给个跳转提示
        tip = Card(parent)
        tip.pack(fill="x", pady=(12, 0))
        tb = tip.body
        TitleLabel(tb, "本地小说与细纲").pack(anchor="w")
        DimLabel(tb, "每章的 `#@` 细纲来自本地分章结果。它跟着「跑章」页走，"
                     "在那一页的 ④ 细纲来源 里配置。", size=9).pack(
            anchor="w", pady=(3, 8))
        BrandButton(tb, "去「跑章」页", width=140, height=34, style="ghost",
                    bg=COLOR["bg_card"],
                    command=lambda: self.show_page("run")).pack(anchor="w")

        self._refresh_setup()

    def _refresh_setup(self):
        """刷新「准备」页顶部状态。

        ★ 用 `_prepare_state()` 而不是 `_session_info()`：前者带
          `age`（"刚刚"/"1天前"）和现成的 `message`，后者只有
          saved/account/cookies。
        """
        try:
            info = self._prepare_state() or {}
        except Exception:
            info = {}
        saved = bool(info.get("saved"))
        msg = info.get("message") or ("登录态已保存" if saved else "尚未保存登录态")

        browser = ""
        try:
            browser = self._browser_path_override() or ""
        except Exception:
            browser = ""
        if not browser:
            try:
                from src.browser_detector import BrowserDetector

                browser = BrowserDetector.get_recommended_browser() or ""
            except Exception:
                browser = ""

        try:
            self._setup_dot.config(
                fg=COLOR["success"] if saved else COLOR["warning"])
            self._setup_lbl.config(text=msg)
            self._setup_sub.config(
                text=(f"登录态：{'已保存' if saved else '未保存'}"
                      + (f"（{info.get('age')}）" if info.get("age") else "")
                      + "   ·   浏览器内核："
                      + (browser or "未检测到（将用内置 Chromium）")))
        except Exception:
            pass
