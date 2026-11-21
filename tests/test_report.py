import json
import unittest

from teleoplab.metrics import Summary
from teleoplab.netem import NetemConfig
from teleoplab.report import render_json, render_markdown, render_table
from teleoplab.runner import RunResult, Scenario

SUMMARY = Summary(count=100, mean=120.0, std=10.0, p50=118.0, p95=150.0, p99=180.0, maximum=200.0)


def make_result(name="baseline", delay=0.0, loss=0.0, level=0) -> RunResult:
    return RunResult(
        scenario=Scenario(name, NetemConfig(delay_ms=delay, loss=loss), 6.0),
        cmd_age=SUMMARY,
        cmd_jitter_ms=3.5,
        video_latency=SUMMARY,
        cmds_sent=360,
        states_received=360,
        frames_sent=120,
        frames_received=110,
        frame_bytes=120 * 3100,
        proxy={"up_forwarded": 360, "up_dropped": 0, "down_forwarded": 470, "down_dropped": 10},
        policy={"final_level": level, "transitions": [], "profile": (20, 64, 48)},
    )


class TestReport(unittest.TestCase):
    def test_table_has_header_and_rows(self):
        table = render_table([make_result(), make_result("lossy", delay=100, loss=0.05, level=1)])
        self.assertIn("指令年龄 p50", table)
        self.assertIn("baseline", table)
        self.assertIn("lossy", table)
        self.assertIn("5%丢", table)

    def test_drop_rate_in_table(self):
        table = render_table([make_result()])
        self.assertIn("8.3%", table)  # 120 发出 / 110 收到

    def test_markdown_contains_sections(self):
        text = render_markdown([make_result()], title="弱网实验报告")
        self.assertTrue(text.startswith("# 弱网实验报告"))
        self.assertIn("## 口径", text)
        self.assertIn("### baseline", text)

    def test_json_is_parseable(self):
        payload = json.loads(render_json([make_result()]))
        self.assertEqual(payload[0]["scenario"], "baseline")
        self.assertAlmostEqual(payload[0]["frame_drop_rate"], 10 / 120, places=9)
        self.assertEqual(payload[0]["cmd_age_ms"]["p95"], 150.0)


if __name__ == "__main__":
    unittest.main()
