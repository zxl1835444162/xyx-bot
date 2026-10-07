"""命令行入口（薄壳）。

真正的实现在 `xyxbot/cli.py` —— 这里只做两件事：把仓库根放进 sys.path，
然后把控制权交出去。这样做的原因：

* 逻辑只留一份（以前 560 行的 CLI 全部堆在根目录的 main.py 里）；
* `python main.py <命令>` 与 `python -m xyxbot <命令>` 完全等价，两种习惯都照顾；
* 打包（PyInstaller）时入口仍是这个稳定的薄壳，包结构内部怎么变都不影响它。

用法：
    python main.py                 # 列出所有命令
    python main.py selftest        # 环境自检
    python -m xyxbot selftest      # 同上，包入口写法
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xyxbot.cli import main  # noqa: E402  （必须在 sys.path 就绪之后导入）


if __name__ == "__main__":
    main()
