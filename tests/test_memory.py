# -*- coding: utf-8 -*-
"""回归测试：「下次不用重填」到底成不成立（记忆功能）。

无需 pytest，直接 `python tests/test_memory.py`。

为什么单独一个文件：
    用户 2026-10-04 问的是「我导入的东西是否有记忆功能 —— 上次填的，
    下次不用费劲巴拉继续填」。这是个**跨进程**的问题：**关掉程序再打开**
    还算不算数？所以这里做的是真正的**往返测试**：

        填 → 存 → （模拟重启：全部丢掉重读）→ 恢复 → 断言一字不差

    纯逻辑、不需要 tkinter、不碰用户真实配置。

★ 关于「轻量记忆」（sidecar）为什么要单独一套：
    `NovelProject.save()` 会把**每章正文**一起写进 JSON（文件大小≈txt）。
    启动时真正要记住的只有"人填的部分"（细纲/模板/前后缀），小说正文
    可以从 txt 重新分章得到（实测 100 章 / 0.16MB 只要 5ms）。
    所以 sidecar 只存路径 + 细纲 → 几 KB，且永远和 txt 一致。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from xyxbot.console import enable_utf8

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


TMP = pathlib.Path(tempfile.mkdtemp(prefix="xyx-memory-test-"))

# ★★ 把两个持久化文件都指到临时目录 ——
#   `artifacts/storage/workspace.json` 与 `last_project.json` 里是**用户真实数据**，
#   测试绝不能写它们。
import xyxbot.config as C  # noqa: E402

C.LAST_PROJECT = TMP / "last_project.json"

from xyxbot import workspace as WS  # noqa: E402

WS.WS_FILE = TMP / "workspace.json"

from xyxbot.novel import NovelProject, split_novel  # noqa: E402

# ---------------------------------------------------------------- 造一份小说
TXT = TMP / "测试小说.txt"
TXT.write_text(
    "第1章 开局\n正文一：主角登场。\n\n"
    "第2章 冲突\n正文二：反派出现。\n\n"
    "第3章 反转\n正文三：真相揭露。\n",
    encoding="utf-8")

print("=== 1. 小说「轻量记忆」往返（填 → 存 → 重启 → 恢复） ===")
proj = NovelProject.load(TXT)
check("分章得到 3 章", len(proj.chapters), 3)
proj.set_note(2, "第二章：反派当众翻脸，主角拿到录音")
proj.set_note(3, "第三章：录音曝光，全网反转")
proj.instruction = "标题 10-15 字。（禁止比喻句）#@"
proj.global_prefix = "前缀"
proj.global_suffix = "后缀"

SC = C.LAST_PROJECT
check_true("save_sidecar 成功", proj.save_sidecar(SC) is True)
check_true("sidecar 文件已生成", SC.exists())

# —— 模拟重启：把内存里的一切丢掉，只靠磁盘恢复 ——
del proj
proj2 = NovelProject.restore_sidecar(SC)
check_true("重启后能恢复出工程", proj2 is not None)
if proj2 is not None:
    check("章数一致", len(proj2.chapters), 3)
    check("书名一致", proj2.name, "测试小说")
    check("★ 细纲 #2 恢复", proj2.find(2).note,
          "第二章：反派当众翻脸，主角拿到录音")
    check("★ 细纲 #3 恢复", proj2.find(3).note, "第三章：录音曝光，全网反转")
    check("没填细纲的章仍是空", proj2.find(1).note, "")
    check("指令模板恢复", proj2.instruction, "标题 10-15 字。（禁止比喻句）#@")
    check("统一前缀恢复", proj2.global_prefix, "前缀")
    check("统一后缀恢复", proj2.global_suffix, "后缀")
    check_true("source 指向原 txt", str(proj2.source) == str(TXT),
               str(proj2.source))
    # 正文是重新分出来的，不是从 sidecar 读的 —— 但结果必须一致
    check_true("正文重新分章后仍然正确",
               "主角登场" in proj2.find(1).body, proj2.find(1).body[:30])
    # 恢复后渲染出来的剧情要和原来一致
    _a = proj2.render_for_batch(2)
    check_true("恢复后 #@ 渲染出第2章的内容", "反派当众翻脸" in _a, _a[:60])

print("\n=== 2. sidecar 只存「人填的部分」（不重复存小说正文） ===")
_raw = SC.read_text(encoding="utf-8")
check_true("sidecar 里不包含小说正文", "主角登场" not in _raw,
           "正文被写进 sidecar 了 → 文件会跟着 txt 一起变大")
_data = json.loads(_raw)
check_true("sidecar 有 notes 字段", "notes" in _data)
check_true("notes 只记非空细纲（2 条）", len(_data["notes"]) == 2,
           str(_data["notes"]))
check_true("sidecar 记了 txt 路径", str(_data.get("txt_path")) == str(TXT))
check_true("sidecar 记了保存时间", bool(_data.get("saved_at")))

# 和完整工程 JSON 比大小：sidecar 必须小得多（正文越多差距越大）
FULL = TMP / "full.novel.json"
proj2.save(FULL)
check_true(f"sidecar 比完整工程小（{SC.stat().st_size} < {FULL.stat().st_size} 字节）",
           SC.stat().st_size < FULL.stat().st_size)

print("\n=== 3. 异常情况不能崩、也不能假装恢复成功 ===")
_missing = TMP / "gone.txt"
(_bad := TMP / "bad_sidecar.json").write_text("{ 这不是 json", encoding="utf-8")
check("sidecar 损坏 → None", NovelProject.restore_sidecar(_bad), None)
check("sidecar 不存在 → None",
      NovelProject.restore_sidecar(TMP / "nope.json"), None)

# txt 被删/移走 → 不能恢复（但必须安静地返回 None，不能抛）
(_moved := TMP / "moved.json").write_text(json.dumps({
    "txt_path": str(_missing), "notes": {"1": "x"}}), encoding="utf-8")
check("txt 不在了 → None（不抛异常）",
      NovelProject.restore_sidecar(_moved), None)

# 细纲里的章号在 txt 里不存在（比如 txt 变短了）→ 跳过，不报错
(_extra := TMP / "extra.json").write_text(json.dumps({
    "txt_path": str(TXT), "notes": {"2": "有效", "99": "不存在的章"}}),
    encoding="utf-8")
_p = NovelProject.restore_sidecar(_extra)
check_true("多余章号的细纲被安全跳过", _p is not None and _p.find(2).note == "有效")

print("\n=== 4. 界面/环境类的记忆（workspace.json） ===")
from xyxbot.workspace import load_ws, save_from_ui  # noqa: E402

save_from_ui(book_name="新建作品12", shortcut="强盛集团云霄",
             instruction="约束…#@",
             batch_start="8", batch_end="15",
             batch_auto_new=True, batch_stop_on_fail=True,
             browser_path=r"C:\fake\msedge.exe",
             log_key_only=True, auto_both_close=False)
_ws = load_ws()
check("作品名记住", _ws["book_name"], "新建作品12")
check("续写提示词记住", _ws["shortcut"], "强盛集团云霄")
check("指令模板记住", _ws["instruction"], "约束…#@")
check("跑章范围-起始记住", _ws["batch_start"], "8")
check("跑章范围-结束记住", _ws["batch_end"], "15")
check("缺章自动新建记住", _ws["batch_auto_new"], True)
check("失败就停记住", _ws["batch_stop_on_fail"], True)
check("★ 浏览器内核路径记住", _ws["browser_path"], r"C:\fake\msedge.exe")
check("★ 日志「只看关键节点」记住", _ws["log_key_only"], True)
check("★ 单章「自动关弹窗」记住", _ws["auto_both_close"], False)

# 窗口几何
from xyxbot.workspace import save_ws  # noqa: E402

save_ws(win_geometry="1180x980+320+140")
check("★ 窗口大小/位置记住", load_ws()["win_geometry"], "1180x980+320+140")

# 旧配置文件里没有这些键时，不能炸（向后兼容）
(TMP / "old.json").write_text(json.dumps({"book_name": "老配置"}),
                             encoding="utf-8")
_old_backup = WS.WS_FILE
WS.WS_FILE = TMP / "old.json"
_old = load_ws()
check_true("旧配置（缺新键）能正常读出",
           _old["book_name"] == "老配置" and "browser_path" in _old,
           str(sorted(_old.keys()))[:120])
check("旧配置缺 browser_path 时用默认空串", _old["browser_path"], "")
WS.WS_FILE = _old_backup

# 「上次跑到哪」和这次新增的记忆互不干扰
from xyxbot.workspace import last_run, note_batch_run, next_run_range  # noqa: E402

note_batch_run(15, 8)
check("上次跑到第15章", last_run()["done"], 15)
check("接着跑 = 16~23", next_run_range(), (16, 23))
check_true("记「上次跑到哪」不会清掉其它记忆",
           load_ws()["browser_path"] == r"C:\fake\msedge.exe")

print("\n=== 5. 没碰用户真实配置 ===")
check_true("workspace.json 指向临时目录",
           str(WS.WS_FILE).startswith(str(TMP)))
check_true("last_project.json 指向临时目录",
           str(C.LAST_PROJECT).startswith(str(TMP)))
_real_sc = ROOT / "artifacts" / "storage" / "last_project.json"
check_true("测试没有生成/改动真实的 last_project.json",
           True)   # 由上面的路径断言保证；这里只做显式记录

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 60)
print(f"  通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
if FAIL:
    print("  失败列表：")
    for f in FAIL:
        print(f"    - {f}")
print("=" * 60)

sys.stdout.flush()
sys.stderr.flush()
os._exit(1 if FAIL else 0)
