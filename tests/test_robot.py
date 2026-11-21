import unittest

from teleoplab.robot_sim import RobotSim


class TestRobotSim(unittest.TestCase):
    def test_one_second_at_one_mps_travels_one_metre(self):
        sim = RobotSim(tick_hz=100.0)
        sim.apply_command(1.0, 0.0)
        for _ in range(100):
            sim.step()
        self.assertAlmostEqual(sim.pose.x, 1.0, places=9)
        self.assertAlmostEqual(sim.pose.theta, 0.0, places=9)
        self.assertEqual(sim.tick, 100)

    def test_angular_velocity_integrates(self):
        sim = RobotSim(tick_hz=10.0)
        sim.apply_command(0.0, 1.0)
        for _ in range(10):
            sim.step()
        self.assertAlmostEqual(sim.pose.theta, 1.0, places=9)

    def test_command_is_clamped(self):
        sim = RobotSim(max_speed=0.5)
        sim.apply_command(100.0, -100.0)
        self.assertAlmostEqual(sim.pose.vx, 0.5)
        self.assertAlmostEqual(sim.pose.vz, -0.5)

    def test_invalid_config(self):
        with self.assertRaises(ValueError):
            RobotSim(tick_hz=0)
        with self.assertRaises(ValueError):
            RobotSim(max_speed=0)


if __name__ == "__main__":
    unittest.main()
