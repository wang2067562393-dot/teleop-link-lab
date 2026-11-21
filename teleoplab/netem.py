"""弱网注入：延迟 / 抖动 / 丢包 / 乱序。

**为什么不用 `tc netem`**：它是行业标准，但需要 Linux + root，在 WSL2 里对
localhost 流量经常不生效，而且结果不可复现（没法用固定 seed 进 CI）。
所以主路径用这里的纯 Python UDP 代理：跨平台、种子固定、可单测。
`tc netem` 适合做一次交叉验证，不适合做每天的回归。

抖动语义：`jitter_ms` 是「大约 ±该值」，内部取 σ = jitter/2，
即约 95% 的样本落在 ±jitter 内。乱序不是显式实现，而是抖动与调度的副产物。
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, replace

from teleoplab.protocol import Message
from teleoplab.scheduler import DelayQueue


@dataclass(frozen=True)
class NetemConfig:
    delay_ms: float = 0.0
    jitter_ms: float = 0.0
    loss: float = 0.0
    seed: int = 0

    def __post_init__(self) -> None:
        if self.delay_ms < 0:
            raise ValueError("delay_ms 不能为负")
        if self.jitter_ms < 0:
            raise ValueError("jitter_ms 不能为负")
        if not 0.0 <= self.loss <= 1.0:
            raise ValueError("loss 必须在 [0, 1]")

    def describe(self) -> str:
        return f"delay={self.delay_ms:g}ms jitter=±{self.jitter_ms:g}ms loss={self.loss * 100:g}%"


class NetemDecider:
    """纯决策器：给定配置，决定这个包延迟多久（秒），或是否丢弃（None）。

    单独抽出来是为了可测：同一个 seed 必须产生同一串决策。
    """

    def __init__(self, config: NetemConfig) -> None:
        self.config = config
        self._rng = random.Random(config.seed)
        self.dropped = 0
        self.forwarded = 0

    def decide(self) -> float | None:
        # 先判丢包，再抽延迟：顺序固定，保证同 seed 同结果
        if self._rng.random() < self.config.loss:
            self.dropped += 1
            return None
        delay = self.config.delay_ms / 1000.0
        if self.config.jitter_ms > 0:
            delay += self._rng.gauss(0.0, self.config.jitter_ms / 2000.0)
        self.forwarded += 1
        return max(0.0, delay)


class _Pipe(asyncio.DatagramProtocol):
    """一条单向管道：收包后交给 handler。"""

    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.peer: tuple[str, int] | None = None
        self.handler = None  # type: ignore[var-annotated]

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        self.peer = addr
        if self.handler is not None:
            self.handler(data, addr)


class NetemProxy:
    """双向 UDP 代理：控制端 ↔ [代理] ↔ 机器人。"""

    def __init__(self, config: NetemConfig) -> None:
        self.config = config
        # 两个方向用不同的种子，避免上下行丢包完全同步（那不像真实网络）
        self.up = NetemDecider(replace(config, seed=config.seed))
        self.down = NetemDecider(replace(config, seed=config.seed + 1))
        self.listen_port = 0   # 控制端往这里发
        self.robot_port = 0    # 机器人往这里回
        self.robot_addr: tuple[str, int] | None = None
        self._operator_addr: tuple[str, int] | None = None
        self._client_pipe = _Pipe()
        self._robot_pipe = _Pipe()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._delay: DelayQueue | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._delay = DelayQueue(self._loop)
        self._client_pipe.handler = self._from_operator
        self._robot_pipe.handler = self._from_robot
        t1, _ = await self._loop.create_datagram_endpoint(
            lambda: self._client_pipe, local_addr=("127.0.0.1", 0)
        )
        t2, _ = await self._loop.create_datagram_endpoint(
            lambda: self._robot_pipe, local_addr=("127.0.0.1", 0)
        )
        self.listen_port = t1.get_extra_info("sockname")[1]
        self.robot_port = t2.get_extra_info("sockname")[1]

    def _from_operator(self, data: bytes, addr) -> None:
        self._operator_addr = addr
        self._schedule(self.up, self._robot_pipe.transport, data, self.robot_addr)

    def _from_robot(self, data: bytes, addr) -> None:
        self._schedule(self.down, self._client_pipe.transport, data, self._operator_addr)

    def _schedule(self, decider: NetemDecider, transport, data: bytes, target) -> None:
        if transport is None or target is None:
            return
        delay = decider.decide()
        if delay is None:
            return
        if delay <= 0:
            self._safe_send(transport, data, target)
        else:
            assert self._delay is not None
            self._delay.call_later(delay, self._safe_send, transport, data, target)

    @staticmethod
    def _safe_send(transport, data: bytes, target) -> None:
        if not transport.is_closing():
            transport.sendto(data, target)

    def close(self) -> None:
        if self._delay is not None:
            self._delay.close()
        for pipe in (self._client_pipe, self._robot_pipe):
            if pipe.transport is not None:
                pipe.transport.close()

    def stats(self) -> dict:
        return {
            "up_forwarded": self.up.forwarded,
            "up_dropped": self.up.dropped,
            "down_forwarded": self.down.forwarded,
            "down_dropped": self.down.dropped,
        }


def decode_or_none(data: bytes) -> Message | None:
    """代理本身不解析报文；这里留给需要检查内容时用。"""
    try:
        return Message.decode(data)
    except Exception:
        return None
