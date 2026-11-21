"""跨机器运行：把「控制端 / 代理 / 机器人」拆成三个独立进程。

## 为什么这样拆

单机回环最大的问题不是延迟低，而是**两端的时钟是同一个**，所有单程时间戳天然可比。
一旦跨机器，`perf_counter_ns()` 就不再可比——两个进程的起点不同，还各有漂移。

但只有一半的指标受影响：

- **指令往返（cmd_age）完全在控制端时钟上测量**：发出时记 `t0`，收到 ack 时记 `t2`，
  差值就是往返。这中间不需要任何时钟同步，跨机器直接可比。
- **画面端到端**用到机器人打的时间戳，必须先把机器人时钟换算到控制端时钟。

## 偏移怎么估

不新增报文类型：机器人收到指令后会立即回一个带自己时间戳的 `state`，
控制端手里有 `t0`（发出）、`t2`（收到）、以及 `ts_robot`（机器人发出 ack 的时刻），于是

    offset_i = ts_robot - (t0 + t2) / 2

单程链路不对称会给每个样本带误差：若上下行差 `d`，该样本的偏移误差约为 `d/2`。
所以取 **RTT 最小** 的样本（此时不对称量也最小），而不是取平均——平均会被抖动放大。

精度量级：同一局域网内 RTT 通常 < 5 ms，取 min 后偏移误差约 ±1 ms 量级，
对 p95 级别的统计够用；对亚毫秒指标不够用（README 局限里写明）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from teleoplab.link import Operator, Robot, now_ns
from teleoplab.metrics import jitter, summarize
from teleoplab.netem import NetemConfig, NetemProxy
from teleoplab.policy import DegradeConfig, DegradeController
from teleoplab.protocol import KIND_FRAME, KIND_STATE, Message
from teleoplab.timing import high_resolution_timer

SETTLE_S = 0.2


@dataclass
class OffsetEstimator:
    """用机器人 ack 的往返样本估计「机器人时钟 - 控制端时钟」。"""

    samples: list[tuple[int, int, int]] = field(default_factory=list)  # (t0, ts_robot, t2)

    def add(self, t_send_ns: int, t_robot_ns: int, t_recv_ns: int) -> None:
        self.samples.append((t_send_ns, t_robot_ns, t_recv_ns))

    @property
    def count(self) -> int:
        return len(self.samples)

    def best(self) -> tuple[int, int] | None:
        """返回 (offset_ns, rtt_ns)，取 RTT 最小的样本；无样本时返回 None。"""
        if not self.samples:
            return None
        best: tuple[int, int] | None = None
        for t0, ts_robot, t2 in self.samples:
            rtt = t2 - t0
            if rtt < 0:  # 时钟被回拨之类，丢弃
                continue
            offset = ts_robot - (t0 + t2) // 2
            if best is None or rtt < best[1]:
                best = (offset, rtt)
        return best

    def offset_ns(self) -> int | None:
        best = self.best()
        return None if best is None else best[0]

    def to_operator_clock(self, robot_ns: int) -> int | None:
        """把机器人时间戳换算成控制端时钟；没有样本时返回 None。

        offset = 机器人时钟 − 控制端时钟，所以换算是**减**。
        """
        off = self.offset_ns()
        return None if off is None else robot_ns - off

    def to_dict(self) -> dict:
        best = self.best()
        return {
            "samples": self.count,
            "offset_ms": None if best is None else round(best[0] / 1e6, 3),
            "min_rtt_ms": None if best is None else round(best[1] / 1e6, 3),
        }


@dataclass
class SyncOperator(Operator):
    """在 Operator 基础上记录时钟同步样本与原始画面时间戳。

    指令往返仍由父类统计（纯控制端时钟，跨机器可直接比）；
    这里额外保留 (t_recv, ts_robot) 供事后做偏移校正。
    """

    sync: OffsetEstimator = field(default_factory=OffsetEstimator)
    video_recv_and_ts: list[tuple[int, int]] = field(default_factory=list)

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        try:
            msg = Message.decode(data)
        except ValueError:
            super().datagram_received(data, addr)
            return
        if msg.kind == KIND_STATE:
            sent = self._pending.get(msg.seq)
            if sent is not None:
                self.sync.add(sent, msg.ts_ns, now_ns())
        elif msg.kind == KIND_FRAME:
            self.video_recv_and_ts.append((now_ns(), msg.ts_ns))
        super().datagram_received(data, addr)

    def synced_video_ms(self) -> list[float]:
        """换算到控制端时钟后的画面端到端延迟；无法校正时返回空列表。"""
        out: list[float] = []
        for t_recv, ts in self.video_recv_and_ts:
            t_capture = self.sync.to_operator_clock(ts)
            if t_capture is None:
                return []
            out.append((t_recv - t_capture) / 1e6)
        return out


async def run_robot(port: int, duration_s: float, bind: str = "0.0.0.0") -> dict:
    """机器人端：监听 port，收到指令立即 ack，并按等级发画面。"""
    loop = asyncio.get_running_loop()
    robot = Robot()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: robot, local_addr=(bind, port)
    )
    actual_port = transport.get_extra_info("sockname")[1]
    print(f"[robot] 监听 {bind}:{actual_port}，运行 {duration_s:g}s", flush=True)
    try:
        with high_resolution_timer():
            await robot.run(duration_s)
    finally:
        transport.close()
        await asyncio.sleep(0.05)
    return {
        "role": "robot",
        "listen": f"{bind}:{actual_port}",
        "duration_s": duration_s,
        "counts": {
            "states_sent": robot.counters.states_sent,
            "frames_sent": robot.counters.frames_sent,
            "frame_bytes": robot.counters.frame_bytes,
        },
        "final_level": robot.level,
        "peer": None if robot.client_addr is None else list(robot.client_addr),
    }


async def run_operator(
    proxy_host: str,
    proxy_port: int,
    duration_s: float,
    *,
    degrade: bool = True,
    rate_hz: float = 60.0,
) -> dict:
    """控制端：向代理发指令，统计往返与画面延迟，并估计时钟偏移。"""
    loop = asyncio.get_running_loop()
    cfg = DegradeConfig() if degrade else DegradeConfig(max_level=0)
    controller = DegradeController(cfg)
    op = SyncOperator(proxy_addr=(proxy_host, proxy_port), policy=controller, rate_hz=rate_hz)
    transport, _ = await loop.create_datagram_endpoint(lambda: op, local_addr=("0.0.0.0", 0))
    print(f"[operator] 目标 {proxy_host}:{proxy_port}，运行 {duration_s:g}s", flush=True)
    try:
        with high_resolution_timer():
            await op.drive(duration_s)
        await asyncio.sleep(SETTLE_S)
    finally:
        transport.close()
        await asyncio.sleep(0.05)

    synced = op.synced_video_ms()
    return {
        "role": "operator",
        "proxy": f"{proxy_host}:{proxy_port}",
        "duration_s": duration_s,
        "cmd_age_ms": summarize(op.cmd_ages_ms).as_dict(),
        "cmd_jitter_ms": jitter(op.cmd_ages_ms),
        "video_raw_ms": summarize(op.video_latency_ms).as_dict(),
        "video_synced_ms": summarize(synced).as_dict() if synced else None,
        "clock": op.sync.to_dict(),
        "counts": {
            "cmds_sent": op.counters.cmds_sent,
            "states_received": op.counters.states_received,
            "frames_received": op.counters.frames_received,
        },
        "policy": controller.summary(),
    }


async def run_proxy(
    listen_port: int,
    robot_host: str,
    robot_port: int,
    duration_s: float,
    *,
    netem: NetemConfig | None = None,
    bind: str = "0.0.0.0",
) -> dict:
    """弱网代理：控制端连它，它转发给机器人（可在第三台机器上）。"""
    proxy = NetemProxy(netem or NetemConfig())
    await proxy.start(bind=bind, listen_port=listen_port)
    proxy.robot_addr = (robot_host, robot_port)
    print(
        f"[proxy] 监听 {bind}:{proxy.listen_port} → 机器人 {robot_host}:{robot_port}"
        f"（{proxy.config.describe()}），运行 {duration_s:g}s",
        flush=True,
    )
    try:
        # 代理也要提高定时器分辨率：注入延迟由独立线程排程，
        # 进程若仍停留在默认 15.6 ms 粒度，注入 50 ms 会实测出 ~111 ms。
        with high_resolution_timer():
            await asyncio.sleep(duration_s)
    finally:
        stats = proxy.stats()
        proxy.close()
        await asyncio.sleep(0.05)
    return {
        "role": "proxy",
        "listen": f"{bind}:{proxy.listen_port}",
        "robot": f"{robot_host}:{robot_port}",
        "netem": {
            "delay_ms": proxy.config.delay_ms,
            "jitter_ms": proxy.config.jitter_ms,
            "loss": proxy.config.loss,
            "seed": proxy.config.seed,
        },
        "duration_s": duration_s,
        "stats": stats,
    }
