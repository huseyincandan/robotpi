import threading
import unittest
from collections import deque

from services.distance import DistanceService, valid_distance_cm


class FakeSensor:
    def __init__(self, distance_m, fresh=True):
        self.distance_m = distance_m
        self.fresh = fresh

    def is_fresh(self):
        return self.fresh

    @property
    def distance(self):
        return self.distance_m


def make_service(distance_m, fresh=True):
    service = DistanceService.__new__(DistanceService)
    service.sensor = FakeSensor(distance_m, fresh=fresh)
    service._samples = deque([90.0, 90.1, 89.9], maxlen=7)
    service._samples_lock = threading.Lock()
    return service


class DistanceValidationTests(unittest.TestCase):
    def test_accepts_only_finite_physical_range(self):
        self.assertTrue(valid_distance_cm(2.0, 4.0))
        self.assertTrue(valid_distance_cm(400.0, 4.0))
        for value in (-2648.0, 0.0, 1.99, 400.01, float("nan"), float("inf"), None):
            with self.subTest(value=value):
                self.assertFalse(valid_distance_cm(value, 4.0))

    def test_invalid_no_echo_clears_old_cluster(self):
        service = make_service(-26.48)
        self.assertIsNone(service.read_safety_centimeters())
        self.assertEqual(list(service._samples), [])

    def test_observation_reports_missing_for_invalid_no_echo(self):
        service = make_service(-26.48)
        observation = service.read_observation()
        self.assertIsNone(observation["distance_cm"])
        self.assertFalse(observation["stable"])
        self.assertEqual(observation["sample_count"], 0)
        self.assertFalse(observation["nearest_cluster_confirmed"])

    def test_stale_smoothed_echo_clears_old_cluster(self):
        service = make_service(0.0934, fresh=False)
        self.assertIsNone(service.read_safety_centimeters())
        self.assertEqual(list(service._samples), [])
        self.assertFalse(service.read_observation()["stable"])


if __name__ == "__main__":
    unittest.main()
