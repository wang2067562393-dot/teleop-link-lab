"""统计口径。

只做三件事：分位数、抖动、丢包率。每一条都写清定义，因为这类指标
在不同团队里含义不同，报数字前必须能说清「我算的是什么」。

- 分位数用 **nearest-rank**（第 ceil(p/100·n) 个样本），不做插值：
  样本量小的时候插值会给出一个不存在的值，看起来更精确，其实是编的。
- 抖动用 **相邻样本绝对差值的均值**（RFC 3550 的思路），不是标准差：
  标准差混入了趋势和漂移，而抖动要的是「相邻两帧之间跳了多少」。
- 丢包率由「发出 - 收到」计算，发出数由发送方提供，不猜测。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Summary:
    count: int
    mean: float
    std: float
    p50: float
    p95: float
    p99: float
    maximum: float

    def as_dict(self) -> dict:
        return {
            "count": self.count,
            "mean": self.mean,
            "std": self.std,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "max": self.maximum,
        }


EMPTY = Summary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def percentile(values: Sequence[float], p: float) -> float:
    """nearest-rank 分位数。p 取 (0, 100]。"""
    if not values:
        raise ValueError("空序列没有分位数")
    if not 0 < p <= 100:
        raise ValueError(f"p 必须在 (0, 100]，收到 {p}")
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100.0 * len(ordered)))
    return ordered[rank - 1]


def summarize(values: Iterable[float]) -> Summary:
    data = list(values)
    if not data:
        return EMPTY
    n = len(data)
    m = sum(data) / n
    var = sum((v - m) ** 2 for v in data) / n if n > 1 else 0.0
    return Summary(
        count=n,
        mean=m,
        std=math.sqrt(var),
        p50=percentile(data, 50),
        p95=percentile(data, 95),
        p99=percentile(data, 99),
        maximum=max(data),
    )


def jitter(values: Sequence[float]) -> float:
    """相邻样本绝对差值的均值；样本少于 2 个时返回 0。"""
    if len(values) < 2:
        return 0.0
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    return sum(diffs) / len(diffs)


def drop_rate(sent: int, received: int) -> float:
    """丢弃比例 = 1 - 收到/发出。发出为 0 时返回 0，不返回 nan。"""
    if sent <= 0:
        return 0.0
    if received < 0:
        raise ValueError("received 不能为负")
    return max(0.0, 1.0 - received / sent)
