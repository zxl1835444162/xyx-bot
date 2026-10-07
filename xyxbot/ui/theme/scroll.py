"""滚轮量纲（按平台换算 delta）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

from xyxbot.ui.theme.fonts import _platform_key

__all__ = ["_WHEEL_STEP", "bind_wheel", "bind_wheel_all", "unbind_wheel_all", "wheel_units"]


# ---------------------------------------------------------------- ★ 滚轮
#
# ★★★ 用户反馈（2026-10-04）：在 Mac 上「只能拖动滑动条，滚轮滚不动」。
#
#   根因：所有滚动点的代码都写成
#       self._canvas.yview_scroll(int(-event.delta / 120), "units")
#   这个 **`/ 120` 是 Windows 的量纲**：
#     * Windows：`event.delta` 是 ±120 的整数倍（一格 = 120）→ 120/120 = 1 ✓
#     * macOS ：`event.delta` 是**很小的整数**（滚轮 ±1，触控板常常只有 ±1）
#                → int(1/120) = **0** ⇒ 滚动量恒为 0，**怎么滚都不动** ✗
#     * Linux ：Tk 根本不发 `<MouseWheel>`，要用 `<Button-4>`/`<Button-5>` ✗
#
#   修法：集中到这一个函数，按平台给**步长**，并顺手支持 Linux 的按钮事件。
#   调用方只需把原来的 `yview_scroll(int(-event.delta / 120), "units")`
#   换成 `wheel_units(event)` 即可。

#: 每个滚轮 notch 滚多少个 "units"（unit = 一行）。macOS 的 delta 小而密，
#: 所以给大一点的步长，手感才跟 Windows 接近。
_WHEEL_STEP = {
    "darwin": 1,      # macOS：delta 已经是 ±1 量级，1 格滚 1 行手感正常
    "win32": 3,       # Windows：一格 delta=120，滚 3 行（原逻辑约等于 1，略加大）
    "linux": 3,       # Linux：Button-4/5 一次一行，滚 3 行
}



def wheel_units(event) -> int:
    """把滚轮事件换算成「滚几行」（正数向下滚，负数向上滚）。

    跨平台统一入口：
      * Windows：按 `event.delta / 120` 取格数
      * macOS  ：`event.delta` 本身就是格数（常为 ±1），**不能再除 120**
      * Linux  ：用 `<Button-4>`/`<Button-5>` 事件，`event.num` 区分方向

    返回值可直接喂给 `canvas.yview_scroll(n, "units")`。
    """
    # ---- Linux：Button-4 上滚 / Button-5 下滚 ----
    num = getattr(event, "num", None)
    if num == 4:
        return -_WHEEL_STEP.get("linux", 3)
    if num == 5:
        return _WHEEL_STEP.get("linux", 3)

    delta = getattr(event, "delta", 0) or 0
    plat = _platform_key()

    if plat == "darwin":
        # macOS：delta 通常是很小的整数（滚轮 ±1，触控板常常只有 ±1），
        # 也有个别 Tk 版本给 120 量级 —— 两种都兼容：
        #   * |delta| 很小 → 按**符号**滚一步（不依赖数值大小，最稳）
        #   * |delta| 是 120 的倍数 → 按 Windows 方式算格数
        # ★ 方向与 Windows 一致：delta 为正表示**向上**滚 → 返回负数。
        if delta == 0:
            return 0
        step = _WHEEL_STEP.get("darwin", 1)
        if abs(delta) >= 120:
            notches = max(1, abs(delta) // 120)
            return -notches * step if delta > 0 else notches * step
        return -step if delta > 0 else step

    # Windows / 其它：标准 120 步进
    if delta == 0:
        return 0
    notches = int(delta / 120)
    if notches == 0:
        # 有些高精度设备（部分外设/驱动）用更小的 delta，兜一层符号
        notches = 1 if delta > 0 else -1
    return -notches * _WHEEL_STEP.get("win32", 3)



def bind_wheel(widget, handler) -> None:
    """把一个「按行滚动」的处理函数绑到控件上，跨平台生效。

    * Windows / macOS → `<MouseWheel>`
    * Linux（X11）     → `<Button-4>` / `<Button-5>`

    `handler` 收到的是原始 event，内部请用 :func:`wheel_units` 换算步长。
    """
    widget.bind("<MouseWheel>", handler, add="+")
    widget.bind("<Button-4>", handler, add="+")
    widget.bind("<Button-5>", handler, add="+")



def bind_wheel_all(widget, handler) -> None:
    """:func:`bind_wheel` 的 `bind_all` 版（全局滚轮）。"""
    widget.bind_all("<MouseWheel>", handler)
    widget.bind_all("<Button-4>", handler)
    widget.bind_all("<Button-5>", handler)



def unbind_wheel_all(widget) -> None:
    """:func:`bind_wheel_all` 的对应解绑。"""
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        try:
            widget.unbind_all(seq)
        except Exception:
            pass
