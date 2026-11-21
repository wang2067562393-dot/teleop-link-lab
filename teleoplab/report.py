"""把一次或多次运行渲染成 Markdown 报告。

报告是给人看的，所以只放能支撑结论的列：分位数、抖动、丢帧率、降级行为。
平均值不放——延迟的长尾比均值重要，均值会把 p99 的灾难藏起来。
"""

from __future__ import annotations

import json

from teleoplab.runner import RunResult

HEADER = (
    "| 场景 | 注入 | 指令年龄 p50 | p95 | p99 | 抖动 | 画面 p95 "
    "| 丢帧率 | 下行码率 | 末级画质 | 切换 |"
)
SEP = "|" + "---|" * 11


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def render_table(results: list[RunResult]) -> str:
    lines = [HEADER, SEP]
    for r in results:
        netem = r.scenario.netem
        inject = f"{netem.delay_ms:g}ms"
        if netem.jitter_ms:
            inject += f"±{netem.jitter_ms:g}"
        if netem.loss:
            inject += f" / {netem.loss * 100:g}%丢"
        profile = r.policy["profile"]
        quality = f"L{r.final_level} ({profile[0]}fps {profile[1]}x{profile[2]})"
        lines.append(
            "| {name} | {inject} | {p50} | {p95} | {p99} | {jit} | {video} "
            "| {drop} | {kbps} | {quality} | {tr} |".format(
                name=r.scenario.name,
                inject=inject,
                p50=_fmt(r.cmd_age.p50),
                p95=_fmt(r.cmd_age.p95),
                p99=_fmt(r.cmd_age.p99),
                jit=_fmt(r.cmd_jitter_ms),
                video=_fmt(r.video_latency.p95),
                drop=f"{r.frame_drop_rate * 100:.1f}%",
                kbps=f"{r.downlink_kbps:.0f}",
                quality=quality,
                tr=r.transitions,
            )
        )
    return "\n".join(lines)


def render_markdown(results: list[RunResult], *, title: str, note: str = "") -> str:
    body = [
        f"# {title}",
        "",
        note.strip() or "_由 `python -m teleoplab suite` 自动生成。_",
        "",
        render_table(results),
        "",
        "## 口径",
        "",
        "- **指令年龄**：控制端发出指令 → 收到机器人 **立即回传的 ack**（同 seq）的时间差，含双向网络与机器人处理。",
        "  不用「下一个固定周期 tick 再回」测：Windows 上 asyncio 定时器粒度约 15.6 ms，那样测到的是采样栅格，不是链路。",
        "- **画面端到端**：机器人采集帧 → 控制端收到帧的时间差（单调时钟，同一进程域）。",
        "- **抖动**：相邻两次指令年龄的绝对差均值，不是标准差。",
        "- **丢帧率**：机器人发出帧数 vs 控制端收到帧数。",
        "- **下行码率**：发出帧总字节 × 8 / 时长，未计压缩（v0.1 是原始像素）。",
        "- **末级画质**：降级策略最终停留的档位；`切换` 是等级变化的次数。",
        "",
    ]
    for r in results:
        body.append(f"### {r.scenario.name}")
        body.append("")
        body.append(f"- 注入：`{r.scenario.netem.describe()}`，时长 {r.scenario.duration_s:g}s")
        body.append(
            f"- 计数：指令发出 {r.cmds_sent}，状态收到 {r.states_received}，"
            f"帧发出 {r.frames_sent}，帧收到 {r.frames_received}"
        )
        body.append(f"- 代理：{r.proxy}")
        body.append(f"- 降级：{r.policy['transitions'] or '未触发'}")
        body.append("")
    return "\n".join(body)


def render_json(results: list[RunResult]) -> str:
    return json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2)
