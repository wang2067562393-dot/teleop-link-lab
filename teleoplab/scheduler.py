"""延迟排程：用独立线程 + 真实时钟，而不是 asyncio 定时器。

**为什么不用 `loop.call_later`**：Windows 上 `loop.time()` 来自 `GetTickCount64`，
分辨率约 15.6 ms，且只在每个 tick 更新。于是 `call_later(0.1)` 的目标时刻是用
一个「最多落后 15.6 ms」的时钟算出来的，实际会**提前**约 6 ms 触发。
实测：注入 100 ms 单向，实际只有约 94 ms；往返因此从 200 ms 变成 188 ms。

延迟注入器一旦系统偏早，所有「弱网下延迟是多少」的结论都会偏低。
所以这里换成独立线程：用 `time.perf_counter()`（高分辨率）排程，
`Condition.wait` 到点后再通过 `call_soon_threadsafe` 交回事件循环发送。
线程等待只会**偏晚**（毫秒级），不会偏早——对延迟注入来说这是正确的方向。
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import threading
import time
from typing import Any, Callable


class DelayQueue:
    """单线程排程器：到点后把发送动作交回事件循环。"""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._heap: list[tuple[float, int, Callable[..., Any], tuple]] = []
        self._counter = itertools.count()
        self._cond = threading.Condition()
        self._stopped = False
        self._thread = threading.Thread(target=self._run, name="teleoplab-delay", daemon=True)
        self._thread.start()
        self.delivered = 0

    def call_later(self, delay_s: float, fn: Callable[..., Any], *args: Any) -> None:
        if delay_s <= 0:
            fn(*args)
            return
        due = time.perf_counter() + delay_s
        with self._cond:
            heapq.heappush(self._heap, (due, next(self._counter), fn, args))
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._heap and not self._stopped:
                    self._cond.wait()
                if self._stopped:
                    return
                due, _, fn, args = self._heap[0]
                remaining = due - time.perf_counter()
                if remaining > 0:
                    self._cond.wait(remaining)
                    continue
                heapq.heappop(self._heap)
            try:
                if not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(fn, *args)
                    self.delivered += 1
            except RuntimeError:  # 事件循环已关闭：丢弃即可，调用方正在退出
                return

    def close(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()
        self._thread.join(timeout=1.0)

    def __enter__(self) -> "DelayQueue":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
