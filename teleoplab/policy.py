"""降级策略：延迟过高时降分辨率/帧率，恢复时要带回滞。

为什么必须有回滞：如果「超过 250 ms 就降，低于 250 ms 就升」，网络在阈值附近
抖动一次，链路会在两个画质之间反复切换，操作员看到的抖动比不降级还糟。
所以升档要求「连续 N 个窗口都低于恢复线」，降档则立即生效——坏了先保命，
好了再慢慢恢复。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from teleoplab.metrics import percentile


@dataclass(frozen=True)
class DegradeConfig:
    degrade_ms: float = 250.0   # p95 超过它就降一档
    recover_ms: float = 200.0   # p95 连续低于它才升一档
    window_samples: int = 60    # 一个判断窗口内的样本数（60Hz 下约 1 秒）
    recover_windows: int = 3    # 连续多少个窗口达标才升档
    max_level: int = 2

    def __post_init__(self) -> None:
        if self.degrade_ms <= self.recover_ms:
            raise ValueError("降级阈值必须大于恢复阈值，否则会来回振荡")
        if self.window_samples < 2:
            raise ValueError("窗口至少 2 个样本")
        if self.recover_windows < 1:
            raise ValueError("恢复窗口数至少 1")


# 等级 → (帧率, 宽, 高)。等级越高越省带宽，但操作员看到的信息越少。
LEVEL_PROFILES = {
    0: (20, 64, 48),
    1: (10, 32, 24),
    2: (5, 16, 12),
}


def profile_for(level: int) -> tuple[int, int, int]:
    if level not in LEVEL_PROFILES:
        raise ValueError(f"未知画质等级：{level}")
    return LEVEL_PROFILES[level]


class DegradeController:
    """输入指令年龄（毫秒），输出应使用的画质等级。"""

    def __init__(self, config: DegradeConfig | None = None) -> None:
        self.config = config or DegradeConfig()
        self.level = 0
        self.transitions: list[tuple[int, int, int]] = []  # (样本序号, 旧等级, 新等级)
        self._window: deque[float] = deque(maxlen=self.config.window_samples)
        self._recover_streak = 0
        self._seen = 0

    def observe(self, cmd_age_ms: float) -> int:
        """喂一个观测值，返回当前等级。等级变化会被记录下来。"""
        self._seen += 1
        self._window.append(cmd_age_ms)
        if len(self._window) < self.config.window_samples:
            return self.level

        p95 = percentile(list(self._window), 95)
        if p95 > self.config.degrade_ms and self.level < self.config.max_level:
            self._transit(self.level + 1)
            self._recover_streak = 0
        elif self.level > 0:
            if p95 < self.config.recover_ms:
                self._recover_streak += 1
                if self._recover_streak >= self.config.recover_windows:
                    self._transit(self.level - 1)
                    self._recover_streak = 0
            else:
                self._recover_streak = 0

        self._window.clear()
        return self.level

    def _transit(self, new_level: int) -> None:
        self.transitions.append((self._seen, self.level, new_level))
        self.level = new_level

    def summary(self) -> dict:
        return {
            "final_level": self.level,
            "transitions": [list(t) for t in self.transitions],
            "profile": profile_for(self.level),
        }
