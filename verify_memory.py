# -*- coding: utf-8 -*-
"""跨进程验证「记忆功能」：真的关掉程序、再开一次，看还在不在。

用法（两个独立进程，共享同一组临时配置路径）：
    set XYX_MEM_TMP=<临时目录>
    python verify_memory.py write    # 第 1 次：分章 + 填细纲 + 存
    python verify_memory.py read     # 第 2 次（相当于重开程序）：只能靠磁盘恢复
"""
from __future__ import annotations

import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    from src.console import enable_utf8

    enable_utf8()
except Exception:
    pass

TMP = pathlib.Path(os.environ["XYX_MEM_TMP"])
import src.config as C  # noqa: E402

C.LAST_PROJECT = TMP / "last_project.json"
from src import workspace as WS  # noqa: E402

WS.WS_FILE = TMP / "workspace.json"

from src.novel import NovelProject  # noqa: E402

TXT = pathlib.Path(r"C:\Users\Administrator\Desktop"
                   r"\开局被绿，我直播捉奸震惊全网.txt")
NOTES = {
    8: "第八章：主角拿到关键证据，直播间人数破百万",
    9: "第九章：反派反扑，主角被全网质疑",
}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "read"
    print(f"[{mode}] 配置目录 = {TMP}")

    if mode == "write":
        t0 = time.perf_counter()
        proj = NovelProject.load(TXT)
        el = time.perf_counter() - t0
        print(f"[write] 分章 {len(proj.chapters)} 章，耗时 {el*1000:.0f} ms")
        for no, txt in NOTES.items():
            proj.set_note(no, txt)
        proj.instruction = "标题10-15字。（禁止比喻句）#@"
        proj.save_sidecar(C.LAST_PROJECT)
        WS.save_ws(book_name="新建作品12", batch_start="8", batch_end="15",
                   browser_path=r"C:\fake\msedge.exe", log_key_only=True)
        print(f"[write] 已存轻量记忆：{C.LAST_PROJECT.stat().st_size} 字节")
        print(f"[write] 已存界面配置：{WS.WS_FILE.stat().st_size} 字节")
        return 0

    # ---- read：全新进程，内存里什么都没有 ----
    print("[read] 进程是全新的，没有任何内存状态 —— 只靠磁盘")
    t0 = time.perf_counter()
    proj = NovelProject.restore_sidecar(C.LAST_PROJECT)
    el = time.perf_counter() - t0

    ok = True
    if proj is None:
        print("[read] ✗ 没恢复出来")
        return 1
    print(f"[read] ✓ 恢复出《{proj.name}》{len(proj.chapters)} 章，"
          f"耗时 {el*1000:.0f} ms")
    for no, txt in NOTES.items():
        got = proj.find(no).note
        hit = (got == txt)
        ok &= hit
        print(f"[read]   #{no} 细纲 {'✓ 一致' if hit else '✗ 不一致'}：{got[:34]}")
    print(f"[read]   指令模板：{proj.instruction!r}")
    r = proj.render_for_batch(8)
    print(f"[read]   #@ 渲染（第8章）：{r[:56]!r}")

    ws = WS.load_ws()
    for key, want in (("book_name", "新建作品12"), ("batch_start", "8"),
                      ("batch_end", "15"),
                      ("browser_path", r"C:\fake\msedge.exe"),
                      ("log_key_only", True)):
        got = ws.get(key)
        hit = (got == want)
        ok &= hit
        print(f"[read]   {key:14s} {'✓' if hit else '✗'} {got!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
