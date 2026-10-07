"""「更多」页 —— 旧功能的入口（2026-10-04 界面重设计）。

用户原话：「很多多余的功能，是不要的。」

这些页面**没有删**（删了万一要用就找不回来，而且它们各自有独立测试），
只是**从主导航里撤掉**，集中收到这一页。主界面因此只剩三个入口：

    ▶ 跑章   ← 99% 的时间只在这一页
    ⚙ 准备   ← 一次性环境配置
    ☰ 更多   ← 需要时才进（本页）

本页只是「入口列表」：点一项就 `show_page(key)` 切过去。
"""

from __future__ import annotations

import tkinter as tk

from ..theme import COLOR, F, BrandButton, Card, DimLabel, TitleLabel

# (页面 key, 标题, 说明)
MORE_ITEMS = [
    ("overview", "概览面板", "运行状态指标卡（纯展示，不影响任何流程）"),
    ("account", "星月账号", "完整的登录 / 校验 / 登出界面（同「准备」页）"),
    ("books", "打开作品", "单独打开一个作品；「跑章」里会自动打开，一般用不到"),
    ("tasks", "任务中心", "执行注册好的 CLI 任务（命令行时代的遗留入口）"),
    ("settings", "运行配置", "浏览器内核路径与只读运行参数（同「准备」页）"),
    ("about", "关于本机", "版本信息与项目说明"),
]


class MorePage:
    """「更多」页。"""

    def _page_more(self, parent):
        self._page_header(parent, "更多",
                          "旧功能入口。主流程（跑章）用不到它们，需要时才进来")

        card = Card(parent)
        card.pack(fill="x")
        b = card.body
        TitleLabel(b, "其它页面").pack(anchor="w")
        DimLabel(b, "这些页面在界面精简后从左侧导航撤掉了，功能本身都还在。",
                 size=9).pack(anchor="w", pady=(3, 12))

        for key, title, desc in MORE_ITEMS:
            row = tk.Frame(b, bg=COLOR["bg_card"])
            row.pack(fill="x", pady=3)

            BrandButton(row, "打开", width=76, height=32, style="ghost",
                        bg=COLOR["bg_card"], font_size=9,
                        command=lambda k=key: self.show_page(k)).pack(
                side="left")
            tk.Label(row, text="  " + title, font=F(10, True),
                     bg=COLOR["bg_card"], fg=COLOR["text"]).pack(side="left")
            tk.Label(row, text="   " + desc, font=F(8), bg=COLOR["bg_card"],
                     fg=COLOR["text_mute"]).pack(side="left")

        back = tk.Frame(b, bg=COLOR["bg_card"])
        back.pack(fill="x", pady=(16, 0))
        BrandButton(back, "← 回到「跑章」", width=160, height=38,
                    bg=COLOR["bg_card"],
                    command=lambda: self.show_page("run")).pack(side="left")
