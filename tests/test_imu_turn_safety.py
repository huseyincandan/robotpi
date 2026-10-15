"""A turn-only command must still be watched for a chassis impact."""

import unittest
from unittest.mock import patch

from config import IMU
from services.imu import _ImuMotionMixin


class FakeImu(_ImuMotionMixin):
    def __init__(self):
        self._init_motion_state()
        self.samples = iter([
            {"accel_x": 0.0, "accel_y": 0.0, "accel_z": 1.0,
             "gyro_x": 0.0, "gyro_y": 0.0, "gyro_z": 0.0},
            {"accel_x": 1.3, "accel_y": 0.0, "accel_z": 1.0,
             "gyro_x": 0.0, "gyro_y": 0.0, "gyro_z": 0.0},
        ])

    def read_motion(self):
        return next(self.samples)


class ImuTurnSafetyTests(unittest.TestCase):
    def test_turn_only_impact_is_detected(self):
        imu = FakeImu()
        with patch.dict(IMU, {"IMPACT_STARTUP_GRACE_SECONDS": 0.0}):
            self.assertIsNone(imu.detect_stuck(20, 0))
            event = imu.detect_stuck(20, 0)
        self.assertIsNotNone(event)
        self.assertIn("impact", event["reasons"])


if __name__ == "__main__":
    unittest.main()
