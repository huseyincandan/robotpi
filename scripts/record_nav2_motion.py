#!/usr/bin/env python3
"""Record Nav2 velocity requests, encoder odometry, and app motor status."""

import argparse
import csv
from datetime import datetime
import json
import math
import threading
import time
from pathlib import Path
import urllib.error
import urllib.request

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from nav2_msgs.msg import Costmap
from rclpy.node import Node
from geometry_msgs.msg import PolygonStamped


class MotionRecorder(Node):
    def __init__(self, args, writer, csv_file, lock):
        super().__init__("robotpi_nav2_motion_recorder")
        self.args = args
        self.writer = writer
        self.csv_file = csv_file
        self.lock = lock
        self.started = time.monotonic()
        self.sequence = 0
        self.latest_cmd = (0.0, 0.0)
        self.latest_odom = (0.0, 0.0)
        self.latest_motor = {}
        self.latest_costmap = None
        self.latest_footprint = None
        self._stop_event = threading.Event()

        self.create_subscription(Twist, args.cmd_vel_topic, self.on_cmd_vel, 10)
        self.create_subscription(Odometry, args.odom_topic, self.on_odom, 10)
        self.create_subscription(Costmap, args.costmap_topic, self.on_costmap, 10)
        self.create_subscription(
            PolygonStamped, args.footprint_topic, self.on_footprint, 10
        )
        self.motor_thread = threading.Thread(target=self.poll_motor, daemon=True)
        self.motor_thread.start()
        self.duration_timer = self.create_timer(0.2, self.check_duration)
        self.costmap_timer = self.create_timer(1.0, self.record_costmap_summary)

    def write_row(self, event, **fields):
        self.sequence += 1
        row = {
            "unix_time": f"{time.time():.6f}",
            "elapsed_s": f"{time.monotonic() - self.started:.3f}",
            "event": event,
            "seq": self.sequence,
            "cmd_vx": self.latest_cmd[0],
            "cmd_wz": self.latest_cmd[1],
            "odom_vx": self.latest_odom[0],
            "odom_wz": self.latest_odom[1],
        }
        row.update(fields)
        with self.lock:
            self.writer.writerow(row)
            self.csv_file.flush()

    def on_cmd_vel(self, msg):
        self.latest_cmd = (float(msg.linear.x), float(msg.angular.z))
        self.write_row("cmd_vel")

    def on_odom(self, msg):
        self.latest_odom = (
            float(msg.twist.twist.linear.x),
            float(msg.twist.twist.angular.z),
        )
        self.write_row("odom_raw")

    def on_costmap(self, msg):
        self.latest_costmap = msg

    def on_footprint(self, msg):
        self.latest_footprint = msg

    @staticmethod
    def point_in_polygon(x, y, polygon):
        inside = False
        j = len(polygon) - 1
        for i, (xi, yi) in enumerate(polygon):
            xj, yj = polygon[j]
            if ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            ):
                inside = not inside
            j = i
        return inside

    def record_costmap_summary(self):
        cm = self.latest_costmap
        fp = self.latest_footprint
        if cm is None or fp is None:
            self.write_row(
                "costmap_waiting",
                error=f"costmap={cm is not None}, footprint={fp is not None}",
            )
            return
        if cm.header.frame_id != fp.header.frame_id:
            self.write_row(
                "costmap_frame_mismatch",
                error=f"{cm.header.frame_id} != {fp.header.frame_id}",
            )
            return

        meta = cm.metadata
        res = float(meta.resolution)
        width, height = int(meta.size_x), int(meta.size_y)
        data = cm.data
        polygon = [(p.x, p.y) for p in fp.polygon.points]
        if res <= 0 or len(data) != width * height or len(polygon) < 3:
            self.write_row("costmap_invalid")
            return

        ox = float(meta.origin.position.x)
        oy = float(meta.origin.position.y)
        # Nav2 publishes this polygon already transformed into the costmap
        # frame (the diagnostic helper uses these coordinates directly).
        world_polygon = polygon
        cx = sum(x for x, _ in world_polygon) / len(world_polygon)
        cy = sum(y for _, y in world_polygon) / len(world_polygon)
        front_mid_x = (world_polygon[0][0] + world_polygon[1][0]) / 2.0
        front_mid_y = (world_polygon[0][1] + world_polygon[1][1]) / 2.0
        yaw = math.atan2(front_mid_y - cy, front_mid_x - cx)
        yaw_cos, yaw_sin = math.cos(yaw), math.sin(yaw)
        min_x = min(p[0] for p in world_polygon) - 0.30
        max_x = max(p[0] for p in world_polygon) + 0.30
        min_y = min(p[1] for p in world_polygon) - 0.30
        max_y = max(p[1] for p in world_polygon) + 0.30
        i0 = max(0, int((min_x - ox) / res))
        i1 = min(width - 1, int((max_x - ox) / res))
        j0 = max(0, int((min_y - oy) / res))
        j1 = min(height - 1, int((max_y - oy) / res))

        footprint_values = []
        nearby_values = []
        nearby_lethal_by_direction = {
            "front": 0, "back": 0, "left": 0, "right": 0
        }
        nearest_lethal_distance = None
        nearest_lethal_bearing = None
        for j in range(j0, j1 + 1):
            wy = oy + (j + 0.5) * res
            for i in range(i0, i1 + 1):
                wx = ox + (i + 0.5) * res
                value = int(data[j * width + i])
                if self.point_in_polygon(wx, wy, world_polygon):
                    footprint_values.append(value)
                else:
                    dx, dy = wx - cx, wy - cy
                    distance = math.hypot(dx, dy)
                    if distance <= 0.30:
                        nearby_values.append(value)
                    if value >= 253 and distance <= 0.50:
                        local_x = dx * yaw_cos + dy * yaw_sin
                        local_y = -dx * yaw_sin + dy * yaw_cos
                        direction = (
                            "front" if abs(local_x) >= abs(local_y) and local_x >= 0
                            else "back" if abs(local_x) >= abs(local_y)
                            else "left" if local_y >= 0
                            else "right"
                        )
                        nearby_lethal_by_direction[direction] += 1
                        if nearest_lethal_distance is None or distance < nearest_lethal_distance:
                            nearest_lethal_distance = distance
                            nearest_lethal_bearing = math.degrees(
                                math.atan2(local_y, local_x)
                            )

        def counts(values):
            return {
                "cells": len(values),
                "unknown": sum(v == 255 or v < 0 for v in values),
                "high_200_plus": sum(v >= 200 for v in values),
                "lethal_253_plus": sum(v >= 253 for v in values),
                "max_cost": max(values, default=-1),
            }

        self.write_row(
            "costmap",
            costmap_frame=cm.header.frame_id,
            costmap_stamp=f"{cm.header.stamp.sec}.{cm.header.stamp.nanosec:09d}",
            pose_x=f"{cx:.4f}",
            pose_y=f"{cy:.4f}",
            pose_yaw="",
            costmap_resolution=f"{res:.4f}",
            footprint_costs=json.dumps(counts(footprint_values), separators=(",", ":")),
            nearby_costs=json.dumps(counts(nearby_values), separators=(",", ":")),
            lethal_by_direction=json.dumps(
                nearby_lethal_by_direction, separators=(",", ":")
            ),
            nearest_lethal_m=(
                "" if nearest_lethal_distance is None
                else f"{nearest_lethal_distance:.3f}"
            ),
            nearest_lethal_bearing_deg=(
                "" if nearest_lethal_bearing is None
                else f"{nearest_lethal_bearing:.1f}"
            ),
        )

    def poll_motor(self):
        endpoint = self.args.motor_url.rstrip("/") + "/motor/status"
        while not self._stop_event.is_set():
            try:
                request = urllib.request.Request(endpoint, method="GET")
                with urllib.request.urlopen(request, timeout=0.35) as response:
                    payload = json.loads(response.read())
                if payload.get("status") == "OK":
                    self.latest_motor = payload
                    self.write_row(
                        "motor_status",
                        motor_x=payload.get("current_x"),
                        motor_y=payload.get("current_y"),
                        requested_x=payload.get("last_requested_x"),
                        requested_y=payload.get("last_requested_y"),
                        blocked=payload.get("blocked"),
                        block_reason=payload.get("last_block_reason"),
                        obstacle_cm=payload.get("last_obstacle_distance"),
                        power_fault=payload.get("power_fault"),
                        sensor_fault=payload.get("sensor_fault"),
                    )
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                self.write_row("motor_status_error", error=str(exc))
            self._stop_event.wait(self.args.poll_interval)

    def check_duration(self):
        if time.monotonic() - self.started >= self.args.duration:
            self.get_logger().info("capture duration reached; robot control unchanged")
            self._stop_event.set()
            rclpy.shutdown()

    def close(self):
        self._stop_event.set()
        if self.motor_thread.is_alive():
            self.motor_thread.join(timeout=0.6)


def main():
    parser = argparse.ArgumentParser(
        description="Capture /cmd_vel, /odom_raw, and /motor/status without controlling the robot"
    )
    parser.add_argument("--duration", type=float, default=45.0)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--motor-url", default="http://127.0.0.1:5000")
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel")
    parser.add_argument("--odom-topic", default="/odom_raw")
    parser.add_argument("--costmap-topic", default="/local_costmap/costmap_raw")
    parser.add_argument(
        "--footprint-topic", default="/local_costmap/published_footprint"
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if args.duration <= 0 or args.poll_interval < 0.1:
        parser.error("duration must be positive and poll interval at least 0.1s")

    if args.out:
        output = Path(args.out)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = Path("logs") / f"nav2-motion-{stamp}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)

    columns = [
        "unix_time", "elapsed_s", "event", "seq", "cmd_vx", "cmd_wz",
        "odom_vx", "odom_wz", "motor_x", "motor_y", "requested_x",
        "requested_y", "blocked", "block_reason", "obstacle_cm",
        "power_fault", "sensor_fault", "error",
        "costmap_frame", "costmap_stamp", "pose_x", "pose_y", "pose_yaw",
        "costmap_resolution", "footprint_costs", "nearby_costs",
        "lethal_by_direction", "nearest_lethal_m", "nearest_lethal_bearing_deg",
    ]
    lock = threading.Lock()
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        csv_file.flush()

        rclpy.init()
        node = MotionRecorder(args, writer, csv_file, lock)
        print(f"Recording {args.cmd_vel_topic}, {args.odom_topic}, and motor status")
        print(f"Output: {output.resolve()}  duration: {args.duration:.1f}s")
        try:
            rclpy.spin(node)
        except KeyboardInterrupt:
            print("Capture interrupted; robot control unchanged")
        finally:
            node.close()
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == "__main__":
    main()
