"""A persistent no-frontier result must end exploration cleanly."""

from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from services.ros2_navigation import Ros2NavigationService


class RunningProcess:
    def poll(self):
        return None


class ExploreCompletionTests(unittest.TestCase):
    def test_persistent_no_frontiers_reports_completion(self):
        navigator = Ros2NavigationService.__new__(Ros2NavigationService)
        navigator.enabled = True
        navigator._explore_state_lock = threading.Lock()
        navigator._explore_generation = 0
        navigator._exploration_intent = False
        navigator._exploration_complete = False
        navigator._explore_process = None
        navigator._nav2_process = RunningProcess()
        navigator._cmdvel_bridge_process = None
        navigator._imu_bridge_process = None
        navigator._ekf_process = None
        navigator._explore_launch_package = "explore_lite"
        navigator._explore_params_file = Path(__file__)
        navigator._explore_log = Path("/tmp/test-explore-completion.log")
        navigator._ros_bin_dir = "/tmp"
        navigator._ros_lib_dir = "/tmp"
        navigator._rmw_implementation = "rmw_cyclonedds_cpp"
        navigator._setup_bash = "/tmp/setup.bash"
        navigator.start_nav2 = lambda: {"status": "OK"}
        navigator._ensure_package_available = lambda _: {"status": "OK"}
        navigator._wait_for_global_costmap_ready = lambda timeout_sec: True
        navigator._exploration_activity = lambda: (False, "no_frontiers")
        spawned = []
        terminated = []
        navigator._spawn_command = lambda _: spawned.append(RunningProcess()) or spawned[-1]
        navigator._terminate_process_group = lambda process: terminated.append(process)

        with patch("services.ros2_navigation.time.sleep"):
            result = navigator.start_exploration()

        self.assertEqual(result["status"], "OK")
        self.assertIn("complete", result["message"].lower())
        self.assertEqual(len(spawned), 3)
        self.assertEqual(len(terminated), 3)
        self.assertFalse(navigator._exploration_intent)
        self.assertIsNone(navigator._explore_process)
        self.assertEqual(navigator.status()["explore_reason"], "complete")


if __name__ == "__main__":
    unittest.main()
