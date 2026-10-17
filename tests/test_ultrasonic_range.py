import unittest

from services.ultrasonic_range import mapping_range_m


class UltrasonicMappingTests(unittest.TestCase):
    def payload(self, distance, confidence=0.95, stable=True):
        return {
            "status": "OK", "distance_cm": distance,
            "confidence": confidence, "stable": stable
        }

    def test_close_return_keeps_sensor_relative_distance_without_axle_offset(self):
        self.assertAlmostEqual(mapping_range_m(self.payload(8.7), 20), 0.087)
        self.assertEqual(mapping_range_m(self.payload(20), 20), 0.20)

    def test_distant_returns_are_not_obstacles_or_free_space_evidence(self):
        for distance in (20.01, 40, 90, 400):
            self.assertIsNone(mapping_range_m(self.payload(distance), 20))

    def test_invalid_or_unconfirmed_measurements_are_rejected(self):
        for distance in (None, -1, 0, 1.99, float("nan"), float("inf"), "bad"):
            self.assertIsNone(mapping_range_m(self.payload(distance), 20))
        self.assertIsNone(mapping_range_m(self.payload(8.7, stable=False), 20))
        self.assertIsNone(mapping_range_m(self.payload(8.7, confidence=0.6), 20))
        self.assertIsNone(mapping_range_m(self.payload(8.7, confidence=float("nan")), 20))


if __name__ == "__main__":
    unittest.main()
