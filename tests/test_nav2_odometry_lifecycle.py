"""SLAM must retain odometry when only Nav2 navigation is stopped."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from services.ros2_navigation import Ros2NavigationService


class Nav2OdometryLifecycleTests(unittest.TestCase):
    def test_navigation_stop_preserves_odom_until_service_close(self):
        service = Ros2NavigationService.__new__(Ros2NavigationService)
        nav2 = object()
        bridge = object()
        imu = object()
        ekf = object()
        service._nav2_process = nav2
        service._cmdvel_bridge_process = bridge
        service._imu_bridge_process = imu
        service._ekf_process = ekf
        service.stop_exploration = Mock()
        service._terminate_process_group = Mock()

        service.stop_nav2()

        self.assertIsNone(service._nav2_process)
        self.assertIs(service._cmdvel_bridge_process, bridge)
        self.assertIs(service._imu_bridge_process, imu)
        self.assertIs(service._ekf_process, ekf)
        service._terminate_process_group.assert_called_once_with(nav2)

        service.close()

        terminated = [call.args[0] for call in service._terminate_process_group.call_args_list]
        self.assertIn(bridge, terminated)
        self.assertIn(imu, terminated)
        self.assertIn(ekf, terminated)

    def test_explorer_reports_no_safe_frontier_after_a_finished_goal(self):
        service = Ros2NavigationService.__new__(Ros2NavigationService)
        service._explore_process = Mock()
        service._explore_process.poll.return_value = None
        with TemporaryDirectory() as directory:
            service._explore_log = Path(directory) / "explore.log"
            service._explore_log.write_text(
                "Sending goal to move base nav2\n"
                "Goal was successful\n"
                "No frontier target below cost 100 yet; waiting for map update.\n"
            )
            self.assertEqual(service._exploration_activity(), (False, "no_safe_frontier"))


if __name__ == "__main__":
    unittest.main()
