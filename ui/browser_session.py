"""浏览器会话与线程模型（从 ui/main_window.py 抽出的基础设施层）。

为什么单独成模块
================

`MainWindow` 原本自己养着一条常驻 Playwright 线程 + 一个任务队列 + 一把互斥锁
（约 90 行散落在 3300 行的窗口类里，夹在页面构建代码中间）。这带来了三个问题：

1. **规则不显式**：注释里写「Playwright 对象必须始终在同一线程操作」，
   但没有任何机制强制它 —— 于是真的出现了几处跨线程调用
   （主线程 `App.stop()`、后台线程读 tk 控件）。
2. **职责混杂**：窗口类既管界面、又管线程生命周期、又管任务互斥。
3. **不可单测**：线程/队列逻辑和 tkinter 窗口耦合，没法脱离 GUI 验证。

本模块把这块收口成一个**不带任何 tkinter 依赖**的 `BrowserSession`：

    session = BrowserSession(log=print)
    session.submit(fn)                 # 把 fn 投到常驻线程串行执行
    session.run_guarded("任务名", fn)   # 互斥 + 生命周期，返回是否已启动
    session.stop()                     # 停浏览器 + 结束线程

设计约束
--------

* **单线程**：所有浏览器（Playwright）操作只能通过 `submit` / `run_guarded`
  进入，永远在同一个后台线程里执行。这是本模块存在的唯一理由。
* **不碰 tk**：`log` 是注入的回调；调用方负责让它线程安全
  （GUI 里传 `lambda m, lv: root.after(0, ...)`）。
* **永不抛**：后台线程内的异常一律吞掉并记日志，避免常驻线程因异常退出
  （那会导致后续所有任务报 `cannot switch to a different thread`）。
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, Optional


class BrowserSession:
    """常驻 Playwright 线程 + 串行任务队列 + 任务互斥。

    典型用法（GUI）::

        self.session = BrowserSession(log=self._session_log)
        self.session.submit(lambda: do_something(self.session.ensure_app()))

        # 互斥任务（按钮点击）
        self.session.run_guarded("批量跑章", worker, on_done=btn_restore)
    """

    def __init__(self, log: Optional[Callable[[str, str], None]] = None,
                 app_factory: Optional[Callable[[], object]] = None):
        """
        Args:
            log: `(消息, 级别)` 回调；级别为 info/ok/warn/err。
                 必须线程安全（GUI 里请用 `root.after` 包装）。
            app_factory: 惰性创建 App 的工厂（**只在常驻线程里被调用**）。
                         默认创建 `src.app.App`。
        """
        self._log = log or (lambda msg, level="info": None)
        self._app_factory = app_factory or self._default_app_factory

        self._queue: "queue.Queue" = queue.Queue()
        self._app = None
        self._thread = threading.Thread(target=self._loop, name="pw-worker",
                                        daemon=True)
        self._thread.start()

        # 任务互斥
        self._task_lock = threading.Lock()
        self._task_running = False
        self._task_name = ""

    # ---------------------------------------------------------------- 内部

    def _default_app_factory(self):
        from src.app import App
        return App(headless=False)

    def _loop(self):
        """常驻线程：串行执行投进来的任务。"""
        while True:
            fn = self._queue.get()
            if fn is None:              # 停止信号
                break
            try:
                fn()
            except Exception as e:
                # 兜底：任务内部本该自己 catch，但绝不能因此让常驻线程退出
                try:
                    self._log(f"[session] 任务异常（已忽略）：{e}", "err")
                except Exception:
                    pass

    # ---------------------------------------------------------------- 线程信息

    @property
    def app(self):
        """当前 App（可能是 None；**只应在常驻线程里读**）。"""
        return self._app

    def is_worker_thread(self) -> bool:
        """当前线程是不是常驻 Playwright 线程。"""
        return threading.current_thread() is self._thread

    # ---------------------------------------------------------------- 提交

    def submit(self, fn: Callable[[], None]) -> None:
        """把 `fn` 投递到常驻线程排队执行（非阻塞）。"""
        self._queue.put(fn)

    def ensure_app(self):
        """确保 App 已启动并返回它。

        ★ 必须在常驻线程里调用（即从 `submit` / `run_guarded` 投进去的
        函数内部）。在别的线程调用会破坏 Playwright 的线程绑定。
        """
        if self._app is None:
            self._app = self._app_factory()
            self._app.start(with_log_file=True)
        return self._app

    def stop(self, on_done: Optional[Callable[[Exception], None]] = None) -> None:
        """★ 线程安全地关掉浏览器。

        把 `app.stop()` 投递到常驻线程执行 —— 这样即使从 tk 主线程调用，
        也不会跨线程操作 Playwright 对象。

        Args:
            on_done: 出错时的回调（收到异常对象）。GUI 里可用来回主线程写日志。
        """
        app, self._app = self._app, None

        def _closer():
            if app is None:
                return
            try:
                app.stop()
            except Exception as e:
                if on_done:
                    on_done(e)
                else:
                    self._log(f"[session] 关闭浏览器出错（忽略）：{e}", "warn")

        self._queue.put(_closer)

    # ---------------------------------------------------------------- 互斥

    @property
    def busy(self) -> bool:
        """是否有互斥任务正在跑/排队。"""
        with self._task_lock:
            return self._task_running

    @property
    def busy_name(self) -> str:
        with self._task_lock:
            return self._task_name

    def run_guarded(self, name: str, worker: Callable[[], None],
                    on_done: Optional[Callable[[], None]] = None) -> bool:
        """★ 统一入口：互斥 + 投递到常驻线程 + 完成后释放。

        解决「上一个任务没跑完就再点 → 报 Playwright 底层线程错」：
        同一个时刻只允许一个互斥任务；重复点击会**友好拒绝**而不是并发。

        Args:
            name:     任务名（用于提示）
            worker:   要在常驻线程里执行的函数（内部自己拿 app / page）
            on_done:  任务结束后调用（无论成败），用于恢复按钮态。

        Returns:
            True 表示已接受并开始排队；False 表示已有任务在跑（被拒绝）。
        """
        with self._task_lock:
            if self._task_running:
                self._log(
                    f"⚠ 任务「{self._task_name}」还在运行，请等它完成后再点",
                    "warn")
                return False
            self._task_running = True
            self._task_name = name

        def _runner():
            try:
                worker()
            finally:
                with self._task_lock:
                    self._task_running = False
                    self._task_name = ""
                if on_done is not None:
                    try:
                        on_done()
                    except Exception:
                        pass

        self._queue.put(_runner)
        return True

    # ---------------------------------------------------------------- 收尾

    def shutdown(self, wait: float = 0.0) -> None:
        """停掉常驻线程（可选等待）。

        ★ 只应在程序退出时调用；`stop()` 才是关浏览器。
        """
        self._queue.put(None)
        if wait:
            self._thread.join(timeout=wait)
