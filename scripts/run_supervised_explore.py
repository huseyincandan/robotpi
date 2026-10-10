#!/usr/bin/env python3
"""Run a bounded exploration trial with live clearance checks and a ROS bag.

Invoke after sourcing the ROS 2 environment while the app and Nav2 are running.
The finalizer always stops exploration, motors, and Nav2.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request


BASE = "http://127.0.0.1:5000"
TOPICS = [
    "/scan", "/map", "/plan", "/received_global_plan", "/cmd_vel_nav",
    "/cmd_vel_smoothed", "/cmd_vel", "/odom", "/odom_raw", "/tf", "/tf_static",
    "/global_costmap/costmap_raw", "/local_costmap/costmap_raw",
]


def request(path, method="GET", timeout=6):
    with urllib.request.urlopen(
        urllib.request.Request(BASE + path, method=method), timeout=timeout
    ) as response:
        return json.load(response)


def snapshot():
    return {
        "nav": request("/nav2/status"),
        "motor": request("/motor/status"),
        "lidar": request("/lidar/readings"),
        "battery": request("/battery/status"),
    }


def unsafe(state, front_abort_cm, min_clearance_cm):
    motor, lidar, battery = state["motor"], state["lidar"], state["battery"]
    if motor.get("power_fault") or motor.get("sensor_fault"):
        return "motor_or_sensor_fault"
    if battery.get("status") != "OK" or battery.get("bus_voltage", 0) < 10.9:
        return "battery"
    distances = [lidar.get(key) for key in ("front_cm", "left_cm", "back_cm", "right_cm")]
    if any(value is None or value < min_clearance_cm for value in distances):
        return "clearance_under_limit"
    if lidar["front_cm"] < front_abort_cm:
        return "front_clearance"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=25.0)
    parser.add_argument("--front-abort-cm", type=float, default=32.0)
    parser.add_argument("--min-clearance-cm", type=float, default=25.0)
    args = parser.parse_args()
    if not 0 < args.duration <= 120:
        parser.error("--duration must be 0..120 seconds")
    if not 0 < args.min_clearance_cm <= args.front_abort_cm:
        parser.error("--min-clearance-cm must be positive and no greater than --front-abort-cm")

    initial = snapshot()
    if not initial["nav"].get("nav2_running") or initial["nav"].get("explore_running"):
        raise RuntimeError("Nav2 must be running with exploration stopped")
    reason = unsafe(initial, args.front_abort_cm, args.min_clearance_cm)
    if reason:
        raise RuntimeError(f"Unsafe preflight: {reason}: {initial}")

    bag = Path("logs") / ("nav2-supervised-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    bag.parent.mkdir(exist_ok=True)
    with open(str(bag) + ".record.log", "w") as log:
        recorder = subprocess.Popen(
            ["ros2", "bag", "record", "--disable-keyboard-controls", "-o", str(bag), *TOPICS],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        print("BAG", bag, flush=True)
        reason = "duration"
        active_since = None
        try:
            # Explore startup can take 15-20 s. HTTP call returns only after
            # the process starts, so give it its own bounded timeout.
            started = request("/explore/start", "POST", 40)
            print("START", started, flush=True)
            if started.get("status") != "OK":
                reason = "start_failed"
                return
            deadline = time.monotonic() + args.duration + 10
            while time.monotonic() < deadline:
                state = snapshot()
                print("CHECK", json.dumps({
                    "time": round(time.monotonic(), 1),
                    "explore": state["nav"].get("explore_reason"),
                    "motor": [state["motor"].get("current_x"), state["motor"].get("current_y")],
                    "lidar": state["lidar"],
                    "voltage": state["battery"].get("bus_voltage"),
                }), flush=True)
                reason = unsafe(state, args.front_abort_cm, args.min_clearance_cm)
                if reason:
                    break
                if state["nav"].get("explore_active") and active_since is None:
                    active_since = time.monotonic()
                if active_since is not None and time.monotonic() - active_since >= args.duration:
                    reason = "duration"
                    break
                time.sleep(0.5)
            else:
                reason = "startup_timeout"
        finally:
            print("STOP_REASON", reason, flush=True)
            for path in ("/explore/stop", "/motor/stop", "/nav2/stop"):
                try:
                    print("STOP", path, request(path, "POST", 20), flush=True)
                except Exception as exc:
                    print("STOP_ERROR", path, repr(exc), flush=True)
            os.killpg(recorder.pid, signal.SIGINT)
            try:
                recorder.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(recorder.pid, signal.SIGTERM)
                recorder.wait(timeout=5)
            print("FINAL", snapshot()["nav"], flush=True)


if __name__ == "__main__":
    main()
