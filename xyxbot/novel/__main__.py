"""`python -m xyxbot.novel` 的入口。

原来在 `novel.py` 末尾是 `if __name__ == "__main__": main()`；
拆包时这个守卫不属于任何职责分组，所以单独放这里。

用法：
    python -m xyxbot.novel <小说.txt>      # 按章拆开并打印摘要
"""
from xyxbot.novel.cli import main

if __name__ == "__main__":
    main()
