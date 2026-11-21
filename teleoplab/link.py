"""控制端与机器人两端的 asyncio 实现。

两端都只做「收包 → 打时间戳 → 记账」，不做业务判断；判断放在 policy 里。
这样时序问题可以单独测，降级逻辑也可以单独测。
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field

from teleoplab.policy import DegradeController, profile_for
from teleoplab.protocol import (
    KIND_CTRL,
    KIND_CMD,
    KIND_FRAME,
    KIND_STATE,
    Message,
    make_cmd,
    make_ctrl,
    make_frame,
    make_state,
    parse_cmd,
    parse_ctrl,
    parse_frame,
)
from teleoplab.robot_sim import RobotSim
from teleoplab.timing import sleep_until


def now_ns() -> int:
    """单调时钟纳秒。测量一律用它，不用 time.time()。"""
    return time.perf_counter_ns()


@dataclass
class Counters:
    cmds_sent: int = 0
    states_received: int = 0
    states_sent: int = 0
    frames_sent: int = 0
    frames_received: int = 0
    frame_bytes: int = 0
    ctrl_sent: int = 0


@dataclass
class Operator(asyncio.DatagramProtocol):
    proxy_addr: tuple[str, int]
    policy: DegradeController
    rate_hz: float = 60.0
    seq: int = 0
    level: int = 0
    transport: asyncio.DatagramTransport | None = None
    counters: Counters = field(default_factory=Counters)
    cmd_ages_ms: list[float] = field(default_factory=list)
    video_latency_ms: list[float] = field(default_factory=list)
    frame_ids: set[int] = field(default_factory=set)
    _pending: dict[int, int] = field(default_factory=dict)

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        try:
            msg = Message.decode(data)
        except ValueError:
            return
        t_recv = now_ns()
        if msg.kind == KIND_STATE:
            self.counters.states_received += 1
            sent = self._pending.pop(msg.seq, None)
            if sent is None:
                return
            age_ms = (t_recv - sent) / 1e6
            self.cmd_ages_ms.append(age_ms)
            new_level = self.policy.observe(age_ms)
            if new_level != self.level:
                self.level = new_level
                self._send(make_ctrl(self.seq, now_ns(), new_level))
                self.counters.ctrl_sent += 1
        elif msg.kind == KIND_FRAME:
            self.counters.frames_received += 1
            _, _, frame_id, _ = parse_frame(msg)
            self.frame_ids.add(frame_id)
            self.video_latency_ms.append((t_recv - msg.ts_ns) / 1e6)

    def _send(self, msg: Message) -> None:
        if self.transport is not None and not self.transport.is_closing():
            self.transport.sendto(msg.encode(), self.proxy_addr)

    async def drive(self, duration_s: float) -> None:
        period = 1.0 / self.rate_hz
        loop = asyncio.get_running_loop()
        start = loop.time()
        next_at = start
        while True:
            await sleep_until(next_at)
            next_at += period
            self.seq += 1
            t_send = now_ns()
            # 一条缓慢的正弦轨迹：既不是坐标轴运动，也不是随机噪声，便于肉眼判断滞后
            phase = (loop.time() - start) * 0.5
            self._pending[self.seq] = t_send
            self._send(make_cmd(self.seq, t_send, 0.6 * math.sin(phase), 0.4))
            self.counters.cmds_sent += 1
            if loop.time() - start >= duration_s:
                break


@dataclass
class Robot(asyncio.DatagramProtocol):
    tick_hz: float = 100.0
    level: int = 0
    transport: asyncio.DatagramTransport | None = None
    client_addr: tuple[str, int] | None = None
    sim: RobotSim = field(default_factory=RobotSim)
    counters: Counters = field(default_factory=Counters)
    last_seq: int = 0
    _frame_accum: float = 0.0
    _frame_id: int = 0
    _base: bytes | None = None

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        try:
            msg = Message.decode(data)
        except ValueError:
            return
        self.client_addr = addr
        if msg.kind == KIND_CMD:
            vx, vz = parse_cmd(msg)
            self.sim.apply_command(vx, vz)
            self.last_seq = msg.seq
            # 收到指令立即回 ack（同 seq）。
            # 不能用「下一个 100 Hz tick 再回」来测延迟：Windows 上 asyncio 的
            # 定时器粒度约 15.6 ms，那样测到的是采样栅格，不是链路。
            self._send(make_state(msg.seq, now_ns(), *self.sim.snapshot()))
            self.counters.states_sent += 1
        elif msg.kind == KIND_CTRL:
            self.level = parse_ctrl(msg)

    def _send(self, msg: Message) -> None:
        if self.client_addr is not None and self.transport is not None:
            if not self.transport.is_closing():
                self.transport.sendto(msg.encode(), self.client_addr)

    def _pixels(self, width: int, height: int) -> bytes:
        size = width * height
        if self._base is None or len(self._base) != size:
            self._base = bytes((i * 7 + 13) & 0xFF for i in range(size))
        # 每帧整体平移，画面会缓慢滚动 —— 人眼能看出卡顿时，说明确实卡了
        shift = self._frame_id % size
        base = self._base
        return base[shift:] + base[:shift]

    async def run(self, duration_s: float) -> None:
        loop = asyncio.get_running_loop()
        dt = 1.0 / self.tick_hz
        start = loop.time()
        next_tick = start
        while True:
            await sleep_until(next_tick)
            next_tick += dt
            self.sim.step()
            self._send(make_state(self.last_seq, now_ns(), *self.sim.snapshot()))
            self.counters.states_sent += 1

            self._frame_accum += dt
            fps, width, height = profile_for(self.level)
            if self._frame_accum >= 1.0 / fps:
                self._frame_accum = 0.0
                msg = make_frame(
                    self._frame_id,
                    now_ns(),
                    width,
                    height,
                    self._frame_id,
                    self._pixels(width, height),
                )
                self._send(msg)
                self.counters.frame_bytes += len(msg.encode())
                self.counters.frames_sent += 1
                self._frame_id += 1

            if loop.time() - start >= duration_s:
                break
