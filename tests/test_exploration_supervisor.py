import asyncio
import threading
import unittest
from unittest.mock import Mock, patch

from services.ros2_navigation import Ros2NavigationService


def make_navigator(reason="no_safe_frontier"):
    navigator = Ros2NavigationService.__new__(Ros2NavigationService)
    navigator.enabled = True
    navigator._explore_state_lock = threading.Lock()
    navigator._explore_start_lock = threading.Lock()
    navigator._explore_generation = 4
    navigator._exploration_intent = True
    navigator._exploration_waiting = False
    navigator._explore_retry_since = 0.0
    navigator._explore_process = object()
    navigator._exploration_activity = Mock(return_value=(False, reason))
    navigator._terminate_process_group = Mock()
    navigator._start_exploration = Mock(return_value={"status": "OK"})
    return navigator


class ExplorationSupervisorTests(unittest.TestCase):
    def test_no_safe_frontier_retries_after_cooldown_without_clearing_intent(self):
        navigator = make_navigator()
        process = navigator._explore_process
        with patch("services.ros2_navigation.time.monotonic", return_value=31):
            navigator.maintain_exploration()
        navigator._terminate_process_group.assert_called_once_with(process)
        navigator._start_exploration.assert_called_once_with(4)
        self.assertTrue(navigator._exploration_intent)

    def test_healthy_active_goal_is_never_restarted(self):
        navigator = make_navigator()
        navigator._exploration_activity.return_value = (True, "goal_active")
        with patch("services.ros2_navigation.time.monotonic", return_value=1000):
            navigator.maintain_exploration()
        navigator._start_exploration.assert_not_called()
        self.assertIsNone(navigator._explore_retry_since)

    def test_exited_process_is_restarted_after_ten_seconds(self):
        navigator = make_navigator("process_stopped")
        with patch("services.ros2_navigation.time.monotonic", return_value=11):
            navigator.maintain_exploration()
        navigator._start_exploration.assert_called_once_with(4)

    def test_short_idle_gap_does_not_restart_recovery(self):
        navigator = make_navigator()
        with patch("services.ros2_navigation.time.monotonic", return_value=29):
            navigator.maintain_exploration()
        navigator._start_exploration.assert_not_called()

    def test_operator_stop_prevents_any_restart(self):
        navigator = make_navigator()
        navigator.stop_exploration()
        navigator.maintain_exploration()
        self.assertFalse(navigator._exploration_intent)
        navigator._start_exploration.assert_not_called()

    def test_stop_arriving_during_activity_check_cancels_retry(self):
        navigator = make_navigator()
        def activity():
            navigator.stop_exploration()
            return False, "process_stopped"
        navigator._exploration_activity.side_effect = activity
        with patch("services.ros2_navigation.time.monotonic", return_value=100):
            navigator.maintain_exploration()
        navigator._start_exploration.assert_not_called()

    def test_stale_generation_cannot_reenable_stopped_session(self):
        navigator = make_navigator()
        navigator.stop_exploration()
        del navigator._start_exploration
        result = navigator.start_exploration(expected_generation=4)
        self.assertEqual(result["status"], "CANCELED")
        self.assertFalse(navigator._exploration_intent)

    def test_retry_does_not_overlap_user_start(self):
        navigator = make_navigator()
        with navigator._explore_start_lock:
            with patch("services.ros2_navigation.time.monotonic", return_value=100):
                navigator.maintain_exploration()
        navigator._start_exploration.assert_not_called()


class SupervisorSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_safety_fault_or_missing_scan_never_restarts_explorer(self):
        for power_fault, sensor_fault, lidar_ready in (
            (True, False, True), (False, True, True), (False, False, False),
            (False, False, True)
        ):
            with self.subTest(power=power_fault, sensor=sensor_fault, scan=lidar_ready):
                navigator = make_navigator()
                navigator.maintain_exploration = Mock()
                motor = Mock(power_fault=power_fault, sensor_fault=sensor_fault)
                lidar = Mock()
                lidar.is_ready.return_value = lidar_ready
                calls = 0
                async def sleep(_):
                    nonlocal calls
                    calls += 1
                    if calls > 1:
                        raise asyncio.CancelledError
                with patch("services.ros2_navigation.asyncio.sleep", side_effect=sleep):
                    with self.assertRaises(asyncio.CancelledError):
                        await navigator.supervise_exploration(motor, lidar)
                self.assertEqual(
                    navigator.maintain_exploration.call_count,
                    int(not power_fault and not sensor_fault and lidar_ready)
                )


if __name__ == "__main__":
    unittest.main()
