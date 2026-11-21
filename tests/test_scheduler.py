import asyncio
import time
import unittest

from teleoplab.scheduler import DelayQueue


class TestDelayQueue(unittest.TestCase):
    def test_fires_no_earlier_than_requested(self):
        async def case() -> float:
            loop = asyncio.get_running_loop()
            done = loop.create_future()

            def fire() -> None:
                if not done.done():
                    done.set_result(time.perf_counter() - t0)

            with DelayQueue(loop) as dq:
                t0 = time.perf_counter()
                dq.call_later(0.05, fire)
                return await asyncio.wait_for(done, timeout=2.0)

        elapsed = asyncio.run(case())
        # 关键断言：只能偏晚，不能偏早（asyncio 定时器在 Windows 上会偏早 ~6 ms）
        self.assertGreaterEqual(elapsed, 0.049)
        self.assertLess(elapsed, 0.3)

    def test_preserves_order(self):
        async def case() -> list[str]:
            loop = asyncio.get_running_loop()
            order: list[str] = []
            done = loop.create_future()

            def mark(tag: str) -> None:
                order.append(tag)
                if len(order) == 3 and not done.done():
                    done.set_result(order)

            with DelayQueue(loop) as dq:
                dq.call_later(0.06, mark, "c")
                dq.call_later(0.02, mark, "a")
                dq.call_later(0.04, mark, "b")
                return await asyncio.wait_for(done, timeout=2.0)

        self.assertEqual(asyncio.run(case()), ["a", "b", "c"])

    def test_zero_delay_is_immediate(self):
        async def case() -> bool:
            loop = asyncio.get_running_loop()
            hits: list[int] = []
            with DelayQueue(loop) as dq:
                dq.call_later(0.0, hits.append, 1)
            return hits == [1]

        self.assertTrue(asyncio.run(case()))

    def test_close_is_idempotent(self):
        async def case() -> None:
            loop = asyncio.get_running_loop()
            dq = DelayQueue(loop)
            dq.close()
            dq.close()

        asyncio.run(case())


if __name__ == "__main__":
    unittest.main()
