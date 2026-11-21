"""跨机器模式：时钟偏移估计 + 三进程端到端。"""

from __future__ import annotations

import asyncio
import unittest

from teleoplab.remote import OffsetEstimator, run_operator, run_robot

MS = 1_000_000


class TestOffsetEstimator(unittest.TestCase):
    def test_symmetric_link_recovers_exact_offset(self):
        # 控制端 t0=0 发出，链路单向 5 ms，机器人时钟 = 控制端 + 1000 ms
        est = OffsetEstimator()
        est.add(0, 1000 * MS + 5 * MS, 10 * MS)
        best = est.best()
        assert best is not None
        offset, rtt = best
        self.assertEqual(rtt, 10 * MS)
        self.assertEqual(offset, 1000 * MS)

    def test_picks_lowest_rtt_sample(self):
        est = OffsetEstimator()
        est.add(0, 1000 * MS + 50 * MS, 100 * MS)  # RTT 100 ms，偏移误差大
        est.add(0, 1000 * MS + 5 * MS, 10 * MS)    # RTT 10 ms，应被选中
        best = est.best()
        assert best is not None
        self.assertEqual(best[1], 10 * MS)
        self.assertEqual(best[0], 1000 * MS)

    def test_asymmetry_error_bounded_by_half_asymmetry(self):
        # 机器人时钟 = 控制端 + 1000 ms；上行 2 ms、下行 8 ms（不对称 6 ms）
        est = OffsetEstimator()
        t0, t2 = 0, 10 * MS
        ts_robot = 1000 * MS + 2 * MS
        est.add(t0, ts_robot, t2)
        offset = est.offset_ns()
        assert offset is not None
        # 估计值 = 真实偏移 + (上行-下行)/2 = +1000ms - 3ms
        self.assertEqual(offset, 1000 * MS - 3 * MS)
        self.assertLessEqual(abs(offset - 1000 * MS), 3 * MS)

    def test_empty_returns_none(self):
        est = OffsetEstimator()
        self.assertIsNone(est.best())
        self.assertIsNone(est.offset_ns())
        self.assertIsNone(est.to_operator_clock(123))
        self.assertEqual(est.to_dict()["samples"], 0)

    def test_negative_rtt_sample_ignored(self):
        est = OffsetEstimator()
        est.add(100 * MS, 5 * MS, 10 * MS)  # t2 < t0，异常样本
        self.assertIsNone(est.best())

    def test_to_operator_clock_applies_offset(self):
        est = OffsetEstimator()
        est.add(0, 1000 * MS + 5 * MS, 10 * MS)
        # 机器人时间戳 2000 ms → 控制端时钟 1000 ms
        self.assertEqual(est.to_operator_clock(2000 * MS), 1000 * MS)


class TestRemoteEndToEnd(unittest.TestCase):
    """同一台机器上的两个进程内端点，走真实 UDP（非回环地址由 CI 决定，这里用本地）。"""

    def test_operator_robot_roundtrip(self):
        async def full():
            robot = asyncio.create_task(run_robot(19222, 2.0, bind="127.0.0.1"))
            await asyncio.sleep(0.2)
            op = await run_operator("127.0.0.1", 19222, 0.8, rate_hz=60.0)
            await robot
            return op

        try:
            result = asyncio.run(asyncio.wait_for(full(), timeout=30))
        except OSError as exc:  # 端口被占用
            self.skipTest(f"端口不可用：{exc}")

        self.assertEqual(result["role"], "operator")
        self.assertGreater(result["counts"]["cmds_sent"], 10)
        self.assertGreater(result["counts"]["states_received"], 5)
        self.assertIsNotNone(result["cmd_age_ms"]["p50"])
        # 本机回环下走真实 socket，偏移应接近 0（同机 perf_counter 同源）
        self.assertIsNotNone(result["clock"]["offset_ms"])
        self.assertLess(abs(result["clock"]["offset_ms"]), 20.0)
        self.assertIsNotNone(result["video_synced_ms"])


if __name__ == "__main__":
    unittest.main()
