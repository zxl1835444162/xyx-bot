"""命令表与入口 main()。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations


# ★★ 必须在任何 print 之前执行：Windows 上输出被重定向到文件/管道时，
#   Python 会用系统代码页(GBK)，而日志里的 ⚠/✓ 不在 GBK 里 →
#   `python main.py batch > log.txt` 会直接崩掉（实测）。
from xyxbot.console import enable_utf8

import sys

from xyxbot.cli.ai import cmd_ai, cmd_auto
from xyxbot.cli.book import cmd_books, cmd_open, cmd_prepare
from xyxbot.cli.review_ import cmd_batch, cmd_review
from xyxbot.cli.session import cmd_check, cmd_diag, cmd_login, cmd_logout, cmd_selftest, cmd_session
from xyxbot.cli.site import cmd_browsers, cmd_platforms, cmd_recon, cmd_run, cmd_studio, cmd_tasks

__all__ = ["COMMANDS", "main"]


COMMANDS = {
    "login": cmd_login,
    "session": cmd_session,
    "prepare": cmd_prepare,
    "check": cmd_check,
    "diag": cmd_diag,
    "selftest": cmd_selftest,
    "recon": cmd_recon,
    "logout": cmd_logout,
    "books": cmd_books,
    "open": cmd_open,
    "ai": cmd_ai,
    "review": cmd_review,
    "auto": cmd_auto,
    "batch": cmd_batch,
    "tasks": cmd_tasks,
    "platforms": cmd_platforms,
    "run": cmd_run,
    "studio": cmd_studio,
    "browsers": cmd_browsers,
}



def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("可用命令:", ", ".join(COMMANDS))
        sys.exit(1)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()


enable_utf8()
