import math
import unittest

from teleoplab.metrics import EMPTY, drop_rate, jitter, percentile, summarize


class TestPercentile(unittest.TestCase):
    def test_nearest_rank(self):
        data = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(percentile(data, 50), 2.0)  # ceil(0.5*4)=2 -> 第 2 个
        self.assertEqual(percentile(data, 100), 4.0)
        self.assertEqual(percentile(data, 25), 1.0)

    def test_unsorted_input(self):
        self.assertEqual(percentile([4.0, 1.0, 3.0, 2.0], 50), 2.0)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            percentile([], 50)

    def test_p_out_of_range(self):
        with self.assertRaises(ValueError):
            percentile([1.0], 0)
        with self.assertRaises(ValueError):
            percentile([1.0], 101)


class TestSummarize(unittest.TestCase):
    def test_known_values(self):
        s = summarize([10.0, 20.0, 30.0, 40.0])
        self.assertEqual(s.count, 4)
        self.assertAlmostEqual(s.mean, 25.0)
        self.assertEqual(s.p50, 20.0)
        self.assertEqual(s.maximum, 40.0)

    def test_population_std(self):
        s = summarize([1.0, 3.0])
        self.assertAlmostEqual(s.std, 1.0, places=9)

    def test_empty_is_zeros_not_nan(self):
        self.assertEqual(summarize([]), EMPTY)
        self.assertFalse(math.isnan(EMPTY.p95))


class TestJitter(unittest.TestCase):
    def test_mean_absolute_consecutive_diff(self):
        self.assertAlmostEqual(jitter([10.0, 12.0, 11.0]), 1.5)

    def test_short_series(self):
        self.assertEqual(jitter([]), 0.0)
        self.assertEqual(jitter([5.0]), 0.0)

    def test_constant_series(self):
        self.assertEqual(jitter([3.0, 3.0, 3.0]), 0.0)


class TestDropRate(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(drop_rate(100, 95), 0.05)

    def test_no_sent(self):
        self.assertEqual(drop_rate(0, 0), 0.0)

    def test_more_received_than_sent_is_zero_not_negative(self):
        self.assertEqual(drop_rate(10, 12), 0.0)


if __name__ == "__main__":
    unittest.main()
