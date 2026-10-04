"""登录窗口：赵氏集团 · 星月创作台。

启动时先显示本窗口，校验通过后回调进入主界面。
校验逻辑：本地授权码（先占位，后续可换成服务端校验）。
"""

from __future__ import annotations

import hashlib
import tkinter as tk
from typing import Callable, Optional

from .theme import (
    COLOR, F, BrandButton, CheckBox, DarkEntry, GradientBar, Toast,
    _lerp_color, round_rect,
)

APP_NAME = "星月创作台"
COMPANY = "赵氏集团"
VERSION = "v1.0.0"

# 内置授权码（演示用）。生产环境应改为服务端校验。
VALID_KEYS = {
    "ZSJT-2026-VIP",
    "zhaoshi-admin",
}

HIGHLIGHTS = [
    ("◈", "全流程自动化引擎", "从登录、建书到章节发布，端到端无人值守"),
    ("◈", "多平台内容分发", "统一调度多站点账号，一次编排批量投递"),
    ("◈", "指纹级环境隔离", "真实浏览器内核 + 独立会话，稳定且隐蔽"),
    ("◈", "智能风控适配", "自适应限速与验证码感知，规避异常拦截"),
    ("◈", "章节资产中台", "自动拆分 / 字数核验 / 重复检测，素材一键入库"),
    ("◈", "实时日志追踪", "全链路操作留痕，异常现场自动截图存档"),
]


class LoginWindow(tk.Toplevel):
    """登录窗口。成功后调用 on_success(username)。

    ★★★ 为什么是 `tk.Toplevel` 而不是 `tk.Tk`（2026-10-04，真机复现）
    =====================================================================

    在 macOS 上，**一个进程里第 2 个 `tk.Tk()` 的 `mainloop()` 收不到任何事件**：
    窗口不绘制、`after` 定时器不触发、鼠标一直转圈，而且**不抛异常** ——
    所以既没有弹窗也没有日志。用户在 mac 上看到的就是「点登录后登录窗没了、
    鼠标转圈、主界面永远不出来」。

    实测（GitHub 的 macOS runner，真机）：
        ★ 卡死了：主线程已 20.4 秒没有任何进展
           最后一次进展：MainWindow.__init__ 结束   ← 第 2 个 root 已经建好
           平台：darwin                              ← 它的 mainloop 却不工作
        而**第 1 个 root（登录窗）的 after(900) 是正常触发的**。

    所以规则是：**整个程序只能有一个 `tk.Tk()`**。
    由 `run_gui.run_app` 建一次并 `withdraw()` 当事件循环宿主；
    登录窗和主界面都是它的 `Toplevel` —— 共享同一个解释器、同一个事件循环。
    切换窗口 = 销毁一个 Toplevel + 建另一个，永远不会出现"第 2 个 root"。

    `master=None` 时（单独用/单元测试）会自动建一个自己的 Tk root，
    这样 `LoginWindow(on_success=...)` 这种老写法也不会报错。
    """

    def __init__(self, master=None,
                 on_success: Optional[Callable[[str], None]] = None,
                 on_cancel: Optional[Callable[[], None]] = None):
        # ★ 兼容老写法：不传 master 就自己建一个 root（并藏起来）
        if master is None:
            master = tk.Tk()
            try:
                master.withdraw()
            except Exception:
                pass
            self._owns_root = True
        else:
            self._owns_root = False
        super().__init__(master)
        self._on_success = on_success
        self._on_cancel = on_cancel

        self.title(f"{COMPANY} · {APP_NAME}")
        self.configure(bg=COLOR["bg_root"])
        self.geometry("880x580")
        self.minsize(880, 580)
        self.resizable(False, False)
        self._center(880, 580)

        self._build()
        self._load_saved_credentials()
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------ 凭据

    def _load_saved_credentials(self):
        """启动时把已保存的账号密码回填到表单。"""
        try:
            from src import credentials as cred

            saved = cred.load()
        except Exception:
            return

        if not saved.get("remember"):
            self.hint_label.configure(text="")
            return

        self.entry_user.set(saved.get("username", ""))
        self.entry_key.set(saved.get("password", ""))
        self.cb_remember.set(True)
        self.hint_label.configure(text="已载入上次保存的账号密码")

    def _on_remember_toggle(self, checked: bool):
        """取消「记住账号密码」时立即清除已存凭据。"""
        if not checked:
            try:
                from src import credentials as cred

                cred.clear()
            except Exception:
                pass
            self.hint_label.configure(text="已清除保存的账号密码")
        else:
            self.hint_label.configure(text="")

    # ------------------------------------------------------------ 布局

    def _center(self, w: int, h: int):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = int((sw - w) / 2)
        y = int((sh - h) / 2.6)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self):
        root = tk.Frame(self, bg=COLOR["bg_root"])
        root.pack(fill="both", expand=True)

        # 左侧品牌区（固定 400px）
        left = tk.Canvas(root, width=400, bg=COLOR["bg_card"],
                         highlightthickness=0, bd=0)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        left.bind("<Configure>", lambda e: self._draw_left(left))

        # 右侧表单区（占满剩余宽度）
        right = tk.Frame(root, bg=COLOR["bg_root"], width=480)
        right.pack(side="left", fill="both", expand=True)
        right.pack_propagate(False)
        self._build_form(right)

    def _draw_left(self, c: tk.Canvas):
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10:
            return

        # 竖向渐变底
        n = 60
        for i in range(n):
            t = i / n
            col = _lerp_color("#171208", "#0d1117", t)
            c.create_rectangle(0, h * i / n, w, h * (i + 1) / n,
                               fill=col, outline="")

        # 品牌光晕（低对比，避免压住文字）
        c.create_oval(-140, -160, 300, 200, fill="#1c1408", outline="")
        c.create_oval(200, h - 240, w + 140, h + 60, fill="#151007", outline="")

        cx = 56
        # 徽标方块
        round_rect(c, cx, 88, cx + 56, 144, 12,
                   fill=COLOR["brand"], outline="")
        c.create_text(cx + 28, 116, text="赵", font=F(24, True),
                      fill=COLOR["text_on_brand"])

        c.create_text(cx, 178, anchor="w", text=COMPANY, font=F(21, True),
                      fill=COLOR["text"])
        c.create_text(cx, 210, anchor="w", text="ZHAOSHI  GROUP",
                      font=("Consolas", 9), fill=COLOR["brand"])

        # 分隔线
        c.create_line(cx, 238, cx + 300, 238, fill=COLOR["border"])

        c.create_text(cx, 262, anchor="w", text=APP_NAME, font=F(14, True),
                      fill=COLOR["brand_hi"])
        c.create_text(cx, 288, anchor="w",
                      text="AI 内容工业化生产平台",
                      font=F(10), fill=COLOR["text_dim"])

        # 亮点列表
        y = 336
        for sym, title, _ in HIGHLIGHTS[:3]:
            c.create_text(cx, y, anchor="w", text=sym,
                          font=F(9), fill=COLOR["brand"])
            c.create_text(cx + 20, y, anchor="w", text=title,
                          font=F(10, True), fill=COLOR["text"])
            y += 30

        # 版本
        c.create_text(cx, h - 40, anchor="w",
                      text=f"{VERSION}   ·   Enterprise Edition",
                      font=F(8), fill=COLOR["text_mute"])

    def _build_form(self, parent: tk.Frame):
        # 用 grid 把表单整体在右侧容器里居中，比 place 更稳
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        wrap = tk.Frame(parent, bg=COLOR["bg_root"])
        wrap.grid(row=0, column=0)

        tk.Label(wrap, text="欢迎回来", font=F(19, True),
                 bg=COLOR["bg_root"], fg=COLOR["text"]).pack(anchor="w")
        tk.Label(wrap, text="请使用授权凭证登录以继续",
                 font=F(9), bg=COLOR["bg_root"],
                 fg=COLOR["text_dim"]).pack(anchor="w", pady=(4, 18))

        # 账号
        tk.Label(wrap, text="授权账号", font=F(9),
                 bg=COLOR["bg_root"], fg=COLOR["text_dim"]).pack(anchor="w")
        self.entry_user = DarkEntry(wrap, placeholder="请输入授权账号",
                                    icon="◈", width=300, height=40)
        self.entry_user.pack(anchor="w", pady=(5, 12))

        # 授权码
        tk.Label(wrap, text="授权凭证", font=F(9),
                 bg=COLOR["bg_root"], fg=COLOR["text_dim"]).pack(anchor="w")
        self.entry_key = DarkEntry(wrap, placeholder="请输入授权凭证",
                                   icon="◈", show="●", width=300, height=40)
        self.entry_key.pack(anchor="w", pady=(5, 8))

        # 记住账号密码
        opt = tk.Frame(wrap, bg=COLOR["bg_root"])
        opt.pack(anchor="w", pady=(0, 8))

        self.cb_remember = CheckBox(
            opt, "记住账号密码", checked=False, width=136, height=22,
            bg=COLOR["bg_root"], command=self._on_remember_toggle,
        )
        self.cb_remember.pack(side="left")

        # 提示行
        self.hint_label = tk.Label(
            wrap, text="", font=F(8), height=1,
            bg=COLOR["bg_root"], fg=COLOR["text_mute"],
        )
        self.hint_label.pack(anchor="w", pady=(0, 4))

        # 错误提示（固定高度，避免出现时把按钮顶下去）
        self.err_label = tk.Label(wrap, text="", font=F(9), height=1,
                                  bg=COLOR["bg_root"], fg=COLOR["danger"])
        self.err_label.pack(anchor="w", pady=(0, 6))

        # 登录按钮
        self.btn_login = BrandButton(wrap, "登 录", command=self._do_login,
                                     width=300, height=42, style="primary",
                                     bg=COLOR["bg_root"], font_size=11)
        self.btn_login.pack(anchor="w")

        # 提示
        tk.Label(wrap, text="演示授权码：ZSJT-2026-VIP",
                 font=F(8), bg=COLOR["bg_root"],
                 fg=COLOR["text_mute"]).pack(anchor="w", pady=(10, 0))

        # 回车提交
        self.bind("<Return>", lambda e: self._do_login())
        self.after(200, self.entry_key.focus)

    # ------------------------------------------------------------ 逻辑

    def _do_login(self):
        user = self.entry_user.get().strip()
        key = self.entry_key.get().strip()

        if not user:
            self._err("请输入授权账号")
            return
        if not key:
            self._err("请输入授权凭证")
            return

        if key not in VALID_KEYS:
            self._err("授权凭证无效，请重新输入")
            self.entry_key.set("")
            return

        # 保存或清除凭据
        self._persist_credentials(user, key)

        self._err("")
        self.btn_login.set_enabled(False)
        self.btn_login.set_text("正在验证…")
        self.update_idletasks()
        self.after(420, lambda: self._enter(user))

    def _persist_credentials(self, user: str, key: str):
        """按勾选状态保存或清除凭据。"""
        try:
            from src import credentials as cred
        except Exception:
            return

        if self.cb_remember.get():
            cred.save(user, key, remember=True)
            self.hint_label.configure(text="已记住账号密码")
        else:
            cred.clear()

    def _err(self, msg: str):
        self.err_label.configure(text=msg)
        # 有错误时清掉"已记住"的提示，避免混淆
        if msg:
            self.hint_label.configure(text="")

    def _enter(self, user: str):
        """登录成功：**只把结果交出去**，窗口的销毁/切换由外层负责。

        ★ 这里以前是 `self.destroy()` + `self._on_success(user)`，而
          `_on_success` 会去建**第 2 个 `tk.Tk()` root** —— 在 macOS 上
          第 2 个 root 的事件循环是不工作的（详见类 docstring 的实测）。
          现在改成：只回调，由 `run_gui.run_app` 用同一个 root 换窗口。
        """
        if self._on_success:
            self._on_success(user)

    def _close(self):
        if self._on_cancel:
            self._on_cancel()
        self.destroy()
