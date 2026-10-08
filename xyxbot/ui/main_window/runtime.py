"""浏览器会话与任务执行（含互斥守卫 _run_guarded）。

由 `xyxbot/ui/main_window.py` 拆分而来（class split）：只搬位置、
不改逻辑（方法体、注释、装饰器、超时值全部原样）。
"""

from __future__ import annotations


class RuntimeMixin:
    """浏览器会话与任务执行（含互斥守卫 _run_guarded）。"""

    # ---- 登录流程（关键：登录不限时，随时可手动确认保存）----

    # ------------------------------------------------ ★ 流程准备（一条龙前置）
    #
    #  用户需求（2026-10-03）：
    #    在所有的流程开始之前，有一个打开网站提前配置，
    #    然后进行 cookie 或者缓存保存的功能，
    #    然后之后点击一条龙服务，就直接开始。

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

    # ------------------------------------------------------------ 打开作品

    # -------------------------------------------------- 一步到位：打开作品

    # -------------------------------------------------- 同名候选

    # -------------------------------------------------- 查看全部

    def _ensure_page(self):
        """确保 App 与浏览器已启动，返回 page（阻塞，供后台线程调用）。"""
        from xyxbot.app import App

        if self._app is None:
            self._app = App(headless=False,
                                    browser_path=self._browser_path_override())
            self._app.start(with_log_file=True)
        return self._app.page

    # -------------------------------------------------- 工作区配置

    # -------------------------------------------------- 选文件 / 分章

    # -------------------------------------------------- ★ 指令模板

    # -------------------------------------------------- 一键 AI 续写

    # -------------------------------------------------- AI 审稿

    # -------------------------------------------------- ★ 续写 + 审稿 一条龙

    # -------------------------------------------------- ★ 批量跑章

    # -------------------------------------------------- 保存 / 读取工程

    # ------------------------------------------------------------ 交互

    def _task_names(self) -> list[str]:
        try:
            from xyxbot.tasks import list_task_names
            return list_task_names()
        except Exception:
            return []

    def _run_task(self, name: str):
        """★ 执行注册任务（走统一互斥锁 + 常驻 Playwright 线程）。

        ★ 根因修复（跨线程 bug）：
          `_run_guarded` 已经保证 `worker` 会跑在常驻 `pw-worker` 线程上，
          所以这里**不要**再自己建 App ——直接用 `self._ensure_app()` 即可。
          原实现在 worker 里 `App(...).start()`，虽然恰好也在 pw 线程
          （因为 `_run_guarded` 投递了它），但绕过了 `_ensure_app` 的统一入口，
          容易在后续改动中被误放到别的线程；这里统一走 `_ensure_app`。
        """
        self.log(f"准备执行任务：{name}", "brand")
        self.status.set_status(f"执行中：{name}", "warn")
        # 任务会把浏览器窗口拉到前台，这里保持主窗口可见
        self._keep_on_top(True)

        def worker():
            try:
                from xyxbot.logging_redirect import LogRedirector

                app = self._ensure_app()

                # 把后端 print 重定向到 UI 日志
                redirector = LogRedirector(
                    sink=lambda m: self.after(0, self.log, m, "info")
                ).install()
                try:
                    ok = app.run_task(name)
                finally:
                    redirector.restore()

                level = "ok" if ok else "err"
                msg = f"任务完成：{name}" if ok else f"任务结束（未成功）：{name}"
                self.after(0, self.log, msg, level)
                self.after(0, self.status.set_status, msg, level)
            except Exception as e:
                self.after(0, self.log, f"任务异常：{e}", "err")
                self.after(0, self.status.set_status, f"异常：{e}", "err")
            finally:
                self.after(0, self._keep_on_top, False)

        # ★ 统一互斥：上一个任务没跑完就再点 → 友好提示，不并发操作浏览器
        self._run_guarded(name, worker)

    # -------------------------------------------------- ★ 常驻 Playwright 线程
    #
    #  ★ 架构改良（2026-10-04）：线程模型 / 任务队列 / 互斥锁已抽到
    #    `ui/browser_session.py` 的 `BrowserSession`（无 tkinter 依赖、可单测）。
    #    下面这些方法保留为**薄封装**，让既有页面代码无需改动即可平滑迁移；
    #    新代码请直接使用 `self.session.*`。

    def _make_app(self):
        """App 工厂（只在常驻 Playwright 线程里被 BrowserSession 调用）。"""
        from xyxbot.app import App
        return App(headless=False,
                   browser_path=self._browser_path_override())

    def _session_log(self, msg: str, level: str = "info"):
        """BrowserSession 的日志回调 —— 从常驻线程安全地转到 tk 主线程。"""
        try:
            self.after(0, self.log, msg, level)
        except Exception:
            pass

    def _run_guarded(self, name: str, worker_fn, btn=None) -> bool:
        """★★ 统一的「后台跑浏览器任务」入口：互斥 + 状态 + 按钮管理。

        实现已迁移到 `BrowserSession.run_guarded`。这里只负责
        **按钮态的 tk 侧处理**（运行中禁用、完成恢复）。

        ★ 顺带修复：按钮禁用改用 `set_enabled()`。
          原实现用 `btn.config(state="disabled")`，但 BrandButton 是
          tk.Canvas，外层 state 不会拦截 `<Button-1>` 绑定 ——
          视觉变灰、实际仍可点击，忙碌期间会重复触发任务。
          （同时 theme.BrandButton.config 也已支持 state 转发，双保险。）
        """
        if btn is not None:
            try:
                if hasattr(btn, "set_enabled"):
                    btn.set_enabled(False)
                else:
                    btn.config(state="disabled")
            except Exception:
                pass

        def _restore():
            if btn is None:
                return
            try:
                if hasattr(btn, "set_enabled"):
                    btn.set_enabled(True)
                else:
                    btn.config(state="normal")
            except Exception:
                pass

        started = self.session.run_guarded(name, worker_fn, on_done=_restore)
        if not started:
            # 被拒绝（已有任务在跑）→ 把刚禁用的按钮立刻恢复
            _restore()
        return started

    # ------------------------------------------------------------ 对外

    def log(self, msg: str, level: str = "info"):
        self.log_view.log(msg, level)
