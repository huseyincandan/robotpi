"""Explore must not start against a SLAM map that excludes the robot."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from config import MAP
from services.ros2_navigation import Ros2NavigationService


class ExploreMapReadinessTests(unittest.TestCase):
    def test_requires_robot_pose_inside_fresh_map(self):
        navigator = Ros2NavigationService.__new__(Ros2NavigationService)
        with tempfile.TemporaryDirectory() as folder, patch.dict(MAP, {"DIR": folder}):
            output = Path(folder)
            pose = {"x": 0.0, "y": 0.0, "updated_at": time.time()}
            meta = {
                "origin": {"x": -1.86, "y": 0.0},
                "resolution": 0.025,
                "width": 71,
                "height": 92,
                "updated_at": time.time(),
            }
            (output / "live_pose.json").write_text(json.dumps(pose))
            (output / "live_map_meta.json").write_text(json.dumps(meta))

            self.assertFalse(navigator._wait_for_global_costmap_ready(timeout_sec=0))
            meta["origin"]["x"] = -2.0
            meta["width"] = 160
            meta["origin"]["y"] = -2.0
            meta["height"] = 160
            (output / "live_map_meta.json").write_text(json.dumps(meta))
            self.assertTrue(navigator._wait_for_global_costmap_ready(timeout_sec=0))


if __name__ == "__main__":
    unittest.main()
