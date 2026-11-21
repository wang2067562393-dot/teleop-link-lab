import asyncio
import unittest

from teleoplab.timing import sleep_until


class TestSleepUntil(unittest.TestCase):
    def test_waits_at_least_until_deadline(self):
        async def case() -> float:
            loop = asyncio.get_running_loop()
            start = loop.time()
            await sleep_until(start + 0.05)
            return loop.time() - start

        elapsed = asyncio.run(case())
        self.assertGreaterEqual(elapsed, 0.049)
        self.assertLess(elapsed, 0.5)

    def test_past_deadline_returns_immediately(self):
        async def case() -> float:
            loop = asyncio.get_running_loop()
            start = loop.time()
            await sleep_until(start - 1.0)
            return loop.time() - start

        self.assertLess(asyncio.run(case()), 0.05)

    def test_short_deadline_uses_spin_path(self):
        async def case() -> float:
            loop = asyncio.get_running_loop()
            start = loop.time()
            await sleep_until(start + 0.001)
            return loop.time() - start

        elapsed = asyncio.run(case())
        self.assertGreaterEqual(elapsed, 0.0009)

    def test_negative_spin_threshold_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(sleep_until(0.0, spin_threshold=-1))


if __name__ == "__main__":
    unittest.main()
