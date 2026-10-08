"""页面导航（标签 / 构建器表 / 切换）。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations

from xyxbot.ui.defaults import (APP_NAME, COMPANY, DEFAULT_PAGE, EXTRA_PAGES,
                       NAV_ITEMS, PAGE_ALIASES, VERSION)
from xyxbot.ui.theme import (COLOR, F, BrandButton, CheckBox, GradientBar, LogView,
                    StatusBar, bind_configure, bind_wheel, bind_wheel_all,
                    round_rect, unbind_wheel_all, wheel_units)
import tkinter as tk


class NavMixin:
    """页面导航（标签 / 构建器表 / 切换）。"""

    # ------------------------------------------------------------ 页面切换

    # 页面 key → 标签（导航项 + 额外页面 + 别名）
    def _page_labels(self) -> dict:
        d = {k: l for k, _i, l in NAV_ITEMS}
        d.update(EXTRA_PAGES)
        for old, new in PAGE_ALIASES.items():
            d[old] = d.get(new, new)
        return d

    def _page_builders(self) -> dict:
        """页面 key → 构建函数。

        ★ 原来 `content`（小说分章）页被拆成「跑章」+「准备」两部分；
          旧 key 通过 `PAGE_ALIASES` 落到 `run`，所以旧代码/链接不会 404。
        """
        return {
            # ---- 主导航三项 ----
            "run": self._page_run,
            "setup": self._page_setup,
            "more": self._page_more,
            # ---- 从导航撤下来、但「更多」页仍可进入的旧页面 ----
            "overview": self._page_overview,
            "account": self._page_account,
            "books": self._page_books,
            "tasks": self._page_tasks,
            "settings": self._page_settings,
            "about": self._page_about,
        }

    def show_page(self, key: str):
        key = PAGE_ALIASES.get(key, key)
        if key not in self._page_builders():
            self.log(f"未知页面：{key}", "warn")
            return

        for k, btn in self._nav_buttons.items():
            btn.set_active(k == key)
        self._current = key

        # ★★ 构建一次、之后只显示/隐藏（2026-10-04 界面重设计）
        #
        #   原实现每次切页都 `destroy()` 掉整页控件再重建，带来两个真实缺陷：
        #     ① **切页会丢编辑** —— 指令模板、章节细纲、跑章参数都没保存就没了
        #        （回来后是从 workspace.json 回填的旧值）；
        #     ② **后台任务回调炸控件** —— 任务里 `self.after(0, btn.set_text, …)`
        #        持有的按钮已被销毁，触发 TclError。
        #   页面只有 3~9 个，一次构建常驻的成本可以忽略。
        frame = self._pages.get(key)
        if frame is None:
            frame = tk.Frame(self.content, bg=COLOR["bg_root"])
            try:
                self._page_builders()[key](frame)
            except Exception as e:
                frame.destroy()
                import traceback
                self.log(f"页面「{self._page_labels().get(key, key)}」构建失败：{e}",
                         "err")
                self.log(traceback.format_exc().splitlines()[-1], "err")
                return
            self._pages[key] = frame

        for k, f in self._pages.items():
            try:
                if k == key:
                    f.pack(fill="both", expand=True)
                else:
                    f.pack_forget()
            except Exception:
                continue

        # 切页后回到顶部
        try:
            self._scroll_canvas.yview_moveto(0)
            self.after(60, lambda: self._scroll_canvas.yview_moveto(0))
            self.after(200, self._on_content_configure)
        except Exception:
            pass

        self.log(f"切换页面：{self._page_labels().get(key, key)}", "info")

    # ------------------------------------------------------------ 各页面

    def _page_header(self, parent, title: str, sub: str):
        box = tk.Frame(parent, bg=COLOR["bg_root"])
        box.pack(fill="x", pady=(6, 12))
        tk.Label(box, text=title, font=F(17, True),
                 bg=COLOR["bg_root"], fg=COLOR["text"]).pack(anchor="w")
        tk.Label(box, text=sub, font=F(9),
                 bg=COLOR["bg_root"], fg=COLOR["text_dim"]).pack(anchor="w", pady=(3, 0))
