"""字体解析与缓存（跨平台族名、缩放、诊断）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from tkinter import font as tkfont
import os
import sys
import time
import tkinter as tk

__all__ = ["F", "FM", "MONO_FONT_CANDIDATES", "UI_FONT_CANDIDATES", "_CJK_HINTS", "_FONT_CACHE", "_FONT_DIAG", "_FONT_SCALE_BY_PLATFORM", "_platform_key", "_resolve_family", "_scale_size", "_system_families", "font_report", "font_scale"]


# ---------------------------------------------------------------- 字体
#
# ★★ 跨平台（2026-10-04 转 macOS）
#   原来写死 "Microsoft YaHei UI"。这个字体在 macOS 上**不存在**，
#   Tk 会默默回退到默认字体 —— 中文可能变成极细字重，或者出现方块。
#   现在按平台列**优先级候选**，并用 `tkfont.families()` 挑第一个真的装了
#   的；一个都挑不到就把第一个候选交给 Tk 自己回退（不会再弄丢中文）。
#
#   两条纪律：
#     ① 系统字体表**只枚举一次**并缓存（见 `_system_families`）
#     ② 解析结果**无论成功失败都要缓存** —— 这两条是 2026-10-04 修的一个
#        真 bug：macOS 上"点击登录后鼠标一直转圈、主界面永远不出来"。
#        原因见 `_system_families` 的说明。
#
#     ③ 允许用环境变量 `XYX_UI_FONT` / `XYX_MONO_FONT` 强制覆盖。
#
# ★★ 为什么要列**中文名**候选（2026-10-04）
#    macOS 会按系统语言把字体族名**本地化**：系统是中文时，
#    `tkfont.families()` 返回的可能是「苹方-简」而不是「PingFang SC」。
#    而英文环境的 CI runner 返回的是英文名。这就解释了
#    "同一个包在 CI 上一秒过、在用户中文 Mac 上卡死"。
#    所以两种写法都列上。

UI_FONT_CANDIDATES = {
    "darwin": ["PingFang SC", "苹方-简", "苹方",
               "Hiragino Sans GB", "冬青黑体简体中文",
               "Heiti SC", "黑体-简", "STHeiti",
               "Songti SC", "宋体-简", "STSong",
               "Arial Unicode MS"],
    "win32": ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei",
              "SimSun", "Segoe UI"],
    "linux": ["Noto Sans CJK SC", "Source Han Sans SC",
              "WenQuanYi Micro Hei", "DejaVu Sans"],
}

MONO_FONT_CANDIDATES = {
    "darwin": ["Menlo", "Monaco", "SF Mono", "等宽", "Courier New"],
    "win32": ["Consolas", "Cascadia Mono", "Courier New"],
    "linux": ["DejaVu Sans Mono", "Noto Sans Mono", "Liberation Mono"],
}


#: 万一一堆候选都没命中，就按这些**关键字**在系统字体里捞一个中文字体
#: （本地化名字千奇百怪，列不完，兜一层关键字匹配）
_CJK_HINTS = ("pingfang", "hiragino", "heiti", "songti", "kaiti",
              "苹方", "黑体", "宋体", "楷体", "冬青", "华文", "雅黑")



# ---------------------------------------------------------------- ★ 字号缩放
#
# ★★★ 用户反馈（2026-10-04）：在 Mac 上「字体太小」。
#
#   原因不是字体选错了（PingFang SC 是对的），而是**同一套 point 字号
#   在不同平台上视觉大小差很多**：
#     * Tk 的字号是 **point**（1pt = 1/72 inch），真机上是按 DPI 换算的
#     * Windows 上 Tk 默认 tk scaling ≈ 1.33（96 DPI），9pt 看着刚刚好
#     * macOS 上同一份代码渲染出来的字明显**更小更细**，尤其 8~10pt 这种小号，
#       在 Retina 屏上会显得发虚、偏小
#   界面里 8/9/10pt 的字号占了绝大多数（49 处 9pt、14 处 10pt、10 处 8pt），
#   所以整体观感就是"字体太小"。
#
#   解决方式：**集中一处做平台缩放**，不去改 78 处调用点。
#     * macOS × 1.3 —— 这是反复对比后比较接近 Windows 观感的系数
#     * 其余平台 × 1.0 —— 完全不动，避免把 Windows/Linux 的效果改坏
#   并且允许用环境变量 `XYX_FONT_SCALE` 覆盖（用户/CI 可微调）。
#
#   ★ 向上取整到 0.5 的整数倍，避免出现 11.7pt 这种怪值（Tk 接受浮点，
#     但取整后跨平台的字体缓存更稳定）。
_FONT_SCALE_BY_PLATFORM = {
    "darwin": 1.3,
    "win32": 1.0,
    "linux": 1.0,
}



def font_scale() -> float:
    """当前平台的字号缩放系数（可用 `XYX_FONT_SCALE` 覆盖）。"""
    override = os.environ.get("XYX_FONT_SCALE", "").strip()
    if override:
        try:
            v = float(override)
            if 0.5 <= v <= 3.0:
                return v
        except ValueError:
            pass
    return _FONT_SCALE_BY_PLATFORM.get(_platform_key(), 1.0)



def _scale_size(size: int) -> int:
    """把设计字号换算成当前平台的实际字号（至少保证 1pt）。"""
    s = font_scale()
    if s == 1.0:
        return int(size)
    # 放大后向上取整到 0.5 的整数倍，避免奇怪的零头
    scaled = size * s
    return max(1, int(scaled + 0.5))


_FONT_CACHE: dict = {}

#: 系统字体表：**小写名 → 原始名**。None = 还没枚举过；{} = 枚举过但失败
#:   ★ 必须留原始名：Tk 认的是原始大小写，把 'PingFang SC' 写成
#:     'pingfang sc' 会找不到字体（等于白挑）。
_SYS_FAMILIES: dict | None = None

#: 诊断用：枚举耗时、命中情况
_FONT_DIAG: dict = {}



def _platform_key() -> str:
    """darwin / win32 / linux（只关心这三类）。"""
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("win"):
        return "win32"
    return "linux"



def _system_families() -> tuple:
    """系统字体族名（小写 → 原始名）。返回 `(表, 是否已定稿)`。

    ★★ 这里是 2026-10-04 那个"点登录后鼠标一直转圈"的**根因**
    =====================================================================

    用户反馈（macOS 15）：登录界面正常，**点确定之后登录窗消失、鼠标变成
    转圈的等待光标、主界面永远不出来、也没有任何报错**。
    转圈 = 主线程被**卡住**（不是崩溃，所以没有异常、没有弹窗）。

    原因：`tkfont.families()` 在 macOS 上要走 CoreText 枚举**全部系统字体**，
    很慢。而原来的 `_resolve_family` 只有"**候选字体命中**"才写缓存：

        for name in candidates:
            if name.lower() in have:
                _FONT_CACHE[key] = name     # ← 只有命中才缓存
                return name
        return candidates[0]                # ← 没命中就直接返回，不缓存！

    于是，只要候选一个都没命中，**每一次** `F()` / `FM()` 都会重新枚举一遍
    系统字体。而构建主界面会调用 F()/FM() **几百次**（每个标签、按钮、
    输入框、画布文字都要），几百次 × 每次几十到几百毫秒 = **主线程卡死
    几分钟**。

    为什么登录界面没事？它控件少，只有几十次调用，几秒内就画完了。
    这正好解释了"登录界面可以、主界面不行"。

    那为什么 CI 上一秒就过？因为 macOS 会按**系统语言**本地化字体族名：
    CI runner 是英文环境，返回 "PingFang SC"，第一个候选就命中 → 只枚举
    一次；用户的中文 Mac 返回的可能是「苹方-简」，ASCII 候选全部落空 →
    每次都重新枚举。所以这个 bug 只在中文 Mac 上炸。

    修法：
      ① 枚举结果**缓存**，成功与否都算数；
      ② 但要区分"还没有 Tk root"和"真的有异常"——
         没有 root 时 `families()` 是**立刻抛错**的（根本不会走 CoreText），
         重试几乎不花钱，所以**不缓存**，等 root 建好后正经解析一次；
         有 root 还失败才是真异常，缓存下来别反复试。
    """
    global _SYS_FAMILIES
    if _SYS_FAMILIES is not None:
        return _SYS_FAMILIES, True        # 已经定稿

    has_root = getattr(tk, "_default_root", None) is not None
    t0 = time.time()
    table: dict = {}
    try:
        for f in tkfont.families():
            s = str(f)
            # 同名不同大小写只留第一个，值一定是**原始名**
            table.setdefault(s.lower(), s)
    except Exception:
        if not has_root:
            # 还没有 Tk root：这种失败是**瞬时**的（不会枚举系统字体），
            # 所以不缓存 —— 等 root 建好后再正经解析一次。
            _FONT_DIAG["families_ms"] = round((time.time() - t0) * 1000)
            _FONT_DIAG["deferred_no_root"] = True
            return {}, False
        # 有 root 仍失败 → 真异常，缓存空表，别每次重试（那才是贵的）
        table = {}

    _SYS_FAMILIES = table
    _FONT_DIAG["families_ms"] = round((time.time() - t0) * 1000)
    _FONT_DIAG["families_count"] = len(table)
    return _SYS_FAMILIES, True



def _resolve_family(candidates: list, env_var: str) -> str:
    """从候选里挑一个当前系统真的有的字体名。**结果一定进缓存**。"""
    forced = (os.getenv(env_var) or "").strip()
    if forced:
        return forced
    key = tuple(candidates)
    if key in _FONT_CACHE:            # ★ 命中就用 —— 包括"没匹配上"的结果
        return _FONT_CACHE[key]

    have, final = _system_families()
    pick = None
    if have:
        for name in candidates:
            real = have.get(name.lower())
            if real:
                pick = real            # ★ 用系统里的原始名，别用候选的写法
                break
        if pick is None:
            # 候选都落空（多半是本地化名字）→ 按关键字在系统字体里捞一个
            for hint in _CJK_HINTS:
                for low, real in have.items():
                    if hint in low:
                        pick = real
                        break
                if pick:
                    break
    result = pick or (candidates[0] if candidates else "TkDefaultFont")
    if final:                             # ★ 定稿了才缓存，避免毒化缓存
        _FONT_CACHE[key] = result
        _FONT_DIAG.setdefault("matched", {})[key] = pick is not None
    return result



def font_report() -> dict:
    """诊断信息：挑到了什么字体、系统有多少字体、枚举花了多久、有没有命中。

    给 `--selftest` 用 —— 中文 Mac 上的字体问题一眼就能看出来。

    ★ `tkfont.families()` 需要存在一个 Tk root 才能拿到真表；没有就临时
      建一个再销毁（否则报告出来的全是 "?" / None，等于没报）。
    """
    # ★ 建 root 与解析要分成两步：建不出 root（Linux 无 DISPLAY / headless）
    #   时，解析仍应尝试并如实报告"未定稿"，而不是整块跳过、什么都不报。
    tmp = None
    try:
        if getattr(tk, "_default_root", None) is None:
            tmp = tk.Tk()
            tmp.withdraw()
    except Exception:
        tmp = None
    try:
        F()
        FM()
    except Exception:
        pass
    finally:
        if tmp is not None:
            try:
                tmp.destroy()
            except Exception:
                pass

    plat = _platform_key()
    k_ui = tuple(UI_FONT_CANDIDATES[plat])
    k_mono = tuple(MONO_FONT_CANDIDATES[plat])
    matched = _FONT_DIAG.get("matched", {})
    return {
        "ui": _FONT_CACHE.get(k_ui, "?"),
        "ui_matched": matched.get(k_ui),
        "mono": _FONT_CACHE.get(k_mono, "?"),
        "mono_matched": matched.get(k_mono),
        "platform": plat,
        "system_family_count": _FONT_DIAG.get("families_count"),
        "families_ms": _FONT_DIAG.get("families_ms"),
        "deferred_no_root": _FONT_DIAG.get("deferred_no_root", False),
        "picked": _FONT_DIAG.get("picked", {}),
    }



def F(size: int = 10, bold: bool = False) -> tuple:
    """统一界面字体（按平台挑得到的最合适的中文字体）。

    ★ 字号会按平台做缩放（macOS 放大，见 `font_scale`）——调用方
    照旧写设计字号即可，不用关心平台差异。
    """
    fam = _resolve_family(UI_FONT_CANDIDATES[_platform_key()], "XYX_UI_FONT")
    return (fam, _scale_size(size), "bold" if bold else "normal")



def FM(size: int = 10) -> tuple:
    """等宽字体，用于日志。

    ★ 同样做平台字号缩放；另外等宽字体在 macOS 上偏小，缩放后更易读。
    """
    fam = _resolve_family(MONO_FONT_CANDIDATES[_platform_key()],
                          "XYX_MONO_FONT")
    return (fam, _scale_size(size), "normal")
