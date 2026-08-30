#!/usr/bin/env python3
import argparse
import json
import math
import socket
import urllib.error
import urllib.request

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Imu


class ImuBridge(Node):

    def __init__(self, args):

        super().__init__("robotpi_imu_bridge")

        self.imu_endpoint = args.app_base_url.rstrip("/") + "/imu/motion"
        self.frame_id = str(args.imu_frame)
        self.gyro_sign = float(args.gyro_sign)
        self.stationary_deadband_rad = math.radians(
            max(0.0, float(args.stationary_deadband_dps))
        )
        self.gyro_z_variance = max(1e-6, float(args.gyro_z_variance))

        self.imu_pub = self.create_publisher(Imu, args.imu_topic, 10)

        self.poll_timer = self.create_timer(
            max(0.01, 1.0 / max(5.0, float(args.rate_hz))),
            self._poll
        )

        self.get_logger().info(
            f"imu bridge started topic={args.imu_topic} "
            f"endpoint={self.imu_endpoint} frame={self.frame_id}"
        )

    def _poll(self):

        request = urllib.request.Request(
            url=self.imu_endpoint,
            method="GET"
        )

        try:
            with urllib.request.urlopen(request, timeout=0.2) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError):
            return

        if payload.get("status") != "OK":
            return

        gyro_z_dps = float(payload.get("gyro_z_dps", 0.0))
        gyro_z = self.gyro_sign * math.radians(gyro_z_dps)
        if abs(gyro_z) <= self.stationary_deadband_rad:
            gyro_z = 0.0

        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.frame_id

        # No magnetometer on this MPU6050 - absolute yaw is unobservable, so
        # mark the whole orientation field invalid per sensor_msgs/Imu
        # convention (first covariance element -1) instead of publishing a
        # fake identity quaternion the EKF might otherwise be told to trust.
        msg.orientation_covariance[0] = -1.0

        # Only yaw rate (z) is a real, usable measurement on this chassis;
        # x/y gyro axes are left at 0 with a large (low-trust) covariance
        # rather than the whole-field -1 marker, since z must stay valid.
        msg.angular_velocity.z = gyro_z
        msg.angular_velocity_covariance[0] = 1e6
        msg.angular_velocity_covariance[4] = 1e6
        msg.angular_velocity_covariance[8] = self.gyro_z_variance

        # Linear acceleration isn't read from the HTTP payload/fused by the
        # EKF (config/ekf.yaml's imu0_config leaves ax/ay/az false) - mark
        # the whole field invalid rather than publishing unused zeros.
        msg.linear_acceleration_covariance[0] = -1.0

        self.imu_pub.publish(msg)


def parse_args():

    parser = argparse.ArgumentParser(
        description="Bridge RobotPi IMU HTTP endpoint to sensor_msgs/Imu for robot_localization"
    )
    parser.add_argument("--app-base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--imu-topic", default="/imu/data")
    parser.add_argument("--imu-frame", default="base_link")
    parser.add_argument("--gyro-sign", type=float, default=1.0)
    parser.add_argument("--stationary-deadband-dps", type=float, default=0.5)
    parser.add_argument("--gyro-z-variance", type=float, default=0.02)
    parser.add_argument("--rate-hz", type=float, default=50.0)
    return parser.parse_args()


def main():

    args = parse_args()
    rclpy.init()
    node = ImuBridge(args)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
