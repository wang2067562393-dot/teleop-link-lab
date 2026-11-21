"""模拟机器人：固定步长积分 + 状态回传。

刻意做成「纯函数式的一步」：`step()` 不睡、不读时钟，调用者决定节奏。
这样单元测试可以精确断言「100 步、每步 10 ms、速度 1 m/s → 走 1 m」，
而不需要等真实时间。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Pose:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0
    vx: float = 0.0
    vz: float = 0.0


class RobotSim:
    """差速底盘的一阶近似：只积分线速度 vx 与角速度 vz。"""

    def __init__(self, *, tick_hz: float = 100.0, max_speed: float = 1.0) -> None:
        if tick_hz <= 0:
            raise ValueError("tick_hz 必须为正")
        if max_speed <= 0:
            raise ValueError("max_speed 必须为正")
        self.tick_hz = tick_hz
        self.dt = 1.0 / tick_hz
        self.max_speed = max_speed
        self.pose = Pose()
        self.tick = 0

    def apply_command(self, vx: float, vz: float) -> None:
        """限幅后写入。真实机器人也会限幅，这里保持一致。"""
        self.pose.vx = max(-self.max_speed, min(self.max_speed, vx))
        self.pose.vz = max(-self.max_speed, min(self.max_speed, vz))

    def step(self) -> Pose:
        """推进一个固定步长。用 dt 而不是读墙钟，保证可复现。"""
        self.pose.x += self.pose.vx * self.dt
        self.pose.theta += self.pose.vz * self.dt
        self.tick += 1
        return self.pose

    def snapshot(self) -> tuple[float, float, float]:
        return (self.pose.x, self.pose.y, self.pose.theta)
