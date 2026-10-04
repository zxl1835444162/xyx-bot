"""「概览面板」页。

从 `ui/main_window.py` 拆出的独立页面（架构改良阶段二）。
`MetricCard` 组件只被本页使用，因此一并从窗口模块搬过来。
"""

from __future__ import annotations

import tkinter as tk

from ..theme import COLOR, F, Card, DimLabel, TitleLabel


class MetricCard(tk.Frame):
    """指标卡：大数字 + 标签 + 说明。"""

    def __init__(self, master, label: str, value: str, sub: str,
                 accent: str = None, **kw):
        bg = COLOR["bg_card"]
        super().__init__(master, bg=bg, highlightbackground=COLOR["border"],
                         highlightthickness=1, **kw)
        accent = accent or COLOR["brand"]

        inner = tk.Frame(self, bg=bg)
        inner.pack(fill="both", expand=True, padx=14, pady=12)

        head = tk.Frame(inner, bg=bg)
        head.pack(fill="x")
        tk.Label(head, text=label, font=F(9), bg=bg,
                 fg=COLOR["text_dim"]).pack(side="left")
        tk.Label(head, text="◈", font=F(9), bg=bg,
                 fg=accent).pack(side="right")

        tk.Label(inner, text=value, font=F(20, True), bg=bg,
                 fg=accent).pack(anchor="w", pady=(8, 2))
        tk.Label(inner, text=sub, font=F(8), bg=bg,
                 fg=COLOR["text_mute"]).pack(anchor="w")


class OverviewPage:
    """「概览面板」页：运行状态指标卡 + 平台能力介绍。"""

    def _page_overview(self, parent):
        self._page_header(parent, "概览面板", "系统运行状态与核心指标")

        # 指标卡行
        row = tk.Frame(parent, bg=COLOR["bg_root"])
        row.pack(fill="x", pady=(0, 12))

        # ★ 只读一次登录态摘要（原来是 4 次重复的 _session_info()，
        #   等价于 4 次磁盘 JSON 读取）
        sess = self._session_info()
        saved = bool(sess.get("saved"))
        metrics = [
            ("已接入平台", "1", "星月写作", COLOR["brand"]),
            ("可用任务", str(len(self._task_names())), "自动化流程", COLOR["accent"]),
            ("浏览器内核", "Edge", "已就绪", COLOR["success"]),
            (
                "星月登录态",
                "已保存" if saved else "未登录",
                "免登录" if saved else "点「星月账号」登录",
                COLOR["success"] if saved else COLOR["warning"],
            ),
        ]
        for i, (label, value, sub, col) in enumerate(metrics):
            c = MetricCard(row, label=label, value=value, sub=sub, accent=col)
            c.pack(side="left", fill="both", expand=True,
                   padx=(0 if i == 0 else 10, 0))

        # 功能简介卡
        card = Card(parent)
        card.pack(fill="both", expand=True)
        b = card.body
        TitleLabel(b, "平台能力").pack(anchor="w")
        DimLabel(b, "面向内容工业化生产的自动化底座",
                 size=9).pack(anchor="w", pady=(3, 12))

        feats = [
            ("全流程自动化引擎", "从登录、建书到章节发布的端到端无人值守执行"),
            ("指纹级环境隔离", "真实浏览器内核配合独立会话，稳定且低特征"),
            ("智能风控适配", "自适应操作节奏与验证码感知，规避异常拦截"),
            ("章节资产中台", "自动拆分、字数核验与重复检测，素材一键入库"),
        ]
        for title, desc in feats:
            line = tk.Frame(b, bg=COLOR["bg_card"])
            line.pack(fill="x", pady=4)
            tk.Label(line, text="◈", font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["brand"]).pack(side="left", padx=(0, 8))
            tk.Label(line, text=title, font=F(10, True), bg=COLOR["bg_card"],
                     fg=COLOR["text"]).pack(side="left")
            tk.Label(line, text="  " + desc, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text_mute"]).pack(side="left")
