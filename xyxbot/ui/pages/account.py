"""「星月账号」页 + 流程准备（登录态管理）。

从 ui/main_window.py 拆出的独立页面（架构改良阶段二）。

包含两块：
  * 「星月账号」页：登录 / 校验 / 清除 / 状态详情
  * 「流程准备」卡片的动作：打开网站并保存、我已登录立即保存、刷新、清除

★ 注意：_ensure_app / _browser_path_override / _stop_app 属于**浏览器
  生命周期**（被多个页面共用），保留在 MainWindow 里，不随本模块搬走。
"""

from __future__ import annotations

import threading
import tkinter as tk

from ..theme import (COLOR, F, BrandButton, Card, DimLabel, TitleLabel)


class AccountPage:
    """「星月账号」页 + 流程准备动作。"""

    def _page_account(self, parent, header: bool = True):
        """星月账号 —— 登录一次的入口，之后长期免登录。

        Args:
            header: 是否自己画页头。`False` 时用于被「准备」页组合进去
                    （否则会出现两个页头）。
        """
        if header:
            self._page_header(parent, "星月账号",
                              "登录一次，之后自动复用会话，无需重复登录")

        # ---------- 状态卡 ----------
        card = Card(parent)
        card.pack(fill="x", pady=(0, 12))
        b = card.body

        head = tk.Frame(b, bg=COLOR["bg_card"])
        head.pack(fill="x")

        info = self._session_info()
        saved = info.get("saved", False)

        # 状态圆点 + 标题
        dot = tk.Canvas(head, width=12, height=12, bg=COLOR["bg_card"],
                        highlightthickness=0, bd=0)
        dot.pack(side="left", pady=(4, 0))
        dot.create_oval(1, 1, 11, 11,
                        fill=COLOR["success"] if saved else COLOR["text_mute"],
                        outline="")

        tk.Label(head, text="  登录态", font=F(12, True), bg=COLOR["bg_card"],
                 fg=COLOR["text"]).pack(side="left")

        self._acc_badge = tk.Label(
            head,
            text="已保存 · 免登录" if saved else "未登录",
            font=F(9), bg=COLOR["bg_card"],
            fg=COLOR["success"] if saved else COLOR["warning"],
        )
        self._acc_badge.pack(side="left", padx=(10, 0))

        # 详情行
        self._acc_detail = tk.Frame(b, bg=COLOR["bg_card"])
        self._acc_detail.pack(fill="x", pady=(12, 0))
        self._render_session_detail()

        # ---------- 操作卡 ----------
        card2 = Card(parent)
        card2.pack(fill="both", expand=True)
        b2 = card2.body

        TitleLabel(b2, "操作").pack(anchor="w")
        DimLabel(b2, "点「登录星月账号」→ 在弹出的浏览器里完成登录 → "
                     "点「我已登录，立即保存」把会话存下来。之后一律免登录",
                 size=9).pack(anchor="w", pady=(3, 14))

        btns = tk.Frame(b2, bg=COLOR["bg_card"])
        btns.pack(anchor="w")

        BrandButton(btns, "登录星月账号", width=150, height=38,
                    bg=COLOR["bg_card"],
                    command=self._start_login).pack(side="left")

        # ★ 手动确认按钮：不依赖自动判定，你说了算
        self._btn_save_session = BrandButton(
            btns, "我已登录，立即保存", width=170, height=38,
            style="ghost", bg=COLOR["bg_card"],
            command=self._confirm_logged_in)
        self._btn_save_session.pack(side="left", padx=(10, 0))

        btns2 = tk.Frame(b2, bg=COLOR["bg_card"])
        btns2.pack(anchor="w", pady=(10, 0))

        BrandButton(btns2, "校验登录态", width=120, height=34, style="ghost",
                    bg=COLOR["bg_card"],
                    command=self._verify_session).pack(side="left")
        BrandButton(btns2, "清除登录态", width=120, height=34, style="ghost",
                    bg=COLOR["bg_card"],
                    command=self._clear_session).pack(side="left", padx=(10, 0))

        # 提示：什么时候该点「我已登录，立即保存」
        DimLabel(b2, "提示：如果浏览器里明明登录成功了、程序却没自动记录，"
                     "就点「我已登录，立即保存」—— 以你看到的为准",
                 size=8).pack(anchor="w", pady=(10, 0))

        line = tk.Frame(b2, bg=COLOR["border"], height=1)
        line.pack(fill="x", pady=14)

        TitleLabel(b2, "它是怎么工作的", size=11).pack(anchor="w", pady=(0, 8))
        for step, desc in [
            ("① 登录一次", "在弹出浏览器里完成扫码 / 账号密码登录"),
            ("② 保存会话", "自动检测成功就自动存；没检测到就点「我已登录，立即保存」"),
            ("③ 长期复用", "以后每次启动浏览器都注入这份会话，等同于「已登录」"),
            ("④ 过期兜底", "万一站点让会话失效，再点一次登录即可，无需重装"),
        ]:
            r = tk.Frame(b2, bg=COLOR["bg_card"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=step, font=F(9, True), bg=COLOR["bg_card"],
                     fg=COLOR["brand"], width=12, anchor="w").pack(side="left")
            tk.Label(r, text=desc, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text_dim"]).pack(side="left")

        # 文件路径提示
        DimLabel(b2, f"登录态文件：{info.get('path', '')}",
                 size=8).pack(anchor="w", pady=(14, 0))

    def _session_info(self) -> dict:
        try:
            from xyxbot import session as S
            return S.describe()
        except Exception:
            return {"saved": False, "saved_at": "", "cookies": 0,
                    "account": "", "path": "", "size": "-"}

    def _render_session_detail(self):
        """刷新状态卡里的详情行。"""
        for w in self._acc_detail.winfo_children():
            w.destroy()

        info = self._session_info()
        saved = info.get("saved", False)

        if saved:
            try:
                from xyxbot import session as S
                age = S.age_text()
            except Exception:
                age = ""
            rows = [
                ("登录时间", info.get("saved_at") or "未知"),
                ("会话时长", age or "未知"),
                ("Cookie", f"{info.get('cookies', 0)} 条"),
                ("文件大小", info.get("size", "-")),
            ]
            if info.get("account"):
                rows.insert(0, ("登录账号", info["account"]))
        else:
            rows = [
                ("状态", "尚未登录星月写作"),
                ("说明", "点下方「登录星月账号」完成首次登录即可"),
            ]

        for k, v in rows:
            r = tk.Frame(self._acc_detail, bg=COLOR["bg_card"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=k, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text_dim"], width=12, anchor="w").pack(side="left")
            tk.Label(r, text=v, font=F(9), bg=COLOR["bg_card"],
                     fg=COLOR["text"]).pack(side="left")

    def _refresh_account_page(self):
        """重新渲染账号页（切换登录态后调用）。"""
        if self._current == "account":
            self.show_page("account")

    # ---- 登录流程（关键：登录不限时，随时可手动确认保存）----

    def _start_login(self):
        """启动登录流程：后台线程跑 ensure_login，不阻塞 UI。

        登录过程**不设超时上限** —— 你在浏览器里慢慢登录，
        程序会一直等；你也可以随时点「我已登录，立即保存」提前结束。
        """
        import threading

        if getattr(self, "_login_running", False):
            self.log("登录流程已在进行中，请先在浏览器完成登录", "warn")
            return

        self._login_running = True
        self._login_stop = threading.Event()

        self.log("=" * 46, "brand")
        self.log("开始登录星月账号 —— 请在弹出的浏览器里完成登录", "brand")
        self.log("登录完成后：自动检测会自动保存；若没反应，", "info")
        self.log("请回到本窗口点「我已登录，立即保存」", "info")
        self.log("=" * 46, "brand")
        self.status.set_status("等待登录中…", "warn")
        self._keep_on_top(True)

        def worker():
            try:
                from xyxbot.app import App
                from xyxbot import login as L
                from xyxbot.logging_redirect import LogRedirector

                if self._app is None:
                    self._app = App(headless=False,
                                    browser_path=self._browser_path_override())
                    self._app.start(with_log_file=True)

                rd = LogRedirector(
                    sink=lambda m: self.after(0, self.log, m, "info")
                ).install()
                try:
                    # wait_seconds=0 → 不限时，等你确认
                    ok = L.ensure_login(self._app, wait_seconds=0,
                                        stop_event=self._login_stop)
                finally:
                    rd.restore()

                msg = "登录态已就绪 ✓  以后无需再登录" if ok else "未取得登录态 ✗"
                self.after(0, self.log, msg, "ok" if ok else "err")
                self.after(0, self.status.set_status, msg, "ok" if ok else "err")
            except Exception as e:
                self.after(0, self.log, f"登录异常：{e}", "err")
                self.after(0, self.status.set_status, f"异常：{e}", "err")
            finally:
                self._login_running = False
                self.after(0, self._keep_on_top, False)
                self.after(0, self._refresh_account_page)

        self.session.submit(worker)

    def _confirm_logged_in(self):
        """「我已登录，立即保存」—— 以用户看到的为准，强制导出登录态。"""
        import threading

        if not getattr(self, "_login_running", False):
            # 登录流程没在跑，也允许单独保存（比如你手动开的浏览器已被接管）
            self.log("当前没有进行中的登录流程，直接尝试导出登录态…", "warn")

        # 先通知等待中的登录线程保存
        if getattr(self, "_login_stop", None) is not None:
            self._login_stop.set()

        self.log("收到「我已登录」—— 正在导出登录态 …", "brand")
        self.status.set_status("正在保存登录态…", "warn")

        def worker():
            try:
                import time as _t
                from xyxbot import session as S

                # 等一下让登录线程自己保存
                _t.sleep(1.5)

                if S.exists():
                    info = S.describe()
                    msg = (f"登录态已保存 ✓  Cookie {info['cookies']} 条"
                           f"（{info['size']}）")
                    self.after(0, self.log, msg, "ok")
                    self.after(0, self.status.set_status,
                               "登录态已保存 ✓", "ok")
                    self.after(0, self._refresh_account_page)
                    return

                # 登录线程没保存成功，这里兜底再存一次
                if self._app is not None and self._app.context is not None:
                    ok = S.save_from_context(self._app.context)
                    if ok:
                        self.after(0, self.log, "登录态已保存 ✓", "ok")
                        self.after(0, self.status.set_status,
                                   "登录态已保存 ✓", "ok")
                        self.after(0, self._refresh_account_page)
                        return

                self.after(0, self.log,
                           "导出失败：浏览器还没启动？请先点「登录星月账号」", "err")
                self.after(0, self.status.set_status, "保存失败", "err")
            except Exception as e:
                self.after(0, self.log, f"保存异常：{e}", "err")
                self.after(0, self.status.set_status, f"异常：{e}", "err")

        self.session.submit(worker)

    def _verify_session(self):
        """后台线程校验登录态，避免卡 UI。"""
        import threading

        self.log("开始校验登录态…", "brand")
        self.status.set_status("校验登录态…", "warn")

        def worker():
            try:
                from xyxbot.app import App
                from xyxbot import login as L
                from xyxbot.logging_redirect import LogRedirector

                if self._app is None:
                    self._app = App(headless=False,
                                    browser_path=self._browser_path_override())
                    self._app.start(with_log_file=True)

                rd = LogRedirector(
                    sink=lambda m: self.after(0, self.log, m, "info")
                ).install()
                try:
                    ok = L.verify_session(self._app)
                finally:
                    rd.restore()

                msg = "登录态有效 ✓" if ok else "登录态无效 / 已过期 ✗"
                self.after(0, self.log, msg, "ok" if ok else "warn")
                self.after(0, self.status.set_status, msg, "ok" if ok else "warn")
                self.after(0, self._refresh_account_page)
            except Exception as e:
                self.after(0, self.log, f"校验异常：{e}", "err")
                self.after(0, self.status.set_status, f"异常：{e}", "err")

        self.session.submit(worker)

    def _clear_session(self):
        """清除登录态，需要二次确认。

        ★ 要**先关浏览器**再删文件 —— 否则浏览器里的 cookie 还在，
          下次准备时会被重新保存回来（见 `_stop_app` 的说明）。
        """
        from tkinter import messagebox

        ok = messagebox.askyesno(
            "清除登录态",
            "将关闭浏览器并清除已保存的登录态。\n"
            "清除后需要重新登录星月写作，确定吗？",
            parent=self,
        )
        if not ok:
            return
        # ① 先关浏览器（★ 投递到 Playwright 常驻线程，不跨线程操作）
        self.log("正在关闭浏览器（清掉内存里的 cookie）…", "info")
        self._stop_app()
        # ② 再删文件
        try:
            from xyxbot import session as S

            S.clear()
            self.log("已清除本机登录态，下次使用需重新登录", "warn")
            self.status.set_status("登录态已清除", "warn")
        except Exception as e:
            self.log(f"清除失败：{e}", "err")
        self._prepare_refresh()
        self._refresh_account_page()

    # ------------------------------------------------ ★ 流程准备（一条龙前置）
    #
    #  用户需求（2026-10-03）：
    #    在所有的流程开始之前，有一个打开网站提前配置，
    #    然后进行 cookie 或者缓存保存的功能，
    #    然后之后点击一条龙服务，就直接开始。

    def _prepare_state(self) -> dict:
        """读准备状态（不启动浏览器，纯本地查询）。"""
        try:
            from xyxbot import login as L
            return L.is_ready()
        except Exception as e:
            return {"ok": False, "saved": False, "cookies": 0,
                    "account": "", "saved_at": "", "age": "",
                    "message": f"读取登录态失败：{e}"}

    def _prepare_refresh(self):
        """刷新准备状态灯（不打开浏览器）。"""
        st = self._prepare_state()
        dot = getattr(self, "_prepare_dot", None)
        lbl = getattr(self, "_prepare_lbl", None)
        try:
            if dot is not None:
                dot.config(fg=COLOR["success"] if st["ok"] else COLOR["warning"])
            if lbl is not None:
                lbl.config(text=st["message"],
                           fg=COLOR["text"] if st["ok"] else COLOR["warning"])
        except Exception:
            pass
        self.log(("✓ " if st["ok"] else "⚠ ") + st["message"],
                 "ok" if st["ok"] else "warn")
        return st

    def _ensure_app(self):
        """按需创建并启动 App（浏览器）。已有的直接复用。

        ★ 只能在常驻 Playwright 线程里调用（即从 `self.session.submit(...)`
        投递进来的 worker 中）。
        实现委托给 `BrowserSession.ensure_app()`。
        """
        app = self.session.ensure_app()
        self._app = app          # 兼容旧字段（页面代码里还在读 self._app）
        return app

    def _browser_path_override(self):
        """读「运行配置」页里用户填的浏览器路径（留空 = 自动检测）。

        ★ 读的是持久字段 `_browser_path_value`，不是控件 ——
          因为切页会销毁 `_browser_entry`，随后启动浏览器时控件已不存在。
        """
        try:
            if self._browser_entry.winfo_exists():
                self._browser_path_value = (
                    self._browser_entry.get() or "").strip().strip('"')
        except Exception:
            pass          # 控件已销毁 → 沿用上次记录的值
        return self._browser_path_value or None

    def _stop_app(self):
        """★ 线程安全地关掉 App（浏览器）。

        ★ 根因修复（跨线程 bug）：
          `App` / `browser` / `context` 是在**常驻 Playwright 线程**里创建的，
          而 `App.stop()` 会 close context 并停掉 playwright ——
          如果直接在 Tk 主线程调用，就违反「Playwright 对象必须同线程操作」
          这条铁律（源码在 `__init__` 的注释里已明确写下），
          轻则报 `cannot switch to a different thread`，重则与队列里
          尚未执行的任务竞争。

          实现委托给 `BrowserSession.stop()`：它把 `app.stop()` 投递到
          常驻线程里执行，并立刻断开引用避免后续任务复用。
        """
        self._app = None
        self.session.stop(
            on_done=lambda e: self._session_log(
                f"关闭浏览器时出错（忽略）：{e}", "warn"))

    def _prepare_go(self):
        """★「① 打开网站并保存」—— 打开网站、登录、把 cookie/缓存存下来。"""
        if getattr(self, "_prepare_running", False):
            self.log("准备流程已在进行中，请在浏览器里完成", "warn")
            return
        self._prepare_running = True
        self._prepare_stop = None
        self.log("开始流程准备：打开网站 → 检测/登录 → 保存 cookie 与缓存", "brand")
        self.status.set_status("准备中…（如需登录请在弹出的浏览器里完成）", "warn")
        _btn = getattr(self, "_btn_prepare", None)
        if _btn is not None:
            try:
                _btn.config(state="disabled")
            except Exception:
                pass

        def worker():
            try:
                from xyxbot.logging_redirect import LogRedirector
                app = self._ensure_app()
                rd = LogRedirector(
                    sink=lambda m: self.after(0, self.log, m, "info")
                ).install()
                try:
                    from xyxbot import login as L
                    r = L.prepare_session(app, save=True, auto=True,
                                          wait_seconds=0, interactive=True)
                finally:
                    rd.restore()
                self.after(0, self._on_prepare_done, r)
            except Exception as e:
                self.after(0, self.log, f"准备异常：{e}", "err")
                self.after(0, self.status.set_status, f"准备异常：{e}", "err")
                self.after(0, self._prepare_refresh)
            finally:
                self._prepare_running = False
                _btn2 = getattr(self, "_btn_prepare", None)
                if _btn2 is not None:
                    try:
                        self.after(0, _btn2.config, {"state": "normal"})
                    except Exception:
                        pass

        # ★ 投递常驻 Playwright 线程（避免跨线程操作浏览器）
        self.session.submit(worker)

    def _on_prepare_done(self, r: dict):
        ok = bool(r.get("ok"))
        self._prepare_refresh()
        if ok:
            self.log(f"✓ 准备就绪（{r.get('mode')} · {r.get('cookies')} 条 cookie）"
                     f" —— 现在可以直接点「一条龙」", "ok")
            self.status.set_status("准备就绪 · 可直接点一条龙", "ok")
        else:
            self.log(f"⚠ {r.get('message')}", "warn")
            self.status.set_status("准备未完成：请先登录并保存", "warn")

    def _prepare_save_now(self):
        """★「我已登录，立即保存」—— 以用户看到的为准，强制导出 cookie。"""
        self.log("收到「我已登录」—— 正在导出 cookie 与缓存 …", "brand")

        def worker():
            try:
                app = self._app
                if app is None or app.context is None:
                    # ★ 线程安全：worker 在常驻 pw 线程上跑，必须经 after 回主线程写日志
                    self.after(0, self.log,
                               "当前没有已启动的浏览器，请先点「① 打开网站并保存」",
                               "warn")
                    return
                from xyxbot.logging_redirect import LogRedirector
                rd = LogRedirector(
                    sink=lambda m: self.after(0, self.log, m, "info")
                ).install()
                try:
                    from xyxbot import login as L
                    ok = L.save_session(app.context, quiet=False)
                finally:
                    rd.restore()
                self.after(0, self.log,
                           "✓ 登录态已保存，以后免登录" if ok else "✗ 保存失败",
                           "ok" if ok else "err")
                self.after(0, self._prepare_refresh)
            except Exception as e:
                self.after(0, self.log, f"保存异常：{e}", "err")

        self.session.submit(worker)

    def _prepare_clear(self):
        """★ 清除登录态（真·登出）。

        ★ 实测坑（2026-10-03）：只删 state.json 是不够的 ——
          如果**浏览器进程还活着**，里面的 cookie 还在，
          下一次「准备」打开网站时会发现「居然还是登录的」，
          于是又把它保存回来了（日志显示 `尚无登录态` 紧接着 `已保存`）。
        所以必须先关浏览器（App.stop）再删文件，这样才是真的登出。

        ★ 重构（去重）：这里原本是与 `_clear_session` 几乎逐行重复的第二份实现
          （前面还有一个只有 docstring 的存根被静默覆盖）。
          现在统一委托给 `_clear_session`，保证两条入口行为永远一致。
        """
        self._clear_session()
