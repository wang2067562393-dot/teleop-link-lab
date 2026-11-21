import unittest

from teleoplab.netem import NetemConfig, NetemDecider


class TestConfig(unittest.TestCase):
    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            NetemConfig(delay_ms=-1)
        with self.assertRaises(ValueError):
            NetemConfig(jitter_ms=-1)

    def test_rejects_bad_loss(self):
        with self.assertRaises(ValueError):
            NetemConfig(loss=1.5)
        with self.assertRaises(ValueError):
            NetemConfig(loss=-0.1)

    def test_describe(self):
        text = NetemConfig(delay_ms=100, jitter_ms=20, loss=0.05).describe()
        self.assertIn("100", text)
        self.assertIn("5", text)


class TestDecider(unittest.TestCase):
    def test_loss_one_drops_everything(self):
        decider = NetemDecider(NetemConfig(loss=1.0, seed=0))
        for _ in range(50):
            self.assertIsNone(decider.decide())
        self.assertEqual(decider.dropped, 50)
        self.assertEqual(decider.forwarded, 0)

    def test_loss_zero_forwards_everything(self):
        decider = NetemDecider(NetemConfig(loss=0.0, delay_ms=0, seed=0))
        for _ in range(50):
            self.assertEqual(decider.decide(), 0.0)
        self.assertEqual(decider.forwarded, 50)

    def test_same_seed_same_decisions(self):
        a = [NetemDecider(NetemConfig(delay_ms=50, jitter_ms=10, loss=0.3, seed=7)).decide()
             for _ in range(1)]
        runs_a = []
        runs_b = []
        da = NetemDecider(NetemConfig(delay_ms=50, jitter_ms=10, loss=0.3, seed=7))
        db = NetemDecider(NetemConfig(delay_ms=50, jitter_ms=10, loss=0.3, seed=7))
        for _ in range(200):
            runs_a.append(da.decide())
            runs_b.append(db.decide())
        self.assertEqual(runs_a, runs_b)
        self.assertTrue(all(x is None or x >= 0 for x in runs_a))
        self.assertEqual(len(a), 1)

    def test_different_seed_differs(self):
        da = NetemDecider(NetemConfig(delay_ms=50, jitter_ms=20, loss=0.2, seed=1))
        db = NetemDecider(NetemConfig(delay_ms=50, jitter_ms=20, loss=0.2, seed=2))
        da_seq = [da.decide() for _ in range(300)]
        db_seq = [db.decide() for _ in range(300)]
        self.assertNotEqual(da_seq, db_seq)

    def test_loss_rate_statistically_close(self):
        decider = NetemDecider(NetemConfig(loss=0.2, seed=11))
        for _ in range(20000):
            decider.decide()
        rate = decider.dropped / 20000
        self.assertLess(abs(rate - 0.2), 0.02)

    def test_delay_never_negative(self):
        decider = NetemDecider(NetemConfig(delay_ms=5, jitter_ms=100, seed=3))
        for _ in range(1000):
            value = decider.decide()
            if value is not None:
                self.assertGreaterEqual(value, 0.0)


if __name__ == "__main__":
    unittest.main()
