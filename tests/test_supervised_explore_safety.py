"""Supervised trials must let Nav2 retreat from a close front obstacle."""

import unittest

from scripts.run_supervised_explore import unsafe


class SupervisedExploreSafetyTests(unittest.TestCase):
    def state(self, forward_speed):
        return {
            "motor": {"current_y": forward_speed, "power_fault": False,
                      "sensor_fault": False},
            "lidar": {"front_cm": 24.0, "left_cm": 40.0,
                      "back_cm": 100.0, "right_cm": 40.0},
            "battery": {"status": "OK", "bus_voltage": 11.8},
            "ultrasonic": {"status": "OK", "stable": True,
                           "nearest_cluster_confirmed": True,
                           "distance_cm": 40.0},
        }

    def test_close_front_allows_reverse_or_rotation(self):
        self.assertIsNone(unsafe(self.state(-25), 32, 18))
        self.assertIsNone(unsafe(self.state(0), 32, 18))

    def test_close_front_stops_forward(self):
        self.assertEqual(unsafe(self.state(25), 32, 18), "front_clearance")

    def test_hard_clearance_limit_stops_any_direction(self):
        state = self.state(-25)
        state["lidar"]["left_cm"] = 17.0
        self.assertEqual(unsafe(state, 32, 18), "clearance_under_limit")


if __name__ == "__main__":
    unittest.main()
