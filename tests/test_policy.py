import unittest

from teleoplab.policy import DegradeConfig, DegradeController, profile_for


def cfg(**kw):
    base = dict(degrade_ms=250, recover_ms=200, window_samples=5, recover_windows=2, max_level=2)
    base.update(kw)
    return DegradeConfig(**base)


class TestConfig(unittest.TestCase):
    def test_recover_threshold_must_be_lower(self):
        with self.assertRaises(ValueError):
            DegradeConfig(degrade_ms=200, recover_ms=250)

    def test_window_minimum(self):
        with self.assertRaises(ValueError):
            DegradeConfig(window_samples=1)

    def test_profiles(self):
        self.assertEqual(profile_for(0), (20, 64, 48))
        self.assertEqual(profile_for(2), (5, 16, 12))
        with self.assertRaises(ValueError):
            profile_for(9)


class TestDegrade(unittest.TestCase):
    def test_degrades_when_p95_over_threshold(self):
        ctl = DegradeController(cfg())
        for _ in range(5):
            level = ctl.observe(300.0)
        self.assertEqual(level, 1)
        self.assertEqual(len(ctl.transitions), 1)

    def test_not_degraded_below_threshold(self):
        ctl = DegradeController(cfg())
        for _ in range(20):
            level = ctl.observe(100.0)
        self.assertEqual(level, 0)
        self.assertEqual(ctl.transitions, [])

    def test_recovery_needs_consecutive_windows(self):
        ctl = DegradeController(cfg())
        for _ in range(5):
            ctl.observe(300.0)
        self.assertEqual(ctl.level, 1)
        for _ in range(5):  # 第一个恢复窗口：只累计 streak
            ctl.observe(100.0)
        self.assertEqual(ctl.level, 1)
        for _ in range(5):  # 第二个恢复窗口：升回 0
            ctl.observe(100.0)
        self.assertEqual(ctl.level, 0)

    def test_no_oscillation_between_thresholds(self):
        ctl = DegradeController(cfg())
        for _ in range(5):
            ctl.observe(300.0)
        self.assertEqual(ctl.level, 1)
        for _ in range(20):  # 240 落在 200 与 250 之间：既不升也不降
            ctl.observe(240.0)
        self.assertEqual(ctl.level, 1)

    def test_recovers_streak_reset_by_bad_window(self):
        ctl = DegradeController(cfg())
        for _ in range(5):
            ctl.observe(300.0)
        for _ in range(5):
            ctl.observe(100.0)  # streak=1
        for _ in range(5):
            ctl.observe(240.0)  # streak 归零
        for _ in range(5):
            ctl.observe(100.0)  # streak=1，仍不升
        self.assertEqual(ctl.level, 1)

    def test_max_level_caps(self):
        ctl = DegradeController(cfg(max_level=1))
        for _ in range(5):
            ctl.observe(400.0)
        for _ in range(5):
            ctl.observe(400.0)
        self.assertEqual(ctl.level, 1)

    def test_summary_shape(self):
        ctl = DegradeController(cfg())
        for _ in range(5):
            ctl.observe(300.0)
        summary = ctl.summary()
        self.assertEqual(summary["final_level"], 1)
        self.assertEqual(summary["profile"], (10, 32, 24))
        self.assertEqual(len(summary["transitions"]), 1)


if __name__ == "__main__":
    unittest.main()
