"""stdout/stderr 重定向（移植自 novel_publisher/logging_redirect.py）。

参考项目重定向到 tkinter Text 控件；这里改为通用 sink 回调 + 同时写文件，
因此在命令行、GUI、无头环境都能用。
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import config as C


class LogRedirector:
    """把 stdout/stderr 同时送往：回调 sink + 日志文件 + 原始终端。

    用法::

        r = LogRedirector(sink=print)
        r.install()
        ...
        r.restore()
    """

    def __init__(self, sink: Optional[Callable[[str], None]] = None,
                 log_file: Optional[Path] = None):
        self.sink = sink
        self._lock = threading.Lock()
        # ★ 每线程行缓冲：把 print() 的「文本 + 换行」两次 write 攒成整行后再落盘，
        #   避免多线程下写出粘连的乱码行。
        self._tl = threading.local()
        self._orig_out = sys.stdout
        self._orig_err = sys.stderr

        self.log_file = log_file
        self._fh = None
        if self.log_file:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
            # ★ 长期持有句柄（原来每行都 open/close 一次）
            try:
                self._fh = open(self.log_file, "a", encoding="utf-8")
            except Exception:
                self._fh = None

    # ------------------------------------------------ 控制
    def install(self) -> "LogRedirector":
        sys.stdout = self
        sys.stderr = self
        return self

    def restore(self) -> None:
        sys.stdout = self._orig_out
        sys.stderr = self._orig_err
        self.close()      # ★ 还原时把日志文件句柄关掉

    # ------------------------------------------------ 写入
    def _emit(self, text: str) -> None:
        """把输出分发到 sink / 日志文件 / 原始终端。

        ★ 根因修复（三处）：

        ① **按「行」写文件，消除多线程交错乱码**（实测确认的真 bug）。
           `print(x)` 会触发**两次** `write()`：先文本、后换行。原实现每次
           write 各自 open/lock/write/close，于是多线程下会写成
           `t5-48t3-49t6-48` 这种粘连行（实测 8 线程 400 行只剩 203 行有效）。
           现在用**每线程行缓冲**：把片段攒到换行再一次性、在锁内写出，
           保证「一行」是原子落盘的。未以换行结尾的片段会暂存到
           `flush()` / `close()` 时补写。

        ② **sink 不再在锁内调用**。原实现在 `with self._lock:` 里直接调
           `self.sink(...)`，而 GUI 的 sink 是 `root.after(...)` —— 等于持锁
           做跨线程投递；若 sink 反过来再写日志就是**自死锁**（Lock 不可重入）。
           现在 sink 与终端都在锁外调用。

        ③ **文件句柄不再每次 open/close**。原实现每写一行就开关一次文件，
           批量日志（一条龙逐章输出）会明显变慢。现在长期持有句柄。
        """
        if not text:
            return
        # 单次 write 可能含多行（例如直接 write("a\nb\n")）
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return

        def _to_file(chunk: str):
            with self._lock:
                if self._fh is None:
                    return
                try:
                    self._fh.write(chunk)
                    self._fh.flush()
                except Exception:
                    pass

        # ① 按行缓冲落盘（原子行）
        buf = getattr(self._tl, "buf", "")
        buf += text
        if "\n" in buf:
            *complete, buf = buf.split("\n")
            if complete:
                _to_file("".join(x + "\n" for x in complete))
        self._tl.buf = buf

        # ② sink 在**锁外**调用
        #    ★ 只送「有内容」的行：`print(x)` 的换行那次 write 会得到空串，
        #      否则 sink 会收到一串空串，把 GUI 日志区刷满空行。
        sink_text = text.rstrip("\n")
        if self.sink and sink_text:
            try:
                self.sink(sink_text)
            except Exception:
                pass

        # ③ 原始终端（同样锁外，避免终端阻塞拖住其它线程）
        try:
            self._orig_out.write(text)
            self._orig_out.flush()
        except Exception:
            pass

    def _drain_tls(self) -> None:
        """把当前线程缓冲里残留的「未换行」片段补写到文件。"""
        buf = getattr(self._tl, "buf", "")
        if not buf:
            return
        self._tl.buf = ""
        with self._lock:
            if self._fh is None:
                return
            try:
                self._fh.write(buf + "\n")
                self._fh.flush()
            except Exception:
                pass

    def write(self, text: str) -> None:
        self._emit(text)

    def close(self) -> None:
        """补写残留缓冲并关闭日志文件句柄（可多次调用）。"""
        self._drain_tls()
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None

    def flush(self) -> None:
        self._drain_tls()
        for orig in (self._orig_out, self._orig_err):
            try:
                orig.flush()
            except Exception:
                pass


def default_log_file() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return C.LOGS / f"run-{stamp}.log"
