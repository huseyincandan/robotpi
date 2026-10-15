"""Exercise a hidden-obstacle stall and a verified reverse escape."""

import unittest

from services.motion_progress import MotionProgressGuard


class MotionProgressTests(unittest.TestCase):
    def test_static_body_stops_forward_even_if_wheels_could_spin(self):
        guard = MotionProgressGuard(window_seconds=3.0)
        pose = (1.0, 2.0, 0.0)
        self.assertFalse(guard.update(0, 58, pose, 0.0))
        self.assertFalse(guard.update(0, 58, pose, 2.9))
        self.assertTrue(guard.update(0, 58, pose, 3.0))
        self.assertTrue(guard.blocked(0, 58))
        self.assertFalse(guard.blocked(0, -58))

    def test_opposite_motion_must_really_move_body_before_release(self):
        guard = MotionProgressGuard()
        guard.block(0, 58, (0.0, 0.0, 0.0))
        guard.update(0, -58, (0.03, 0.0, 0.0), 0.0)
        self.assertTrue(guard.blocked(0, 58))
        guard.update(0, -58, (0.07, 0.0, 0.0), 1.0)
        self.assertFalse(guard.blocked(0, 58))

    def test_verified_turn_releases_blocked_forward_direction(self):
        guard = MotionProgressGuard()
        guard.block(0, 58, (0.0, 0.0, 0.0))
        guard.update(30, 0, (0.0, 0.0, 0.20), 0.0)
        self.assertTrue(guard.blocked(0, 58))
        guard.update(30, 0, (0.0, 0.0, 0.37), 1.0)
        self.assertFalse(guard.blocked(0, 58))

    def test_scan_rotation_requires_two_changed_sectors(self):
        guard = MotionProgressGuard()
        guard.block(0, 58, (1.0, 1.0, 1.0, 1.0), kind="scan")
        guard.update(30, 0, (1.0, 1.0, 1.3, 1.0), 0.0, kind="scan")
        self.assertTrue(guard.blocked(0, 58))
        guard.update(30, 0, (1.0, 1.0, 1.3, 1.3), 1.0, kind="scan")
        self.assertFalse(guard.blocked(0, 58))

    def test_turn_only_stall_uses_yaw_progress(self):
        guard = MotionProgressGuard(window_seconds=3.0)
        pose = (0.0, 0.0, 0.0)
        guard.update(20, 0, pose, 0.0)
        self.assertTrue(guard.update(20, 0, pose, 3.1))
        self.assertTrue(guard.blocked(20, 0))

    def test_missing_pose_does_not_trigger_false_stall(self):
        guard = MotionProgressGuard(window_seconds=3.0)
        guard.update(0, 58, (0.0, 0.0, 0.0), 0.0)
        self.assertFalse(guard.update(0, 58, None, 4.0))
        self.assertFalse(guard.blocked(0, 58))

    def test_static_scan_detects_stall_when_map_pose_is_stale(self):
        guard = MotionProgressGuard(window_seconds=3.0)
        scan = (0.85, 1.13, 1.04, 0.20)
        guard.update(0, 58, scan, 0.0, kind="scan")
        self.assertTrue(guard.update(0, 58, scan, 3.1, kind="scan"))
        self.assertTrue(guard.blocked(0, 58))
        guard.update(0, -58, (0.85, 1.13, 1.97, 0.20), 3.15, kind="scan")
        self.assertTrue(guard.blocked(0, 58))
        guard.update(0, -58, (0.88, 1.10, 1.04, 0.20), 3.2, kind="scan")
        self.assertTrue(guard.blocked(0, 58))
        guard.update(0, -58, (0.96, 1.02, 1.04, 0.20), 4.0, kind="scan")
        self.assertFalse(guard.blocked(0, 58))


if __name__ == "__main__":
    unittest.main()
