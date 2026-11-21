"""把一端一端接起来，跑一次完整场景，产出可比较的结果。

链路的落点很关键：代理夹在中间，所有包都必须真的经过它，否则测出来的
延迟是「本机回环」，没有意义。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from teleoplab.link import Operator, Robot
from teleoplab.metrics import Summary, drop_rate, jitter, summarize
from teleoplab.netem import NetemConfig, NetemProxy
from teleoplab.policy import DegradeConfig, DegradeController, profile_for
from teleoplab.timing import high_resolution_timer

SETTLE_S = 0.2  # 收尾等待：让在途的延迟包落地后再统计，避免尾部样本被截断


@dataclass(frozen=True)
class Scenario:
    name: str
    netem: NetemConfig = field(default_factory=NetemConfig)
    duration_s: float = 6.0
    degradation: bool = True
    degrade_config: DegradeConfig = field(default_factory=DegradeConfig)


@dataclass
class RunResult:
    scenario: Scenario
    cmd_age: Summary
    cmd_jitter_ms: float
    video_latency: Summary
    cmds_sent: int
    states_received: int
    frames_sent: int
    frames_received: int
    frame_bytes: int
    proxy: dict
    policy: dict

    @property
    def frame_drop_rate(self) -> float:
        return drop_rate(self.frames_sent, self.frames_received)

    @property
    def downlink_kbps(self) -> float:
        """下行视频码率（kbps）= 发出帧总字节 × 8 / 时长。"""
        if self.scenario.duration_s <= 0:
            return 0.0
        return self.frame_bytes * 8 / self.scenario.duration_s / 1000.0

    @property
    def final_level(self) -> int:
        return int(self.policy["final_level"])

    @property
    def transitions(self) -> int:
        return len(self.policy["transitions"])

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario.name,
            "netem": {
                "delay_ms": self.scenario.netem.delay_ms,
                "jitter_ms": self.scenario.netem.jitter_ms,
                "loss": self.scenario.netem.loss,
            },
            "duration_s": self.scenario.duration_s,
            "degradation": self.scenario.degradation,
            "cmd_age_ms": self.cmd_age.as_dict(),
            "cmd_jitter_ms": self.cmd_jitter_ms,
            "video_latency_ms": self.video_latency.as_dict(),
            "counts": {
                "cmds_sent": self.cmds_sent,
                "states_received": self.states_received,
                "frames_sent": self.frames_sent,
                "frames_received": self.frames_received,
            },
            "frame_drop_rate": self.frame_drop_rate,
            "downlink_kbps": self.downlink_kbps,
            "proxy": self.proxy,
            "policy": self.policy,
        }


async def run_scenario(sc: Scenario) -> RunResult:
    loop = asyncio.get_running_loop()

    robot = Robot()
    robot_transport, _ = await loop.create_datagram_endpoint(
        lambda: robot, local_addr=("127.0.0.1", 0)
    )
    robot_port = robot_transport.get_extra_info("sockname")[1]

    proxy = NetemProxy(sc.netem)
    await proxy.start()
    proxy.robot_addr = ("127.0.0.1", robot_port)

    degrade_cfg = sc.degrade_config if sc.degradation else DegradeConfig(max_level=0)
    controller = DegradeController(degrade_cfg)
    operator = Operator(proxy_addr=("127.0.0.1", proxy.listen_port), policy=controller)
    operator_transport, _ = await loop.create_datagram_endpoint(
        lambda: operator, local_addr=("127.0.0.1", 0)
    )

    try:
        with high_resolution_timer():
            await asyncio.gather(robot.run(sc.duration_s), operator.drive(sc.duration_s))
        await asyncio.sleep(SETTLE_S)
    finally:
        operator_transport.close()
        proxy.close()
        robot_transport.close()
        await asyncio.sleep(0.05)

    policy_summary = controller.summary()
    policy_summary["profile"] = list(profile_for(controller.level))
    return RunResult(
        scenario=sc,
        cmd_age=summarize(operator.cmd_ages_ms),
        cmd_jitter_ms=jitter(operator.cmd_ages_ms),
        video_latency=summarize(operator.video_latency_ms),
        cmds_sent=operator.counters.cmds_sent,
        states_received=operator.counters.states_received,
        frames_sent=robot.counters.frames_sent,
        frames_received=operator.counters.frames_received,
        frame_bytes=robot.counters.frame_bytes,
        proxy=proxy.stats(),
        policy=policy_summary,
    )


def default_suite(duration_s: float = 6.0) -> list[Scenario]:
    """六个场景：基线 → 有延迟 → 有丢包 → 又慢又丢 → 降级开/关对照。"""
    return [
        Scenario("baseline", NetemConfig(), duration_s),
        Scenario("delay-100ms", NetemConfig(delay_ms=100.0, seed=1), duration_s),
        Scenario(
            "delay-100ms+loss-5%",
            NetemConfig(delay_ms=100.0, loss=0.05, seed=2),
            duration_s,
        ),
        Scenario(
            "delay-200ms+jitter-20ms+loss-10%",
            NetemConfig(delay_ms=200.0, jitter_ms=20.0, loss=0.10, seed=3),
            duration_s,
        ),
        Scenario(
            "delay-300ms-无降级",
            NetemConfig(delay_ms=300.0, seed=4),
            duration_s,
            degradation=False,
        ),
        Scenario("delay-300ms-有降级", NetemConfig(delay_ms=300.0, seed=4), duration_s),
    ]
