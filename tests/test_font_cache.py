# -*- coding: utf-8 -*-
"""回归测试：字体解析**必须只枚举一次系统字体**。

无需 pytest，直接 `python tests/test_font_cache.py`。

★★ 这个文件锁的是一个真实的"卡死"bug（2026-10-04 用户实测）
================================================================

用户（macOS 15，中文系统）反馈：

    登录界面正常 → 点确定 → **登录窗消失、鼠标转圈、主界面永远不出来、
    没有任何报错**

"转圈"= 主线程被卡住，不是崩溃，所以没有异常、也没有弹窗。

根因：`tkfont.families()` 在 macOS 上要走 CoreText 枚举**全部系统字体**，
很慢。而原来的 `_resolve_family` **只有候选字体命中时才写缓存**：

    for name in candidates:
        if name.lower() in have:
            _FONT_CACHE[key] = name        # ← 只有命中才缓存
            return name
    return candidates[0]                    # ← 没命中就直接返回，**不缓存**

只要候选一个都没命中，**每一次** F()/FM() 都会重新枚举一遍系统字体。
而构建主界面会调用 F()/FM() **几百次** → 几百次 × 几十~几百毫秒
= 主线程卡死几分钟。登录界面控件少（几十次），所以几秒内还能画出来。

为什么只在中文 Mac 上炸：macOS 按**系统语言本地化**字体族名 —— 英文环境
返回 "PingFang SC"（第一个候选就命中，只枚举一次），中文环境可能返回
「苹方-简」，ASCII 候选全部落空 → 每次都重新枚举。

所以本文件用**假的字体表**在本地复现这个场景，并断言：
  ① 无论命中与否，系统字体表只枚举 **1 次**
  ② 枚举抛异常也只试 1 次（并回退到首个候选，不崩）
  ③ 结果进缓存（第二次调用不再枚举）
  ④ 本地化名字能靠关键字捞到中文字体，而不是瞎回退
  ⑤ XYX_UI_FONT / XYX_MONO_FONT 覆盖生效，且不触发枚举
"""
from __future__ import annotations

import os
import pathlib
import sys
import tkinter.font as tkfont

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import _support as S  # noqa: E402  文件布局的唯一接口（见 tests/_support.py）

try:
    from xyxbot.console import enable_utf8

    enable_utf8()
except Exception:
    pass

from xyxbot.ui import theme  # noqa: E402

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


_real_families = tkfont.families
# 拆包后字体实现住在 theme/fonts.py（theme/_SYS_FAMILIES/_platform_key 都在那里）。
# 读 theme.xxx 有兼容转发，但**打补丁必须打在归属模块上**才有用。
from xyxbot.ui.theme import fonts as theme_fonts  # noqa: E402


def _fake_fonts(names, calls: list, cost_ms: float = 0.0, boom: bool = False):
    """造一个假的 `tkfont.families()`：记录调用次数、可选地模拟耗时/抛错。"""
    def _f(*a, **kw):
        calls.append(1)
        if cost_ms:
            import time
            time.sleep(cost_ms / 1000.0)
        if boom:
            raise RuntimeError("模拟：环境异常，拿不到字体表")
        return tuple(names)
    return _f


def _reset():
    theme._FONT_CACHE.clear()
    theme_fonts._SYS_FAMILIES = None
    theme._FONT_DIAG.clear()
    os.environ.pop("XYX_UI_FONT", None)
    os.environ.pop("XYX_MONO_FONT", None)


N = 300          # 模拟"构建主界面时的调用次数"（实际是几百次）

# ★ 把平台钉死成 darwin：要测的就是"中文 macOS"这个场景
#   （否则在 Windows 上跑会用到 win32 的候选表，测不到目标路径）
_real_platform_key = theme_fonts._platform_key
theme_fonts._platform_key = lambda: "darwin"
_UI = theme.UI_FONT_CANDIDATES["darwin"]

try:
    # ================================================ ① 候选全落空（中文 Mac）
    print("=== ① 候选全部落空（模拟中文 macOS：字体名被本地化）===")
    calls: list = []
    # 只有本地化名字，一个 ASCII 候选都不在 → 老代码会每次都重新枚举
    tkfont.families = _fake_fonts(["苹方-简", "黑体-简", "Mystery Font"],
                                  calls, cost_ms=2.0)
    _reset()
    for _ in range(N):
        theme.F(10)
    check("枚举系统字体只发生 1 次（这是不卡死的关键）", len(calls), 1)
    check_true("解析结果进了缓存", tuple(_UI) in theme._FONT_CACHE)
    picked = theme.F(10)[0]
    # ★ 必须带回**原始大小写**，否则 Tk 找不到这个字体（等于白挑）
    check("直接命中了中文候选名（本地化名字已在候选表里）", picked, "苹方-简")

    # 再调 300 次也不能多枚举
    for _ in range(N):
        theme.F(11)
        theme.FM(9)
    check("再调用 600 次仍然只有那 1 次枚举", len(calls), 1)

    # ================================================ ①b 关键字兜底
    print("\n=== ①b 候选全落空、且名字不在候选表里 → 关键字兜底 ===")
    calls_b: list = []
    tkfont.families = _fake_fonts(["苹方-简体", "Mystery Font"], calls_b,
                                  cost_ms=2.0)
    _reset()
    got_b = [theme.F(10)[0] for _ in range(N)]
    check("关键字兜底也只枚举 1 次", len(calls_b), 1)
    check("按关键字捞到中文字体，且保留原始大小写", got_b[0], "苹方-简体")

    # ================================================ ② 英文环境（CI 上的情况）
    print("\n=== ② 候选命中（模拟英文 macOS / CI runner）===")
    calls2: list = []
    tkfont.families = _fake_fonts(["PingFang SC", "Menlo", "Helvetica"],
                                  calls2, cost_ms=2.0)
    _reset()
    picks = [theme.F(10)[0] for _ in range(N)]
    check("命中时也只枚举 1 次", len(calls2), 1)
    check("挑中的就是第一个可用候选", picks[0], "PingFang SC")
    check_true("每次都返回同一个字体（已缓存）", len(set(picks)) == 1)

    # ================================================ ③ 枚举抛异常
    print("\n=== ③ 字体表拿不到（抛异常）时的两种情形 ===")
    _real_default_root = getattr(theme.tk, "_default_root", None)
    try:
        # ③a 还没有 Tk root → 这种失败是**瞬时**的，不缓存、可以重试
        theme.tk._default_root = None
        calls3: list = []
        tkfont.families = _fake_fonts([], calls3, boom=True)
        _reset()
        got = [theme.F(10)[0] for _ in range(50)]
        check("无 root 时不去毒化缓存（失败是瞬时的，允许重试）",
              len(calls3), 50)
        check("无 root 时回退到首个候选（不崩）", got[0], _UI[0])

        # ③b 有 Tk root 还失败 → 真异常，只试 1 次（避免反复走 CoreText）
        theme.tk._default_root = object()
        calls3b: list = []
        tkfont.families = _fake_fonts([], calls3b, boom=True)
        _reset()
        got2 = [theme.F(10)[0] for _ in range(N)]
        check("有 root 时失败只试 1 次（这才是贵的路径）", len(calls3b), 1)
        check("回退到首个候选", got2[0], _UI[0])
        check_true("异常结果也缓存了（返回稳定）", len(set(got2)) == 1)
    finally:
        theme.tk._default_root = _real_default_root

    # ================================================ ④ 等宽字体
    print("\n=== ④ 等宽字体同样只枚举一次 ===")
    calls4: list = []
    tkfont.families = _fake_fonts(["苹方-简", "Menlo"], calls4, cost_ms=1.0)
    _reset()
    for _ in range(N):
        theme.F(10)
        theme.FM(9)
    check("UI + 等宽加起来也只枚举 1 次（共用同一张系统字体表）",
          len(calls4), 1)
    check_true("UI 与等宽是两个独立的缓存条目（互不覆盖）",
               len(theme._FONT_CACHE) == 2, str(list(theme._FONT_CACHE)))
    check("等宽挑中了 Menlo", theme.FM(9)[0], "Menlo")

    # ================================================ ⑤ 环境变量覆盖
    print("\n=== ⑤ XYX_UI_FONT / XYX_MONO_FONT 覆盖 ===")
    calls5: list = []
    tkfont.families = _fake_fonts(["苹方-简"], calls5)
    _reset()
    os.environ["XYX_UI_FONT"] = "MyCustomFont"
    os.environ["XYX_MONO_FONT"] = "MyCustomMono"
    check("覆盖 UI 字体", theme.F(10)[0], "MyCustomFont")
    check("覆盖等宽字体", theme.FM(10)[0], "MyCustomMono")
    check("覆盖时不枚举系统字体（省掉最贵的那一步）", len(calls5), 0)
    os.environ.pop("XYX_UI_FONT", None)
    os.environ.pop("XYX_MONO_FONT", None)

    # ================================================ ⑥ 诊断信息
    print("\n=== ⑥ font_report 给 --selftest 用 ===")
    calls6: list = []
    tkfont.families = _fake_fonts(["苹方-简", "Menlo"], calls6, cost_ms=1.0)
    _reset()
    rep = theme.font_report()
    for k in ("ui", "mono", "ui_matched", "mono_matched", "platform",
              "system_family_count", "families_ms", "picked"):
        check_true(f"font_report 含 {k}", k in rep, str(rep))
    if rep.get("deferred_no_root"):
        # ★ 没有图形会话（Linux headless）时，字体表是"未定稿"的：
        #   这时不该要求它报出字体数，而要确认它**如实说了自己是未定稿**，
        #   并且没有把空表钉进缓存（否则以后有 root 也不会再解析）。
        check_true("无 root 时如实报告「未定稿」", rep["deferred_no_root"] is True)
        check_true("无 root 时不毒化缓存（_SYS_FAMILIES 仍为 None）",
                   theme_fonts._SYS_FAMILIES is None)
    else:
        check("报告里的系统字体数正确", rep["system_family_count"], 2)
        check_true("报告里说清了有没有命中候选（便于远程排查）",
                   rep["ui_matched"] is True, str(rep))
    check_true("报告里给出了实际用的字体名",
               isinstance(rep["ui"], str) and rep["ui"], str(rep["ui"]))

    # ================================================ ⑦ 静态检查
    print("\n=== ⑦ 静态检查：别再退回「只有命中才缓存」 ===")
    src = S.module_source("ui/theme.py")
    check_true("解析结果无条件写缓存", "_FONT_CACHE[key] = result" in src)
    check_true("系统字体表有「已定稿」守卫（不会每次重来）",
               "if _SYS_FAMILIES is not None:" in src
               and "_SYS_FAMILIES = table" in src)
    check_true("区分「还没有 Tk root」与「真异常」（前者不毒化缓存）",
               "has_root" in src and "deferred_no_root" in src)
    check_true("字体表存的是「小写 → 原始名」，保住大小写",
               "setdefault(s.lower(), s)" in src)
    check_true("候选里带上了中文名（本地化环境也能命中）",
               "苹方-简" in src and "黑体-简" in src)
    check_true("有本地化关键字兜底", "_CJK_HINTS" in src)
finally:
    tkfont.families = _real_families
    theme_fonts._platform_key = _real_platform_key

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
