#!/usr/bin/env python3
import argparse
import json
import math
import os
import tempfile
import time

import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from tf2_ros import Buffer
from tf2_ros import TransformException
from tf2_ros import TransformListener


def quaternion_to_yaw(qx, qy, qz, qw):
    siny_cosp = 2.0 * ((qw * qz) + (qx * qy))
    cosy_cosp = 1.0 - 2.0 * ((qy * qy) + (qz * qz))
    return math.atan2(siny_cosp, cosy_cosp)


def atomic_write_bytes(path, payload):
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-map-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def occupancy_to_pgm(grid):
    width = int(grid.info.width)
    height = int(grid.info.height)

    if width <= 0 or height <= 0:
        return None

    data = list(grid.data)
    if len(data) != width * height:
        return None

    pixels = bytearray(width * height)

    for y in range(height):
        src_row = y * width
        dst_row = (height - 1 - y) * width

        for x in range(width):
            occ = int(data[src_row + x])

            if occ < 0:
                value = 205
            else:
                occ = max(0, min(100, occ))
                value = int(round(255.0 - (occ * 2.55)))

            pixels[dst_row + x] = value

    header = f"P5\n{width} {height}\n255\n".encode("ascii")
    return header + bytes(pixels)


class Ros2SlamExporter(Node):

    def __init__(self, args):
        super().__init__("robotpi_ros2_slam_exporter")

        self.output_pgm = args.output_pgm
        self.output_pose = args.output_pose
        self.output_meta = args.output_meta
        self.map_frame = args.map_frame
        self.base_frame = args.base_frame
        self.latest_map = None
        self.latest_pose = None
        self.latest_meta = None
        self.last_saved_map_stamp = None
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        map_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL
        )

        self.create_subscription(OccupancyGrid, args.map_topic, self._on_map, map_qos)

        interval = 1.0 / max(0.5, float(args.rate))
        self.create_timer(interval, self._flush)

        self.get_logger().info(
            f"ros2 slam exporter started map={args.map_topic} tf={args.tf_topic}"
        )

    def _on_map(self, msg):
        self.latest_map = msg
        info = msg.info
        origin = info.origin.position
        self.latest_meta = {
            "frame": str(msg.header.frame_id or self.map_frame),
            "width": int(info.width),
            "height": int(info.height),
            "resolution": float(info.resolution),
            "origin": {
                "x": float(origin.x),
                "y": float(origin.y)
            },
            "updated_at": time.time()
        }

    def _update_pose_from_tf(self):
        try:
            transform_stamped = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.base_frame,
                Time()
            )
        except TransformException:
            return

        header = transform_stamped.header
        t = transform_stamped.transform.translation
        r = transform_stamped.transform.rotation

        self.latest_pose = {
            "frame": self.map_frame,
            "child_frame": self.base_frame,
            "x": float(t.x),
            "y": float(t.y),
            "yaw_rad": float(quaternion_to_yaw(r.x, r.y, r.z, r.w)),
            "stamp_sec": int(header.stamp.sec),
            "stamp_nanosec": int(header.stamp.nanosec),
            "updated_at": time.time()
        }

    def _flush(self):
        self._update_pose_from_tf()

        if self.latest_map is not None:
            stamp = (
                int(self.latest_map.header.stamp.sec),
                int(self.latest_map.header.stamp.nanosec)
            )

            if stamp != self.last_saved_map_stamp:
                payload = occupancy_to_pgm(self.latest_map)

                if payload is not None:
                    atomic_write_bytes(self.output_pgm, payload)
                    self.last_saved_map_stamp = stamp

        if self.latest_pose is not None:
            encoded = (json.dumps(self.latest_pose, ensure_ascii=True) + "\n").encode("utf-8")
            atomic_write_bytes(self.output_pose, encoded)

        if self.latest_meta is not None:
            encoded = (json.dumps(self.latest_meta, ensure_ascii=True) + "\n").encode("utf-8")
            atomic_write_bytes(self.output_meta, encoded)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-topic", default="/map")
    parser.add_argument("--tf-topic", default="/tf")
    parser.add_argument("--map-frame", default="map")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--rate", type=float, default=3.0)
    parser.add_argument("--output-pgm", required=True)
    parser.add_argument("--output-pose", required=True)
    parser.add_argument("--output-meta", required=True)
    return parser.parse_args()


def main():
    args = parse_args()

    output_pgm_dir = os.path.dirname(args.output_pgm) or "."
    output_pose_dir = os.path.dirname(args.output_pose) or "."
    output_meta_dir = os.path.dirname(args.output_meta) or "."
    os.makedirs(output_pgm_dir, exist_ok=True)
    os.makedirs(output_pose_dir, exist_ok=True)
    os.makedirs(output_meta_dir, exist_ok=True)

    rclpy.init()
    node = Ros2SlamExporter(args)

    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
