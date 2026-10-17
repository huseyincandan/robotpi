"""A late Explore startup must not undo an earlier stop request."""

from pathlib import Path
import threading
import unittest

from services.ros2_navigation import Ros2NavigationService


class ExploreStartStopRaceTests(unittest.TestCase):
    def test_stop_during_costmap_wait_prevents_late_launch(self):
        navigator = Ros2NavigationService.__new__(Ros2NavigationService)
        navigator.enabled = True
        navigator._explore_state_lock = threading.Lock()
        navigator._explore_start_lock = threading.Lock()
        navigator._explore_generation = 0
        navigator._exploration_intent = False
        navigator._explore_process = None
        navigator._explore_launch_package = "explore_lite"
        navigator._explore_params_file = Path(__file__)

        waiting = threading.Event()
        release = threading.Event()
        spawned = []

        navigator.start_nav2 = lambda: {"status": "OK"}
        navigator._ensure_package_available = lambda _: {"status": "OK"}

        def wait_for_costmap(timeout_sec):
            waiting.set()
            self.assertTrue(release.wait(5))
            return True

        navigator._wait_for_global_costmap_ready = wait_for_costmap
        navigator._spawn_command = lambda _: spawned.append(True)

        result = {}
        worker = threading.Thread(
            target=lambda: result.update(navigator.start_exploration()),
        )
        worker.start()
        self.assertTrue(waiting.wait(5))

        navigator.stop_exploration()
        release.set()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result["status"], "CANCELED")
        self.assertEqual(spawned, [])
        self.assertIsNone(navigator._explore_process)


if __name__ == "__main__":
    unittest.main()
