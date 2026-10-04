"""条件驱动等待：把「傻等 N 秒再检查」换成「一满足就立刻返回」。

为什么要这个模块
================

原实现里大量出现这种写法：

    time.sleep(1.5)              # 先等 UI 反应一下
    if ready(): ...              # 再检查一次
    time.sleep(1.2)              # 完成后"再等一下让字数渲染"

问题：
  ① **必等**。即使条件 50ms 就满足了，也要先吃满那 1.5s。
  ② **不确定性**。写在 sleep 之后的检查失败了，没有重试机会，直接判失败。
  ③ **累积**。单章流程里这类固定 sleep 合计约 52 秒；100 章就是 1.4 小时纯空转。

本模块提供 `wait_until(...)`：**高频轮询一个谓词**，条件一成立立即返回，
超时才放弃。查询本身很便宜（一次 DOM 属性读取），所以轮询可以很密，
不需要像原来那样用 2 秒的粗间隔来"省查询"。

★ 对站点风控的影响：轮询做的是**纯读取**（`is_visible` / `count`），
  频率由 `interval` 控制且默认带轻微退避，不会像"连点"那样触发验证码。
  真正要避免的是快速**点击**，不是快速**读取**。

用法
----

    from .waiting import wait_until, wait_gone

    # 等某个条件成立
    if wait_until(lambda: _visible(page, ["text=菜单"])[0] is not None,
                  timeout=6.0):
        ...

    # 等某个东西消失
    wait_gone(lambda: page.locator(".n-modal").count())

    # 需要知道等了几秒
    res = wait_until(cond, timeout=10)
    print(res.ok, res.elapsed, res.value)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

__all__ = ["WaitResult", "wait_until", "wait_gone", "poll_interval",
           "wait_visible", "wait_hidden"]

# 默认轮询间隔。40ms 对一次 DOM 属性读取来说很轻，
# 又能把「条件成立 → 返回」的延迟压到几乎感知不到。
DEFAULT_INTERVAL = 0.04
# 退避上限：长时间等待时不要一直 40ms 猛查
MAX_INTERVAL = 0.25


def poll_interval(elapsed: float, base: float = DEFAULT_INTERVAL,
                  cap: float = MAX_INTERVAL) -> float:
    """随时间轻微退避的轮询间隔。

    前 1 秒用 `base`（抢"其实早就好了"的快速返回），
    之后线性放大到 `cap`，避免长等待时无意义地高频查询。
    """
    if elapsed <= 1.0:
        return base
    grow = base + (elapsed - 1.0) * 0.02
    return min(grow, cap)


@dataclass
class WaitResult:
    """`wait_until` 的结果。"""

    ok: bool = False
    elapsed: float = 0.0
    polls: int = 0
    value: Any = None
    detail: str = ""
    # ★★ 是否因为「外部请求中止」而提前结束（不是超时，也不是条件满足）。
    #    用途：批量跑章时用户点「停止」，正在等待的步骤要能在一个轮询周期内
    #    退出，而不是把 600 秒的审稿超时等完。
    aborted: bool = False

    def __bool__(self) -> bool:      # 可以当 bool 用
        return self.ok


def _predicate_error_note(cond, err: BaseException, desc: str) -> None:
    """谓词抛异常时的提示。

    ★★ 为什么必须喊出来（2026-10-04 血泪教训）：
       `wait_until` 出于健壮性会把谓词异常当成「未满足」吞掉 —— 因为
       DOM 还没渲染出来时，谓词里 `locator().inner_text()` 之类确实会抛。
       但这个"贴心设计"埋了一个**完全静默**的坑：如果传进来的谓词
       **签名就是错的**（例如把 `def gen_finished(page)` 直接当谓词传，
       而不是 `lambda: gen_finished(page)`），那么它**每一轮都抛
       TypeError**，于是等待**必然超时**，而且日志里一个字都没有。

       实测代价：上一版把 `wait_generation` 写成
           `wait_until(gen_finished, timeout=300, ...)`
       → 每章都要**干等满 300 秒**才判"生成失败"，而生成其实 9 秒就好了。
       用户看到的"等待时间特别长"就是这个。

       判据：**DOM 未就绪只会让谓词返回 False，不会抛 TypeError。**
       所以 TypeError 基本可以断定是"写错了"，必须立刻显式报错。
    """
    print(f"[waiting] ✗ 谓词调用失败（{desc or cond!r}）：{err}")
    if isinstance(err, TypeError):
        print("[waiting]   ↳ 这像是**签名写错**（不是元素没出来）："
              "需要参数的函数要包一层，写成 `lambda: f(page)`。"
              "被吞掉的异常会让这个等待**必然超时**。")


def wait_until(cond: Callable[[], Any],
               timeout: float = 10.0,
               interval: float = DEFAULT_INTERVAL,
               on_poll: Optional[Callable[[int], None]] = None,
               desc: str = "",
               backoff: bool = True,
               should_abort: Optional[Callable[[], bool]] = None) -> WaitResult:
    """轮询 `cond` 直到返回真值、超时、**或被请求中止**。

    Args:
        cond:     无参谓词。返回真值即成功（返回值放进 `result.value`）。
                   ★ 必须是**无参可调用对象**。需要参数的函数请包一层：
                     `wait_until(lambda: gen_finished(page), ...)`
                   （直接写 `wait_until(gen_finished, ...)` 会每轮抛
                     TypeError 被吞掉 → 必然超时，且日志无声。见
                     `_predicate_error_note` 的说明。）
                   抛异常按「未满足」处理（DOM 还没出来的常见情况），
                   但第一次抛异常会**打印警告**，超时时 `detail` 里
                   也会带上最后一次的异常。
        timeout:  最长等多久（秒）。
        interval: 轮询间隔（秒）；`backoff=True` 时作为**起始**间隔。
        on_poll:  每轮回调（收到轮询次数），用于打心跳日志。
        desc:     仅用于日志/`detail`。
        backoff:  是否随时间放大间隔（见 `poll_interval`）。
        should_abort:
                  ★ 可选的中止判据（无参、返回 bool）。返回 True 时**立刻**
                  停下并返回 `aborted=True`（判据自身抛异常按"不中止"处理）。
                  用途：用户点「停止」时，正在等的 600 秒审稿超时不该等满。

    Returns:
        WaitResult
    """
    t0 = time.time()
    polls = 0
    last_err: Optional[BaseException] = None
    warned = False
    while True:
        if should_abort is not None:
            try:
                if should_abort():
                    return WaitResult(False, time.time() - t0, polls, None,
                                      f"{desc} 已中止".strip(), aborted=True)
            except Exception:
                pass
        polls += 1
        try:
            val = cond()
            last_err = None
        except BaseException as e:            # noqa: BLE001 - 故意全捕
            val = None
            last_err = e
            if not warned:
                warned = True
                _predicate_error_note(cond, e, desc)
        if val:
            el = time.time() - t0
            return WaitResult(True, el, polls, val, desc)
        el = time.time() - t0
        if el >= timeout:
            detail = f"{desc} 超时（{timeout}s）".strip()
            if last_err is not None:
                detail += (f"；谓词一直在报错："
                           f"{type(last_err).__name__}: {last_err}")
            return WaitResult(False, el, polls, None, detail)
        if on_poll is not None:
            try:
                on_poll(polls)
            except Exception:
                pass
        step = poll_interval(el, interval) if backoff else interval
        # 不要睡过 deadline
        time.sleep(min(step, max(0.0, timeout - el)))


def wait_gone(cond: Callable[[], Any],
              timeout: float = 10.0,
              interval: float = DEFAULT_INTERVAL,
              on_poll: Optional[Callable[[int], None]] = None,
              desc: str = "",
              should_abort: Optional[Callable[[], bool]] = None) -> WaitResult:
    """等 `cond` 变成**假值**（元素消失 / 计数归零）。

    与 `wait_until` 相反：一开始就为假则**立即**返回成功。
    `cond` 同样必须是**无参**可调用对象（见 `wait_until` 的说明）。
    `should_abort` 语义同 `wait_until`。
    """
    t0 = time.time()
    polls = 0
    last_err: Optional[BaseException] = None
    warned = False
    while True:
        if should_abort is not None:
            try:
                if should_abort():
                    return WaitResult(False, time.time() - t0, polls, None,
                                      f"{desc} 已中止".strip(), aborted=True)
            except Exception:
                pass
        polls += 1
        try:
            val = cond()
            last_err = None
        except BaseException as e:            # noqa: BLE001 - 故意全捕
            val = None
            last_err = e
            if not warned:
                warned = True
                _predicate_error_note(cond, e, desc)
        if not val:
            el = time.time() - t0
            return WaitResult(True, el, polls, None, desc)
        el = time.time() - t0
        if el >= timeout:
            detail = f"{desc} 超时（{timeout}s，仍未消失）".strip()
            if last_err is not None:
                detail += (f"；谓词一直在报错："
                           f"{type(last_err).__name__}: {last_err}")
            return WaitResult(False, el, polls, val, detail)
        if on_poll is not None:
            try:
                on_poll(polls)
            except Exception:
                pass
        step = poll_interval(el, interval)
        time.sleep(min(step, max(0.0, timeout - el)))


def wait_visible(page, selectors, timeout: float = 6.0,
                 interval: float = DEFAULT_INTERVAL,
                 desc: str = "") -> bool:
    """等任意一个选择器可见（多候选，命中即返回）。

    这是替换「click 之后 sleep 1.5 再检查」的标准工具。
    只读，不点击 —— 对风控无影响。
    """
    sels = [selectors] if isinstance(selectors, str) else list(selectors)
    label = desc or (sels[0] if sels else "?")

    def _cond():
        for sel in sels:
            try:
                if page.locator(sel).first.is_visible(timeout=60):
                    return sel
            except Exception:
                continue
        return None

    return wait_until(_cond, timeout=timeout, interval=interval,
                      desc=f"等待可见: {label}").ok


def wait_hidden(page, selectors, timeout: float = 6.0,
                interval: float = DEFAULT_INTERVAL,
                desc: str = "") -> bool:
    """等选择器全部不可见/消失（用于「等弹窗关掉」）。"""
    sels = [selectors] if isinstance(selectors, str) else list(selectors)
    label = desc or (sels[0] if sels else "?")

    def _cond():
        for sel in sels:
            try:
                if page.locator(sel).first.is_visible(timeout=60):
                    return False
            except Exception:
                continue
        return True

    return wait_until(_cond, timeout=timeout, interval=interval,
                      desc=f"等待消失: {label}").ok
