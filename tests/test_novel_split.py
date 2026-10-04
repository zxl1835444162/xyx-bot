# -*- coding: utf-8 -*-
"""回归测试：小说分章的**通用性**（无需 pytest，直接 python 运行）。

背景（2026-10-04 用户反馈）：
    用户从微信导出的 txt（`　　第1章 ...`，行首两个**全角空格** U+3000）
    **一章都分不出来**，直呼"太草台班子"。根因是旧正则的行首空白类
    只写了 `[ \\t]`，不含全角空格。

用户还明确要求：「我想做成**通用的**，而不是定制的」。
    所以这次不是补一个字符，而是重写成多模式解析器，本测试套件就是
    把"通用"这个词**钉死成可执行断言**，防止以后又退化成只认某一种写法。

覆盖：
  A. 各种章节标题写法都要认（全/半角空白、章/回/节/话/卷、中文数字、
     前导零、书名号、方括号、加粗、markdown 井号、BOM、全角数字…）
  B. 特殊章（序章/楔子/番外/作者的话…）
  C. **正文里提到的"第N章"绝不能被当成标题**（分章最容易翻车的地方）
  D. 章号归一：纯编号书保留原书号；混特殊章时退化成顺序编号
  E. 目录残留过滤、空输入、真实文件端到端

用法：
    .venv312\\Scripts\\python.exe tests\\test_novel_split.py
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, got, want):
    if got == want:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}: got={got!r} want={want!r}")


def check_true(name: str, cond, detail: str = ""):
    check(name, bool(cond), True)
    if not cond and detail:
        print(f"         {detail}")


from src.novel import (  # noqa: E402
    CHAPTER_RE, SPECIAL_RE, cn_to_int, split_novel,
)


def _one(line: str) -> int:
    """给一行标题加正文，返回分出的章数。"""
    return len(split_novel(line + "\n正文内容一些字。\n"))


# ============================================================ A. 格式通用性
print("\n=== A. 各种章节写法都要认（通用性）===")

FORMAT_CASES = [
    ("裸写", "第1章 标题"),
    ("半角空格缩进", " 第1章 标题"),
    # ★★ 用户报的那个：全角空格 U+3000（微信/Word 导出极常见）
    ("全角1空格", "\u3000第1章 标题"),
    ("全角2空格", "\u3000\u3000第1章 标题"),
    ("全角3空格", "\u3000\u3000\u3000第1章 标题"),
    ("全半角混合缩进", " \u3000 第1章 标题"),
    ("制表符", "\t第1章 标题"),
    ("不换行空格", "\u00a0第1章 标题"),
    ("章内空格", "第 1 章 标题"),
    ("中文数字", "第十二章 标题"),
    ("中文数字(百)", "第一百零八章 标题"),
    ("前导零", "第001章 标题"),
    ("全角数字", "第１章 标题"),
    ("冒号", "第1章：标题"),
    ("顿号", "第1章、标题"),
    ("markdown井号", "## 第1章 标题"),
    ("加粗", "**第1章 标题**"),
    ("只有章号", "第1章"),
    ("方括号", "【第1章】标题"),
    ("方括号+空格", "【第1章】 标题"),
    ("尾部全角空格", "第1章 标题\u3000"),
    ("书名号黏连", "第98章《龙之传说》杀青"),
    ("回目", "第一回 大闹天宫"),
    ("节", "第3节 尾声"),
    ("话", "第2话 觉醒"),
    ("篇", "第1篇 标题"),
    ("卷", "第1卷 标题"),
    ("BOM", "\ufeff第1章 标题"),
    ("英文Chapter", "Chapter 1 Title"),
    ("英文章+中文数字", "Chapter 十二 Title"),
]
for _name, _line in FORMAT_CASES:
    check(f"A 认得出：{_name} [{_line[:24]!r}]", _one(_line), 1)


# ============================================================ B. 特殊章
print("\n=== B. 无编号特殊章 ===")

SPECIAL_CASES = ["序章", "序章 雪夜", "楔子", "楔子 雪夜", "引子",
                 "前言", "序言", "尾声", "尾章", "后记", "终章",
                 "大结局", "大结局 圆满", "番外", "番外 一",
                 "番外篇 小剧场", "外传", "作者的话", "卷首语"]
for _line in SPECIAL_CASES:
    check(f"B 认得出特殊章：{_line!r}", _one(_line), 1)


# ============================================================ C. 不误伤正文
print("\n=== C. 正文里的「第N章」不能被当成标题（最关键）===")

NOISE = [
    "第一章正文。",
    "他翻开第二章看了看。",
    "这是第三章的伏笔。",
    "序章的故事开始了。",
    "第1章的内容很精彩。",
    "见第3章的设定。",
    "按照顺序来。",
    "前言不搭后语。",
    "他翻到第五回。",
    "番外篇讲了什么？",
    "第一章" + "的正文" * 30,        # 长正文，以「第一章」开头
]
for _line in NOISE:
    ch = split_novel(_line + "\n" + _line + "\n")
    check_true(f"C 不误伤：{_line[:26]!r}", len(ch) == 0,
               f"意外分出 {len(ch)} 章：{[c.title for c in ch]}")

# ★ 反向：正文里出现「第N章」但确实有真标题时，不能少分
_ok = split_novel(
    "第1章 觉醒\n他翻开第一章正文，后面还有第二章的内容。\n\n"
    "第2章 冲突\n正文。\n")
check("C 有真标题时正文噪声不影响，仍 2 章", len(_ok), 2)


# ============================================================ D. 章号归一
print("\n=== D. 章号归一 ===")

# 纯编号书：保留原书号
_pure = split_novel("第1章 a\n正文。\n第2章 b\n正文。\n第3章 c\n正文。\n")
check("D 纯编号书 → 原书号", [c.no for c in _pure], [1, 2, 3])

# 编号不连续（跳号）也要原样保留
_gap = split_novel("第1章 a\n正文。\n第5章 b\n正文。\n第9章 c\n正文。\n")
check("D 跳号也保留原书号", [c.no for c in _gap], [1, 5, 9])

# 中文数字章号 → 正确转成 int 并保留
_cn = split_novel("第一章 a\n正文。\n第二章 b\n正文。\n第十章 c\n正文。\n")
check("D 中文数字章号", [c.no for c in _cn], [1, 2, 10])

# 有特殊章混排 → 顺序编号（保证唯一、连续、不串位）
_mix = split_novel(
    "序章\n序章正文。\n\n第1章 觉醒\n正文。\n\n"
    "第2章 冲突\n正文。\n\n番外 小剧场\n番外正文。\n")
check("D 混特殊章 → 顺序编号", [c.no for c in _mix], [1, 2, 3, 4])
check("D 混特殊章 → 章数", len(_mix), 4)
check_true("D 混特殊章 → 首章是序章", _mix[0].title.startswith("序章"),
           _mix[0].title)
check_true("D 混特殊章 → 末章是番外", "番外" in _mix[-1].title, _mix[-1].title)

# 编号重复/倒序 → 退化成顺序编号
_dup = split_novel("第1章 a\n正文。\n第1章 b\n正文。\n第2章 c\n正文。\n")
check("D 编号重复 → 顺序编号", [c.no for c in _dup], [1, 2, 3])


# ============================================================ E. 边界
print("\n=== E. 边界情况 ===")

check("E 空文本 → 0 章", len(split_novel("")), 0)
check("E 纯正文（无标题）→ 0 章", len(split_novel("这是一段普通正文。\n" * 20)), 0)

# 目录残留：连着几十行「第N章」但后面没正文 → 全丢
_toc = "".join(f"第{i}章 标题{i}\n" for i in range(1, 31))
_toc += "\n第1章 真正的第一章\n这是正文。\n"
_res = split_novel(_toc)
check("E 目录残留被过滤，只剩真有正文的", len(_res), 1)

# 章正文不能被吃掉（标题行不算正文）
_b = split_novel("第1章 觉醒\n这里是第一章的正文内容。\n")
check_true("E 正文完整保留", _b[0].body == "这里是第一章的正文内容。",
           repr(_b[0].body))

# 书名号标题左书名号不能丢
_sq = split_novel("第98章《龙之传说》杀青\n正文。\n")
check_true("E 书名号标题完整", _sq[0].title == "第98章 《龙之传说》杀青",
           repr(_sq[0].title))

# 方括号标题：收括号要被剥掉，不能落进标题
_br = split_novel("【第1章】觉醒\n正文。\n")
check_true("E 方括号标题干净", _br[0].title == "第1章 觉醒",
           repr(_br[0].title))


# ============================================================ F. cn_to_int
print("\n=== F. 中文数字解析 ===")

for _s, _want in [("一", 1), ("十", 10), ("十二", 12), ("二十", 20),
                  ("二十三", 23), ("一百", 100), ("一百零八", 108),
                  ("1", 1), ("007", 7), ("０１", 1)]:
    check(f"F cn_to_int({_s!r})", cn_to_int(_s), _want)

check("F cn_to_int 非数字 → None", cn_to_int("abc"), None)
check("F cn_to_int 空 → None", cn_to_int(""), None)


# ============================================================ G. 正则契约
print("\n=== G. 正则静态契约（防退化）===")

# ★ 行首空白类必须含全角空格 U+3000 —— 这就是用户那个 bug 的根
check_true("G 行首空白含全角空格 U+3000",
           "\\u3000" in CHAPTER_RE.pattern,
           CHAPTER_RE.pattern[:80])
# ★ 必须支持「回/节/话/卷」等中文分节单位，不能只认"章"
for _u in ("回", "节", "话", "卷", "集", "篇"):
    check_true(f"G 支持分节单位「{_u}」", _u in CHAPTER_RE.pattern)
# ★ 特殊章模式要存在且能认序章/番外
check_true("G 特殊章模式认序章", bool(SPECIAL_RE.match("序章")))
check_true("G 特殊章模式认番外", bool(SPECIAL_RE.match("番外 一")))
# ★ 分隔符**不能**含 \\s（会跨行吞掉下一行正文）
check_true("G CHAPTER_RE 的标题部分不跨行",
           "\n" not in CHAPTER_RE.pattern.replace("\\n", ""),
           "pattern 里出现了真实换行")
# ★ 中文数字必须是字符类 [...]，不能写成捕获组 (...)
check_true("G 英文模式用字符类而非捕获组",
           "[" in CHAPTER_RE.pattern and "零一二三" not in
           CHAPTER_RE.pattern.replace("[零一二三", ""),
           "中文数字写成了 (...) 会变成字面顺序匹配")


# ============================================================ H. 真实文件
print("\n=== H. 端到端（本地真实 txt，有才跑）===")

_REAL = [
    pathlib.Path(r"D:\weixin\xwechat_files\wxid_mug5q6njawnh22_e08e"
                 r"\msg\file\2026-10\开局被绿(1).txt"),
    pathlib.Path.home() / "Desktop" / "开局被绿，我直播捉奸震惊全网.txt",
    ROOT / "artifacts_verify" / "sample_quanjiao.txt",
]
_ran = False
for _p in _REAL:
    try:
        if not _p.exists():
            continue
        _raw = _p.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        continue
    _ch = split_novel(_raw)
    _nos = [c.no for c in _ch]
    _miss = [n for n in range(1, len(_ch) + 1) if n not in _nos]
    print(f"  {_p.name}: {len(_ch)} 章")
    check_true(f"H 真实文件 {_p.name} 分得出章（>10）", len(_ch) > 10,
               f"只分出 {len(_ch)} 章")
    check_true(f"H 真实文件 {_p.name} 无缺号", not _miss, f"缺号 {_miss}")
    check_true(f"H 真实文件 {_p.name} 无空正文",
               all(c.body.strip() for c in _ch))
    _ran = True
    break
if not _ran:
    print("  [SKIP] 本机没有可用的真实 txt 样本")


# ============================================================ 汇总
print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for _f in FAIL:
        print(f"    - {_f}")
print("=" * 60)

import os  # noqa: E402

sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)
