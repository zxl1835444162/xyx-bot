"""重绘守卫（macOS 上 <Configure> 自激的根治手段）。

本文件由原巨型模块拆分而来（Phase C2/C1），拆分时按 AST 依赖做了拓扑排序，
每个模块只 import 排在自己前面的模块，不存在循环引用。
"""

from __future__ import annotations

import sys
import time

__all__ = ["_REDRAW_BUDGET", "_REDRAW_PER_SEC", "_redraw_allowed", "bind_configure"]



# ---------------------------------------------------------------- ★ Configure 守卫
#
# ★★★ 这里修的是 macOS 上「点登录后鼠标转圈、主界面永远不出来」的**直接原因**
# =====================================================================
#
# 实测（GitHub 的 macOS runner，真机，tests/repro_login.py 带计数器版本）：
#
#     ★ 卡死了：主线程已 10.3 秒没有任何进展
#        最后一次进展：MainWindow.__init__ 结束      ← 主窗**已经建好了**
#        ★ 计数：Configure=97968  render=98029  create_text=126038
#
# 10 秒内 `<Configure>` 触发 **9.8 万次**、重绘 **9.8 万次**、
# `create_text` **12.6 万次** —— 每秒约一万次。主线程全耗在这个循环里，
# **永远回不到事件循环**，于是 `after` 定时器不触发、窗口不绘制、
# 鼠标一直转圈。同一份代码在 Windows 上全程只有 32 次 Configure。
#
# 原因：在 `<Configure>` 回调里 delete + 重建画布内容（或在里面
# `place_configure` 子控件），会**再触发一次 `<Configure>`**。
# macOS 的 Tk 每次重绘都会再发一个 Configure，于是：
#
#     Configure → 重绘 → Configure → 重绘 → …（无限）
#
# 破法：**尺寸没变就不重绘**。再配一个全局速率上限兜底 ——
# 万一将来又造出别的循环，界面最多降到约 6 帧/秒，绝不会被拖死。

_REDRAW_BUDGET = {"t0": 0.0, "n": 0}

_REDRAW_PER_SEC = 400          # 全局每秒重绘上限（正常界面远低于这个数）



def _redraw_allowed() -> bool:
    """全局重绘闸门：每秒超过 `_REDRAW_PER_SEC` 次就返回 False。"""
    now = time.time()
    if now - _REDRAW_BUDGET["t0"] >= 1.0:
        _REDRAW_BUDGET["t0"] = now
        _REDRAW_BUDGET["n"] = 0
    _REDRAW_BUDGET["n"] += 1
    return _REDRAW_BUDGET["n"] <= _REDRAW_PER_SEC



def bind_configure(widget, redraw) -> None:
    """把 `<Configure>` 绑成**带守卫的重绘**。新代码请一律用它。

    ★ 为什么不能直接 `widget.bind("<Configure>", redraw)`：见上面那段实测数据。

    守卫做两件事：
      ① **尺寸和上次一样 → 直接返回**（这一条破掉实测到的死循环）；
      ② 全局每秒重绘上限（`_redraw_allowed`）。超了就合并成一次延时重绘，
         保证最终画对，但不会把主线程占死。

    重绘回调里要读尺寸就读 `widget._cfg_w` / `widget._cfg_h`
    （由本函数写入），别再去接 event —— 这样回调可以是零参数的。

    Args:
        widget: 要绑定的控件
        redraw: 零参数可调用对象
    """
    def _on_cfg(event):
        size = (event.width, event.height)
        if getattr(widget, "_cfg_last", None) == size:
            return                              # ★ 尺寸没变 → 不重绘（破循环）
        widget._cfg_last = size
        widget._cfg_w, widget._cfg_h = size
        if not _redraw_allowed():
            # 超预算：合并成一次延时重绘（保证最终画对，但不占死主线程）
            if not getattr(widget, "_cfg_pending", False):
                widget._cfg_pending = True

                def _late():
                    widget._cfg_pending = False
                    try:
                        redraw()
                    except Exception:
                        pass

                try:
                    widget.after(150, _late)
                except Exception:
                    pass
            return
        try:
            redraw()
        except Exception:
            # 重绘出错不能把事件循环带走（否则又变成"卡住没反应"）
            import traceback as _tb

            print("[ui] Configure 重绘失败：\n" + _tb.format_exc(),
                  file=sys.stderr)

    widget.bind("<Configure>", _on_cfg)
