"""命令行自测入口（python -m xyxbot.novel）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.novel.project import NovelProject

__all__ = ["main"]


# ---------------------------------------------------------------- CLI 便捷

def main():
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m src.novel <小说.txt> [指令模板]")
        print('例:   python -m src.novel 开局被绿.txt "根据 #1 的细纲续写正文"')
        sys.exit(1)
    proj = NovelProject.load(sys.argv[1])
    print(f"\n{proj.summary()}\n")
    for c in proj.chapters[:10]:
        print(f"  {c.code:6s} {c.title:32s} {len(c.body)} 字")
    if len(proj.chapters) > 10:
        print(f"  ... 还有 {len(proj.chapters) - 10} 章")

    # 演示短代号模板
    proj.set_note(1, "陆晨撞见女友与经纪人王浩私会，怒火中烧，系统激活。")
    tpl = sys.argv[2] if len(sys.argv) > 2 else \
        "根据 #1 的细纲，续写下一段正文，保持爽文节奏。"
    print(f"\n--- 指令模板 ---\n{tpl}")
    print(f"\n--- 替换后 ---\n{proj.render_template(tpl)}")


if __name__ == "__main__":
    main()
