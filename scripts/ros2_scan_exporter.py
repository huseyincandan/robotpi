#!/usr/bin/env python3
import argparse
import json
import math
import os
import tempfile
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import LaserScan


def atomic_write_bytes(path, payload):
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-scan-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


class Ros2ScanExporter(Node):

    def __init__(self, args):
        super().__init__("robotpi_ros2_scan_exporter")

        self.output_scan = args.output_scan
        self.min_valid_cm = max(0.0, float(args.min_valid_cm))
        self.max_valid_cm = max(self.min_valid_cm + 1.0, float(args.max_valid_cm))
        self.sector_deg = max(2.0, min(120.0, float(args.sector_deg)))
        self.latest = None

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
            reliability=ReliabilityPolicy.BEST_EFFORT
        )

        self.create_subscription(LaserScan, args.scan_topic, self._on_scan, qos)

        interval = 1.0 / max(1.0, float(args.rate))
        self.create_timer(interval, self._flush)

        self.get_logger().info(
            f"ros2 scan exporter started topic={args.scan_topic}"
        )

    def _sector_min(self, points, center_deg, half_sector):
        minimum = None

        for angle_deg, distance_cm in points:
            diff = (float(angle_deg) - center_deg + 540.0) % 360.0 - 180.0

            if abs(diff) > half_sector:
                continue

            if minimum is None or distance_cm < minimum:
                minimum = float(distance_cm)

        return minimum

    def _on_scan(self, msg):
        angle_min = float(msg.angle_min)
        angle_increment = float(msg.angle_increment)

        points = []

        for idx, distance_m in enumerate(msg.ranges):
            distance = float(distance_m)

            if not math.isfinite(distance) or distance <= 0.0:
                continue

            distance_cm = distance * 100.0

            if distance_cm < self.min_valid_cm or distance_cm > self.max_valid_cm:
                continue

            angle_rad = angle_min + (idx * angle_increment)
            angle_deg = math.degrees(angle_rad) % 360.0
            points.append((round(angle_deg, 3), round(distance_cm, 2)))

        half_sector = self.sector_deg / 2.0
        front_cm = self._sector_min(points, 0.0, half_sector)
        left_cm = self._sector_min(points, 90.0, half_sector)
        right_cm = self._sector_min(points, 270.0, half_sector)

        self.latest = {
            "front_cm": front_cm,
            "left_cm": left_cm,
            "right_cm": right_cm,
            "scan_points": points,
            "timestamp": time.monotonic(),
            "updated_at": time.time()
        }

    def _flush(self):
        if self.latest is None:
            return

        encoded = (json.dumps(self.latest, ensure_ascii=True) + "\n").encode("utf-8")
        atomic_write_bytes(self.output_scan, encoded)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-topic", default="/scan")
    parser.add_argument("--rate", type=float, default=8.0)
    parser.add_argument("--min-valid-cm", type=float, default=12.0)
    parser.add_argument("--max-valid-cm", type=float, default=550.0)
    parser.add_argument("--sector-deg", type=float, default=30.0)
    parser.add_argument("--output-scan", required=True)
    return parser.parse_args()


def main():
    args = parse_args()

    output_dir = os.path.dirname(args.output_scan) or "."
    os.makedirs(output_dir, exist_ok=True)

    rclpy.init()
    node = Ros2ScanExporter(args)

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
