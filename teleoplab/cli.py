"""命令行入口。

    python -m teleoplab run --delay-ms 100 --loss 0.05
    python -m teleoplab suite --out reports

跨机器（三个终端 / 三台机器）：

    # 机器人端
    python -m teleoplab serve --role robot --port 9100 --duration 40
    # 代理（可选，第三台机器；不加就是直连）
    python -m teleoplab serve --role proxy --listen-port 9000 --robot 192.168.1.5:9100 --delay-ms 50
    # 控制端
    python -m teleoplab serve --role operator --proxy 192.168.1.5:9000 --duration 20 --out reports/remote.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from teleoplab.netem import NetemConfig
from teleoplab.report import render_json, render_markdown, render_table
from teleoplab.runner import Scenario, default_suite, run_scenario


def _run_one(args: argparse.Namespace) -> int:
    sc = Scenario(
        name=args.name,
        netem=NetemConfig(
            delay_ms=args.delay_ms,
            jitter_ms=args.jitter_ms,
            loss=args.loss,
            seed=args.seed,
        ),
        duration_s=args.duration,
        degradation=not args.no_degrade,
    )
    result = asyncio.run(run_scenario(sc))
    if args.json:
        print(render_json([result]))
    else:
        print(render_table([result]))
    return 0


def _run_suite(args: argparse.Namespace) -> int:
    scenarios = default_suite(args.duration)
    results = [asyncio.run(run_scenario(sc)) for sc in scenarios]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "weaknet.md").write_text(
        render_markdown(
            results,
            title="弱网实验报告",
            note=(
                "本机回环 + 可注入代理（种子固定），每档 60 s→此处为 "
                f"{scenarios[0].duration_s:g}s；延迟定义见文末口径。"
            ),
        ),
        encoding="utf-8",
    )
    (out_dir / "weaknet.json").write_text(render_json(results), encoding="utf-8")
    print(render_table(results))
    print(f"\n写入 {out_dir / 'weaknet.md'} 与 {out_dir / 'weaknet.json'}")
    return 0


def _parse_hostport(text: str) -> tuple[str, int]:
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port:
        raise argparse.ArgumentTypeError(f"地址要写成 host:port，收到 {text!r}")
    try:
        return host, int(port)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"端口不是整数：{port!r}") from exc


def _fmt(ms: dict | None, key: str = "p95") -> str:
    if not ms:
        return "n/a"
    return f"{ms[key]:.2f} ms"


def _serve(args: argparse.Namespace) -> int:
    from teleoplab import remote

    if args.role == "proxy" and args.robot is None:
        print("proxy 需要 --robot host:port", file=sys.stderr)
        return 2
    if args.role == "operator" and args.proxy is None:
        print("operator 需要 --proxy host:port", file=sys.stderr)
        return 2

    if args.role == "robot":
        result = asyncio.run(remote.run_robot(args.port, args.duration, bind=args.bind))
        print(
            f"[robot] 发出状态 {result['counts']['states_sent']}，"
            f"画面 {result['counts']['frames_sent']} 帧，对端 {result['peer']}"
        )
    elif args.role == "proxy":
        robot_host, robot_port = args.robot
        result = asyncio.run(
            remote.run_proxy(
                args.listen_port,
                robot_host,
                robot_port,
                args.duration,
                netem=NetemConfig(
                    delay_ms=args.delay_ms,
                    jitter_ms=args.jitter_ms,
                    loss=args.loss,
                    seed=args.seed,
                ),
                bind=args.bind,
            )
        )
        print(f"[proxy] 统计：{result['stats']}")
    else:
        proxy_host, proxy_port = args.proxy
        result = asyncio.run(
            remote.run_operator(
                proxy_host,
                proxy_port,
                args.duration,
                degrade=not args.no_degrade,
                rate_hz=args.rate_hz,
            )
        )
        age = result["cmd_age_ms"]
        print(
            "\n指令往返  p50 {0}  p95 {1}  p99 {2}   抖动 {3:.2f} ms".format(
                _fmt(age, "p50"), _fmt(age, "p95"), _fmt(age, "p99"), result["cmd_jitter_ms"]
            )
        )
        print(f"画面(原始)  {_fmt(result['video_raw_ms'])}")
        if result["video_synced_ms"]:
            print(f"画面(校正)  {_fmt(result['video_synced_ms'])}")
        clock = result["clock"]
        print(
            f"时钟偏移 {clock['offset_ms']} ms（{clock['samples']} 个样本，"
            f"最小 RTT {clock['min_rtt_ms']} ms）"
        )
        print(f"计数：{result['counts']}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n写入 {out}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="teleoplab", description="遥操作链路实验台")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="跑一个场景")
    run.add_argument("--name", default="custom")
    run.add_argument("--delay-ms", type=float, default=0.0)
    run.add_argument("--jitter-ms", type=float, default=0.0)
    run.add_argument("--loss", type=float, default=0.0, help="0–1")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--duration", type=float, default=6.0)
    run.add_argument("--no-degrade", action="store_true", help="关闭降级策略")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=_run_one)

    suite = sub.add_parser("suite", help="跑六个标准场景并写报告")
    suite.add_argument("--duration", type=float, default=6.0)
    suite.add_argument("--out", default="reports")
    suite.set_defaults(func=_run_suite)

    serve = sub.add_parser("serve", help="跨机器：分别启动机器人 / 代理 / 控制端")
    serve.add_argument("--role", choices=("robot", "proxy", "operator"), required=True)
    serve.add_argument("--duration", type=float, default=20.0, help="本进程运行时长（秒）")
    serve.add_argument("--bind", default="0.0.0.0", help="监听地址，默认所有网卡")
    serve.add_argument("--port", type=int, default=9100, help="robot 监听端口")
    serve.add_argument("--listen-port", type=int, default=9000, help="proxy 监听端口")
    serve.add_argument(
        "--robot", type=_parse_hostport, default=None, help="proxy 转发目标 host:port"
    )
    serve.add_argument(
        "--proxy", type=_parse_hostport, default=None, help="operator 连接的 host:port"
    )
    serve.add_argument("--delay-ms", type=float, default=0.0, help="proxy 注入延迟")
    serve.add_argument("--jitter-ms", type=float, default=0.0, help="proxy 注入抖动")
    serve.add_argument("--loss", type=float, default=0.0, help="proxy 注入丢包 0–1")
    serve.add_argument("--seed", type=int, default=0)
    serve.add_argument("--rate-hz", type=float, default=60.0, help="operator 指令频率")
    serve.add_argument("--no-degrade", action="store_true", help="关闭降级策略")
    serve.add_argument("--out", default=None, help="把本进程结果写成 JSON")
    serve.set_defaults(func=_serve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
