"""命令行入口。

    python -m teleoplab run --delay-ms 100 --loss 0.05
    python -m teleoplab suite --out reports
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

    suite = sub.add_parser("suite", help="跑四个标准场景并写报告")
    suite.add_argument("--duration", type=float, default=6.0)
    suite.add_argument("--out", default="reports")
    suite.set_defaults(func=_run_suite)
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
