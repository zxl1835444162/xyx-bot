"""章节文件读写、字数统计、重复检测（移植自 novel_publisher/chapter_files.py）。

与参考项目的差异：去掉 tkinter 依赖（messagebox 换成 print），
使其在无 GUI 环境也能用。
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import List, Tuple

CHAPTER_PATTERN = re.compile(
    r"(^\s*#*\s*第\s*[一二三四五六七八九十百千万零\dIVXLCDM]+\s*章[：:\s]+.*$)",
    re.MULTILINE,
)


def split_chapters(content: str) -> List[dict]:
    """将全文按章节标记拆分为 [{title, content}, ...]。"""
    parts = CHAPTER_PATTERN.split(content)
    if len(parts) <= 1:
        return []

    chapters = []
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        if i + 1 < len(parts):
            chapters.append({"title": title, "content": parts[i + 1].strip()})
    return chapters


def normalize_chapter_title(title: str) -> str:
    """规范化章节标题中的冒号和空格。"""
    t = str(title)
    if "：" not in t:
        idx = t.find("章") + 1
        if 0 < idx < len(t) and t[idx] in (":", " "):
            t = t[:idx] + "：" + t[idx + 1:]
    return t.replace(" ", "")


def create_chapter_files(novel_file_path: str, output_dir: str | None = None) -> bool:
    """把一个 .txt 全文拆成 Chapter_001.md 等章节文件。"""
    if not novel_file_path.endswith(".txt"):
        print(f"错误: 文件 {novel_file_path} 不是文本文件")
        return False

    out = output_dir or os.path.splitext(novel_file_path)[0]
    os.makedirs(out, exist_ok=True)

    try:
        with open(novel_file_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"错误: 文件 {novel_file_path} 未找到")
        return False

    chapters = split_chapters(content)
    if not chapters:
        print("未找到任何章节。")
        return False

    for i, ch in enumerate(chapters):
        title = normalize_chapter_title(ch["title"])
        path = os.path.join(out, f"Chapter_{i + 1:03d}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f"# {title}\n\n")
            fh.write(ch["content"])

    print(f"成功分解 {len(chapters)} 个章节到目录: {out}")
    return True


def get_chapter_files_in_range(
    novels_folder: str, start_chapter: int, end_chapter: int
) -> List[Tuple[int, str]]:
    """取指定章节号区间内的 .md 文件，按序号排序返回 [(序号, 路径)]。"""
    if not os.path.isdir(novels_folder):
        return []

    files = [
        os.path.join(novels_folder, f)
        for f in os.listdir(novels_folder)
        if f.endswith(".md")
    ]

    reverse = start_chapter > end_chapter
    if reverse:
        print("起始章节号大于结束章节号，按反向顺序取（适合存草稿箱）")

    lo, hi = min(start_chapter, end_chapter), max(start_chapter, end_chapter)
    picked = []
    for fp in files:
        name = os.path.splitext(os.path.basename(fp))[0]
        m = re.search(r"_(\d+)", name)
        if m and lo <= int(m.group(1)) <= hi:
            picked.append((int(m.group(1)), fp))

    picked.sort(key=lambda x: x[0])
    if reverse:
        picked.reverse()

    if not picked:
        print(f"在 {novels_folder} 中没找到第 {start_chapter}~{end_chapter} 章")
    return picked


def get_chapter_details(filepath: str, neat_index: bool = True):
    """从 .md 提取 (章节序号, 标题, 正文, 作者说)。"""
    name = os.path.splitext(os.path.basename(filepath))[0]
    m = re.search(r"_(\d+)", name)
    if not m:
        raise ValueError(f"文件名 {name} 格式错误，未找到章节序号")
    num = m.group(1)

    with open(filepath, "r", encoding="utf-8") as f:
        first_line = f.readline().strip()
        if "：" not in first_line:
            idx = first_line.find("章") + 1
            title = first_line[idx + 1:] if idx > 0 else first_line
        elif first_line.startswith("#"):
            title = first_line.lstrip("# ").split("：", 1)[-1]
        else:
            title = first_line.split("：", 1)[-1]
        content = f.read()

    if "@作者说：" in content:
        content, writer_said = content.split("@作者说：")
    else:
        writer_said = ""

    print(f"读取章节: 第{num}章 - {title}")
    if not neat_index:
        num = str(int(num))
    return num, title, content, writer_said


def count_chinese_characters(text: str) -> int:
    """统计中文字符数（含中文标点），忽略 Markdown 符号。"""
    if not text:
        return 0

    count = 0
    text = text.replace("\n", "").replace(" ", "")
    for char in text:
        try:
            if "CJK" in unicodedata.name(char):
                count += 1
            elif char.isascii():
                count += 1
            elif char in "，。！？；：“”…（）【】《》、-%.":
                count += 1
        except (ValueError, TypeError):
            continue
    return count


def check_repeat_content(content: str) -> str:
    """检查开头是否有重复段落，返回去重后的内容。"""
    min_length = 30
    while len(content) >= min_length * 2:
        head = content[:min_length]
        if head in content[min_length:] and content[: min_length + 1] not in content[min_length + 1:]:
            print(f"发现重复内容:\n {head}")
            return content[min_length:]
        min_length += 1
    print("未发现简单重复内容，请手动查验")
    return content
