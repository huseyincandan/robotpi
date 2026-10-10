"""Verify autonomous ultrasonic gating stays separate from manual protection."""

from types import SimpleNamespace
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import LIDAR, ULTRASONIC
from routes.control import register_control_routes


class FakeLidar:
    front_cm = 100.0

    def get_distances_cm(self):
        return {"front_cm": self.front_cm}


class FakeMotor:
    sensor_fault = False
    power_fault = False
    last_obstacle_distance = None
    last_block_reason = None

    def __init__(self):
        self.ultrasonic_reads = 0
        self.drive_calls = []
        self.stop_calls = 0

    def read_distance_centimeters(self):
        self.ultrasonic_reads += 1
        return 11.8

    def drive(self, x, y, **kwargs):
        self.drive_calls.append((x, y, kwargs))
        return True

    def stop(self):
        self.stop_calls += 1


class AutonomousUltrasonicGateTests(unittest.TestCase):
    def setUp(self):
        self.old_enabled = ULTRASONIC.get("AUTONOMOUS_FORWARD_STOP_ENABLED")
        self.old_front_stop = LIDAR.get("FRONT_STOP_CM")
        LIDAR["FRONT_STOP_CM"] = 40
        self.motor = FakeMotor()
        self.lidar = FakeLidar()
        app = FastAPI()
        register_control_routes(
            app,
            self.motor,
            movement=SimpleNamespace(lidar=self.lidar),
        )
        self.client = TestClient(app)

    def tearDown(self):
        ULTRASONIC["AUTONOMOUS_FORWARD_STOP_ENABLED"] = self.old_enabled
        LIDAR["FRONT_STOP_CM"] = self.old_front_stop
        self.client.close()

    def test_autonomous_nav_ignores_close_ultrasonic_echo(self):
        ULTRASONIC["AUTONOMOUS_FORWARD_STOP_ENABLED"] = False

        response = self.client.get("/drive", params={"y": 10, "source": "nav2"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "OK"})
        self.assertEqual(self.motor.ultrasonic_reads, 0)
        self.assertEqual(len(self.motor.drive_calls), 1)

    def test_manual_forward_still_stops_on_close_ultrasonic_echo(self):
        ULTRASONIC["AUTONOMOUS_FORWARD_STOP_ENABLED"] = False

        response = self.client.get("/drive", params={"y": 10, "source": "manual"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "BLOCKED")
        self.assertEqual(response.json()["reason"], "ultrasonic")
        self.assertGreater(self.motor.ultrasonic_reads, 0)
        self.assertEqual(self.motor.drive_calls, [])

    def test_autonomous_lidar_gate_keeps_turn_while_blocking_forward(self):
        self.lidar.front_cm = 27.5
        ULTRASONIC["AUTONOMOUS_FORWARD_STOP_ENABLED"] = False

        response = self.client.get(
            "/drive", params={"x": 20, "y": 30, "source": "nav2"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "BLOCKED")
        self.assertEqual(response.json()["reason"], "lidar")
        self.assertEqual(self.motor.stop_calls, 0)
        self.assertEqual(len(self.motor.drive_calls), 1)
        self.assertEqual(self.motor.drive_calls[0][:2], (20, 0))

    def test_autonomous_can_maneuver_inside_manual_stop_distance(self):
        self.lidar.front_cm = 37.5
        ULTRASONIC["AUTONOMOUS_FORWARD_STOP_ENABLED"] = False

        response = self.client.get(
            "/drive", params={"x": 20, "y": 30, "source": "nav2"}
        )

        self.assertEqual(response.json(), {"status": "OK"})
        self.assertEqual(self.motor.drive_calls[0][:2], (20, 30))


if __name__ == "__main__":
    unittest.main()
