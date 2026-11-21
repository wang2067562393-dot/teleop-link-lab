"""精确等待与 Windows 定时器分辨率。

**为什么不用裸 `asyncio.sleep`**：Windows 的默认定时器粒度约 15.6 ms，
一个 10 ms 的 tick 会被拖成 15.6 ms；更糟的是「应该睡 10 ms、实际睡 16 ms」
会让固定步长循环持续落后，然后在追赶时突发，测量结果出现双峰。

两层处理：
1. `high_resolution_timer()`：在 Windows 上把进程定时器分辨率提到 1 ms；
2. `sleep_until()`：远离 deadline 时用 `sleep` 粗等，最后 3 ms 改用
   `asyncio.sleep(0)` 让出控制权但不再等待定时器。

这个坑本身就值得记一笔：**先证明你的测量工具没坏，再去测别人。**
没有这两层，基线会显示 ~30 ms，而真实链路其实只有几毫秒——后面所有
对比都会建立在一个假基线上。
"""

from __future__ import annotations

import asyncio
import contextlib
import sys

SPIN_THRESHOLD_S = 0.003


@contextlib.contextmanager
def high_resolution_timer(period_ms: int = 1):
    """Windows 上把定时器分辨率提到 period_ms；其他平台是空操作。"""
    if sys.platform != "win32":  # pragma: no cover - 只在 Windows 生效
        yield
        return
    import ctypes

    winmm = ctypes.WinDLL("winmm")  # type: ignore[attr-defined]
    winmm.timeBeginPeriod(period_ms)
    try:
        yield
    finally:
        winmm.timeEndPeriod(period_ms)


async def sleep_until(deadline: float, *, spin_threshold: float = SPIN_THRESHOLD_S) -> None:
    """等到 loop.time() >= deadline。deadline 必须是同一个事件循环的时钟。"""
    if spin_threshold < 0:
        raise ValueError("spin_threshold 不能为负")
    loop = asyncio.get_running_loop()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return
        if remaining > spin_threshold:
            await asyncio.sleep(remaining - spin_threshold)
        else:
            await asyncio.sleep(0)
