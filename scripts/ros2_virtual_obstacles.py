#!/usr/bin/env python3
"""Publishes operator/IMU-flagged "invisible" obstacles (e.g. low table legs
below the lidar/ultrasonic beam height) into Nav2's costmaps.

Reads a JSON file (written by services/motor.py whenever the IMU detects a
stuck/impact event that neither the lidar nor the ultrasonic corroborate) and
republishes it as a PointCloud2 in the map frame at a steady rate. Nav2's
ObstacleLayer is configured (see config/nav2_params.yaml) to mark from this
topic without clearing it, so these points survive normal costmap clears and
rolling-window resets, and both local and global costmaps keep avoiding the
exact spot even though no sensor can see the obstacle itself.
"""
import argparse
import json
import math
import os

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2
from std_msgs.msg import Header


class Ros2VirtualObstacles(Node):

    def __init__(self, args):
        super().__init__("robotpi_ros2_virtual_obstacles")

        self.input_file = args.input_file
        self.frame_id = args.frame
        self.ring_radius_m = max(0.0, float(args.ring_radius_m))
        self.ring_points = max(1, int(args.ring_points))
        self.min_hit_count = max(1, int(args.min_hit_count))
        self._last_load_mtime = None
        self._points = []

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL
        )

        self.publisher = self.create_publisher(PointCloud2, args.topic, qos)

        interval = 1.0 / max(0.2, float(args.rate))
        self.create_timer(interval, self._publish)

        self.get_logger().info(
            f"ros2 virtual obstacles started input={self.input_file} "
            f"topic={args.topic} frame={self.frame_id}"
        )

    def _reload_if_changed(self):
        try:
            mtime = os.path.getmtime(self.input_file)
        except OSError:
            if self._last_load_mtime is not None:
                self._last_load_mtime = None
                self._points = []
            return

        if mtime == self._last_load_mtime:
            return

        self._last_load_mtime = mtime

        try:
            with open(self.input_file, "r", encoding="utf-8") as handle:
                entries = json.load(handle)
        except (OSError, ValueError):
            return

        if not isinstance(entries, list):
            return

        points = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            # A single hit can be a false positive; only publish (and thus
            # permanently wall off) a spot once it's been confirmed more
            # than once, since marks here never get cleared by Nav2.
            try:
                hit_count = int(entry.get("hit_count", 1))
            except (TypeError, ValueError):
                hit_count = 1
            if hit_count < self.min_hit_count:
                continue

            try:
                cx = float(entry["x"])
                cy = float(entry["y"])
            except (KeyError, TypeError, ValueError):
                continue

            points.append((cx, cy))

            if self.ring_radius_m > 0.0:
                for i in range(self.ring_points):
                    angle = (2.0 * math.pi) * (float(i) / float(self.ring_points))
                    points.append((
                        cx + self.ring_radius_m * math.cos(angle),
                        cy + self.ring_radius_m * math.sin(angle)
                    ))

        self._points = points

    def _publish(self):
        self._reload_if_changed()

        stamp = self.get_clock().now().to_msg()
        cloud_points = [(x, y, 0.0) for (x, y) in self._points]

        msg_header = Header()
        msg_header.stamp = stamp
        msg_header.frame_id = self.frame_id

        cloud = point_cloud2.create_cloud_xyz32(msg_header, cloud_points)
        self.publisher.publish(cloud)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--topic", default="/virtual_obstacles")
    parser.add_argument("--frame", default="map")
    parser.add_argument("--rate", type=float, default=2.0)
    parser.add_argument("--ring-radius-m", type=float, default=0.06)
    parser.add_argument("--ring-points", type=int, default=10)
    parser.add_argument("--min-hit-count", type=int, default=2)
    return parser.parse_args()


def main():
    args = parse_args()

    rclpy.init()
    node = Ros2VirtualObstacles(args)

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
