"""Guard the active path controller and frontier safety configuration."""

from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import yaml


ROOT = Path(__file__).resolve().parents[1]


class FrontierControllerConfigurationTests(unittest.TestCase):
    def test_route_tracking_uses_continuous_lookahead_with_collision_checks(self):
        config = yaml.safe_load((ROOT / "config/nav2_params.yaml").read_text())
        follow_path = config["controller_server"]["ros__parameters"]["FollowPath"]

        self.assertEqual(
            follow_path["plugin"],
            "nav2_rotation_shim_controller::RotationShimController",
        )
        self.assertEqual(
            follow_path["primary_controller"],
            "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController",
        )
        self.assertTrue(follow_path["rotate_to_goal_heading"])
        self.assertTrue(follow_path["use_collision_detection"])
        self.assertFalse(follow_path["use_rotate_to_heading"])
        self.assertGreater(follow_path["max_angular_accel"], 0.2)
        self.assertNotIn("critics", follow_path)

    def test_frontier_goal_uses_clearance_and_distance_constraints(self):
        explore = yaml.safe_load(
            (ROOT / "config/explore_lite_params.yaml").read_text()
        )["/**"]["ros__parameters"]
        nav2 = yaml.safe_load((ROOT / "config/nav2_params.yaml").read_text())
        global_costmap = nav2["global_costmap"]["global_costmap"]["ros__parameters"]
        inflation_radius = global_costmap["inflation_layer"]["inflation_radius"]

        self.assertGreater(explore["frontier_goal_standoff"], inflation_radius)
        self.assertEqual(explore["frontier_goal_max_cost"], 100)
        self.assertGreaterEqual(
            explore["min_goal_distance"],
            0.45,
        )

    def test_collision_recovery_retreats_once_before_trying_a_turn(self):
        root = ET.parse(ROOT / "config/nav2_bt_recovery_backup_first.xml").getroot()
        recovery = root.find(".//RecoveryNode[@name='NavigateRecovery']")
        self.assertIsNotNone(recovery)
        self.assertEqual(recovery.attrib["number_of_retries"], "1")
        escape = recovery.findall("./Sequence/Fallback")[-1]
        self.assertEqual([node.tag for node in escape], ["BackUp", "Spin"])
        self.assertLessEqual(float(escape[0].attrib["backup_dist"]), 0.20)
        self.assertLessEqual(float(escape[0].attrib["backup_speed"]), 0.10)


if __name__ == "__main__":
    unittest.main()
