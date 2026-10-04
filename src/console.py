"""控制台编码加固：让 print 里的中文/符号在**任何**输出目标上都不炸。

★★ 为什么需要这个模块（2026-10-04 实测踩到）
=============================================

本项目的日志里有大量符号（`⚠ ✓ ✗ ・ ☆`）。在 Windows 上：

  * 输出到**真实控制台** → Python 走 `_WindowsConsoleIO`，Unicode 没问题
  * 输出被**重定向到文件/管道**（`python main.py batch > log.txt`、
    计划任务、CI、父进程用管道抓输出）→ Python 退化成用**系统 ANSI 代码页**
    （简体中文机器上是 cp936/GBK），而 `⚠`(U+26A0) 不在 GBK 里：

        $ python -c "print('warn \u26a0')" > out.txt
        UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0'

  实测：`tests/test_fixes.py` 重定向后直接**退出码 1** 崩在
  `src/novel.py` 的一行 `print(f"[novel] ⚠ …")` 上 —— 测试没跑完就死了。

也就是说：**你能不能拿到完整日志，取决于你把输出重定向到哪**。
这属于"日志一落盘就崩溃"的隐藏地雷，因此统一在这里修掉。

做法：把 stdout/stderr 重新配置成 UTF-8 + `errors="replace"`。
`errors="replace"` 保证**任何**字符都打得出去（打不出就退化成 `?`），
永远不再因为一个表情符号中断整个流程。
"""

from __future__ import annotations

import sys

__all__ = ["enable_utf8"]


def enable_utf8(quiet: bool = True) -> bool:
    """把 stdout/stderr 切成 UTF-8，避免 GBK 编码错误。

    Returns:
        bool: 是否至少成功改了一个流（改不了也不抛，静默降级）
    """
    ok = False
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            # Python 3.7+；被替换成非文本流（如 GUI 里的队列转发器）时会抛
            stream.reconfigure(encoding="utf-8", errors="replace")
            ok = True
        except Exception:
            # 兜底：退回到「只替换编码错误」的老办法
            try:
                stream.errors = "replace"      # type: ignore[attr-defined]
                ok = True
            except Exception:
                pass
    if not quiet and not ok:
        print("[console] 无法重配置输出编码（继续，不影响运行）")
    return ok
