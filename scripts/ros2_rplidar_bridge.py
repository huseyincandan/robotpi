#!/usr/bin/env python3
import argparse
import math
import time
import types

import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from sensor_msgs.msg import LaserScan

try:
    from rplidar import RPLidar
except Exception:
    RPLidar = None


class RplidarBridge(Node):

    def __init__(self, args):
        super().__init__("robotpi_rplidar_bridge")

        if RPLidar is None:
            raise RuntimeError("rplidar module is not available")

        self.port = args.serial_port
        self.baudrate = int(args.serial_baudrate)
        self.frame_id = args.frame_id
        self.scan_topic = args.scan_topic
        self.range_min = float(args.range_min)
        self.range_max = float(args.range_max)
        self.reverse_angle = bool(args.reverse_angle)
        self.angle_offset_deg = float(args.angle_offset_deg)
        self.disable_pwm_start = bool(args.disable_pwm_start)
        self.bins = max(180, int(args.bins))
        self.reconnect_seconds = max(0.5, float(args.reconnect_seconds))

        self.publisher = self.create_publisher(LaserScan, self.scan_topic, 10)
        self._lidar = None
        self._last_publish = time.monotonic()

    def _connect(self):
        lidar = RPLidar(self.port, baudrate=self.baudrate, timeout=1)

        if self.disable_pwm_start:
            def _start_motor_no_pwm(lidar_self):
                lidar_self._serial.setDTR(False)
                lidar_self.motor_running = True

            lidar.start_motor = types.MethodType(_start_motor_no_pwm, lidar)

        self._lidar = lidar
        self.get_logger().info(
            f"lidar connected port={self.port} baud={self.baudrate}"
        )

    def _disconnect(self):
        if self._lidar is None:
            return

        try:
            self._lidar.stop()
        except Exception:
            pass

        try:
            self._lidar.stop_motor()
        except Exception:
            pass

        try:
            self._lidar.disconnect()
        except Exception:
            pass

        self._lidar = None

    def _publish_scan(self, scan):
        now = self.get_clock().now()
        now_monotonic = time.monotonic()
        # Startup, reconnect and SLAM reset gaps are not part of one physical
        # revolution. Carrying a multi-second gap into LaserScan would make
        # every ray timestamp invalid and cause costmap/TF message drops.
        scan_time = min(0.15, max(0.02, now_monotonic - self._last_publish))
        self._last_publish = now_monotonic

        ranges = [math.inf] * self.bins
        angle_increment = (2.0 * math.pi) / float(self.bins)

        for (_, angle_deg, distance_mm) in scan:
            distance_m = float(distance_mm) / 1000.0

            if distance_m <= 0.0:
                continue

            if distance_m < self.range_min or distance_m > self.range_max:
                continue

            transformed = float(angle_deg)

            if self.reverse_angle:
                transformed = -transformed

            transformed += self.angle_offset_deg
            normalized = transformed % 360.0
            idx = int((normalized / 360.0) * self.bins)
            if idx >= self.bins:
                idx = self.bins - 1

            current = ranges[idx]
            if math.isinf(current) or distance_m < current:
                ranges[idx] = distance_m

        message = LaserScan()
        # LaserScan timestamps identify the first ray, while iter_scans yields
        # a complete revolution. Stamping it at callback time puts the scan a
        # few milliseconds ahead of the latest odom TF and causes Nav2 to drop
        # otherwise valid scans as future extrapolations.
        tf_lag_seconds = 0.03
        message.header.stamp = (
            now - Duration(seconds=scan_time + tf_lag_seconds)
        ).to_msg()
        message.header.frame_id = self.frame_id
        message.angle_min = 0.0
        message.angle_max = (2.0 * math.pi) - angle_increment
        message.angle_increment = angle_increment
        message.time_increment = scan_time / float(self.bins)

        message.scan_time = scan_time

        message.range_min = self.range_min
        message.range_max = self.range_max
        message.ranges = ranges
        message.intensities = []

        self.publisher.publish(message)

    def spin_forever(self):
        while rclpy.ok():
            try:
                self._connect()

                for scan in self._lidar.iter_scans(max_buf_meas=1200):
                    if not rclpy.ok():
                        break
                    self._publish_scan(scan)

            except Exception as exc:
                self.get_logger().error(f"lidar bridge error: {repr(exc)}")
                time.sleep(self.reconnect_seconds)
            finally:
                self._disconnect()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial-port", default="/dev/ttyUSB0")
    parser.add_argument("--serial-baudrate", type=int, default=460800)
    parser.add_argument("--frame-id", default="laser")
    parser.add_argument("--scan-topic", default="/scan")
    parser.add_argument("--range-min", type=float, default=0.12)
    parser.add_argument("--range-max", type=float, default=8.0)
    parser.add_argument("--bins", type=int, default=360)
    parser.add_argument("--reconnect-seconds", type=float, default=1.5)
    parser.add_argument("--reverse-angle", action="store_true")
    parser.add_argument("--angle-offset-deg", type=float, default=0.0)
    parser.add_argument("--disable-pwm-start", action="store_true")
    parser.add_argument("--enable-pwm-start", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.enable_pwm_start:
        args.disable_pwm_start = False
    elif not args.disable_pwm_start:
        args.disable_pwm_start = True

    rclpy.init()
    bridge = RplidarBridge(args)

    try:
        bridge.spin_forever()
    finally:
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()