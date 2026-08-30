#!/usr/bin/env python3
import argparse
import json
import math
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import rclpy
from geometry_msgs.msg import TransformStamped
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Range
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster


class CmdVelBridge(Node):

    def __init__(self, args):

        super().__init__("robotpi_cmdvel_bridge")

        self.app_base_url = args.app_base_url.rstrip("/")
        self.drive_endpoint = self.app_base_url + "/drive"
        self.stop_endpoint = self.app_base_url + "/stop"
        self.imu_endpoint = self.app_base_url + "/imu/motion"
        self.ultrasonic_endpoint = self.app_base_url + "/ultrasonic/readings"
        self.ultrasonic_rate_hz = max(2.0, float(args.ultrasonic_rate_hz))
        self.ultrasonic_x_offset = max(0.0, float(args.ultrasonic_x_offset))

        self.max_linear = max(0.01, float(args.max_linear_x))
        self.max_angular = max(0.01, float(args.max_angular_z))
        self.max_drive = max(10.0, float(args.max_drive_percent))
        self.max_turn = max(10.0, float(args.max_turn_percent))
        self.turn_hold = max(10.0, min(self.max_turn, float(args.turn_hold_percent)))
        self.turn_breakaway_seconds = max(0.0, float(args.turn_breakaway_seconds))
        self.angular_slew_rate = max(0.05, float(args.angular_slew_rate))
        self.min_linear_scale_at_max_turn = max(
            0.0,
            min(1.0, float(args.min_linear_scale_at_max_turn))
        )
        self.command_timeout = max(0.05, float(args.command_timeout_sec))

        self.odom_frame = str(args.odom_frame)
        self.base_frame = str(args.base_frame)
        self.laser_frame = str(args.laser_frame)
        self.laser_x_offset = float(args.laser_x_offset)

        self.current_linear = 0.0
        self.current_angular = 0.0
        self.target_angular = 0.0
        self.last_cmd_time = self.get_clock().now()
        self._last_drive_monotonic = time.monotonic()
        self._turn_breakaway_started = None
        self._turn_breakaway_direction = 0

        self.odom_vx_variance = max(1e-6, float(args.odom_vx_variance))
        self.odom_vyaw_variance = max(1e-6, float(args.odom_vyaw_variance))

        self.imu_max_age_sec = max(0.1, float(args.imu_max_age_sec))
        self._imu_last_update_monotonic = None

        self.lidar_odom_correction_enabled = bool(args.lidar_odom_correction_enabled)
        self.lidar_odom_slip_scale = max(0.0, min(1.0, float(args.lidar_odom_slip_scale)))
        self._lidar_motion_verified = None
        self._lidar_last_update_monotonic = None

        self.motor_odom_source_enabled = bool(args.motor_odom_source_enabled)
        self._motor_x_percent = 0.0
        self._motor_y_percent = 0.0
        self._motor_last_update_monotonic = None

        self.subscription = self.create_subscription(
            Twist,
            args.cmd_vel_topic,
            self._on_cmd_vel,
            10
        )
        self.ultrasonic_pub = self.create_publisher(
            Range,
            args.ultrasonic_topic,
            10
        )

        self.odom_pub = self.create_publisher(
            Odometry,
            args.odom_topic,
            10
        )
        self.static_tf_broadcaster = StaticTransformBroadcaster(self)
        self._publish_laser_transform()

        self.drive_timer = self.create_timer(
            max(0.02, 1.0 / max(5.0, float(args.drive_rate_hz))),
            self._drive_loop
        )

        self.odom_timer = self.create_timer(
            max(0.02, 1.0 / max(5.0, float(args.odom_rate_hz))),
            self._odom_loop
        )

        # Lidar-based odom slip correction and the motor's actual drive
        # percentage are both read from the same /imu/motion HTTP response
        # (gyro_z itself is now polled independently by ros2_imu_bridge.py
        # and fused by robot_localization's EKF instead of here).
        if self.lidar_odom_correction_enabled or self.motor_odom_source_enabled:
            self.imu_timer = self.create_timer(
                max(0.02, 1.0 / max(5.0, float(args.imu_rate_hz))),
                self._imu_loop
            )

        self.ultrasonic_timer = self.create_timer(
            1.0 / self.ultrasonic_rate_hz,
            self._ultrasonic_loop
        )

        self.get_logger().info(
            "cmd_vel bridge started "
            f"cmd_vel={args.cmd_vel_topic} odom={args.odom_topic} "
            f"drive={self.drive_endpoint}"
        )

    def _imu_loop(self):

        request = urllib.request.Request(
            url=self.imu_endpoint,
            method="GET"
        )

        try:
            with urllib.request.urlopen(request, timeout=0.2) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError):
            # Keep last known gyro reading; _odom_loop falls back to commanded
            # angular velocity once it goes stale (imu_max_age_sec).
            return

        if payload.get("status") != "OK":
            return

        self._imu_last_update_monotonic = time.monotonic()

        # Same HTTP round-trip also carries the motor's lidar omnidirectional
        # motion-signature verdict (True/False/None). False means the lidar
        # explicitly saw too little change for the commanded drive (likely
        # wheel slip); None means no verdict is available yet.
        if "lidar_motion_verified" in payload:
            self._lidar_motion_verified = payload.get("lidar_motion_verified")
            self._lidar_last_update_monotonic = time.monotonic()

        # Motorun o an gercekten uyguladigi y-yuzdesi: kaynak nav2 cmd_vel de
        # olsa joystick/sesli surus de olsa gercek hareketi bu yansitir, oysa
        # current_linear sadece /cmd_vel mesajlariyla guncellenir.
        if "motor_y_percent" in payload:
            self._motor_x_percent = float(payload.get("motor_x_percent", 0.0))
            self._motor_y_percent = float(payload.get("motor_y_percent", 0.0))
            self._motor_last_update_monotonic = time.monotonic()

    def _ultrasonic_loop(self):

        request = urllib.request.Request(
            url=self.ultrasonic_endpoint,
            method="GET"
        )

        try:
            with urllib.request.urlopen(request, timeout=0.25) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, socket.timeout, ValueError):
            return

        if payload.get("status") != "OK":
            return

        if bool(payload.get("nearest_cluster_confirmed", False)):
            distance_cm = payload.get("nearest_cluster_distance_cm")
        elif bool(payload.get("stable", False)):
            distance_cm = payload.get("distance_cm")
        else:
            return

        if distance_cm is None:
            return

        measured_range = (
            float(distance_cm) / 100.0
            + self.ultrasonic_x_offset
        )
        msg = Range()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.base_frame
        msg.radiation_type = Range.ULTRASOUND
        msg.field_of_view = math.radians(24.0)
        msg.min_range = 0.02
        msg.max_range = 4.2
        # RangeSensorLayer's variable-range handler rejects range > max_range
        # outright (no clearing), so clamp to max_range instead of inf - with
        # clear_on_max_reading enabled in nav2_params.yaml, that clamped
        # max-range reading is what triggers clearing of the free space ahead.
        msg.range = min(measured_range, msg.max_range)
        self.ultrasonic_pub.publish(msg)

    def _publish_laser_transform(self):

        if self.base_frame == self.laser_frame:
            return

        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = self.base_frame
        transform.child_frame_id = self.laser_frame
        transform.transform.translation.x = self.laser_x_offset
        transform.transform.translation.y = 0.0
        transform.transform.translation.z = 0.0
        transform.transform.rotation.x = 0.0
        transform.transform.rotation.y = 0.0
        transform.transform.rotation.z = 0.0
        transform.transform.rotation.w = 1.0

        self.static_tf_broadcaster.sendTransform(transform)
        self.get_logger().info(
            f"published static tf {self.base_frame}->{self.laser_frame} "
            f"x={self.laser_x_offset:.3f}"
        )

    def _on_cmd_vel(self, msg):

        self.current_linear = float(msg.linear.x)
        self.target_angular = float(msg.angular.z)
        self.last_cmd_time = self.get_clock().now()

    def _drive_loop(self):

        now = self.get_clock().now()
        age_sec = (now - self.last_cmd_time).nanoseconds / 1e9

        if age_sec > self.command_timeout:
            self.current_linear = 0.0
            self.target_angular = 0.0

        now_monotonic = time.monotonic()
        elapsed = min(0.2, max(0.0, now_monotonic - self._last_drive_monotonic))
        self._last_drive_monotonic = now_monotonic
        max_angular_step = self.angular_slew_rate * elapsed
        angular_delta = max(
            -max_angular_step,
            min(max_angular_step, self.target_angular - self.current_angular)
        )
        self.current_angular += angular_delta

        x_percent = max(
            -self.max_turn,
            min(self.max_turn, (self.current_angular / self.max_angular) * self.max_turn)
        )

        turn_direction = 1 if x_percent > 0 else -1 if x_percent < 0 else 0
        if abs(x_percent) > self.turn_hold:
            if turn_direction != self._turn_breakaway_direction:
                self._turn_breakaway_direction = turn_direction
                self._turn_breakaway_started = now_monotonic
            elif self._turn_breakaway_started is None:
                self._turn_breakaway_started = now_monotonic

            if (
                now_monotonic - self._turn_breakaway_started
                >= self.turn_breakaway_seconds
            ):
                x_percent = turn_direction * self.turn_hold
        else:
            self._turn_breakaway_started = None
            self._turn_breakaway_direction = turn_direction

        y_percent = max(
            -self.max_drive,
            min(self.max_drive, (self.current_linear / self.max_linear) * self.max_drive)
        )

        turn_ratio = min(1.0, abs(self.current_angular) / self.max_angular)
        linear_scale = 1.0 - (
            (1.0 - self.min_linear_scale_at_max_turn) * turn_ratio
        )
        y_percent *= linear_scale

        self._send_drive(x_percent, y_percent)

    def _send_drive(self, x_percent, y_percent):

        query = urllib.parse.urlencode({
            "x": f"{float(x_percent):.4f}",
            "y": f"{float(y_percent):.4f}",
            "source": "nav2"
        })

        url = f"{self.drive_endpoint}?{query}"

        request = urllib.request.Request(
            url=url,
            method="GET"
        )

        try:
            with urllib.request.urlopen(request, timeout=0.35) as response:
                _ = response.read()
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            # Keep bridge loop quiet on transient HTTP hiccups.
            pass

    def _odom_loop(self):

        # This publishes a raw velocity-only source (/odom_raw) for
        # robot_localization's EKF to fuse - no local pose integration or
        # odom->base_link TF here anymore (the EKF owns both, see
        # config/ekf.yaml and services/ros2_navigation.py).
        v = self.current_linear
        w = self.current_angular

        if (
            self.motor_odom_source_enabled
            and self._motor_last_update_monotonic is not None
            and (time.monotonic() - self._motor_last_update_monotonic) <= self.imu_max_age_sec
        ):
            # Joystick/sesli surus /cmd_vel'e hic mesaj yayinlamaz, bu yuzden
            # current_linear boyle durumlarda hep sifirda kalirdi; motorun
            # gercek y-yuzdesinden turetilen hiz her surus kaynagi icin dogru.
            v = (self._motor_y_percent / self.max_drive) * self.max_linear

        if (
            self.lidar_odom_correction_enabled
            and abs(v) > 1e-6
            and self._lidar_motion_verified is False
            and self._lidar_last_update_monotonic is not None
            and (time.monotonic() - self._lidar_last_update_monotonic) <= self.imu_max_age_sec
        ):
            # No wheel encoders means translation is otherwise fully open-loop.
            # The lidar explicitly reports too little motion for the commanded
            # drive (wheel slip on a slippery floor, or a stall) so scale the
            # velocity used for odom down accordingly. This makes the EKF's
            # (and therefore Nav2's) pose estimate reflect reality instead of
            # the ideal commanded motion, so it naturally keeps driving toward
            # the goal (instead of believing it already arrived) until the
            # lidar confirms real progress again.
            v *= self.lidar_odom_slip_scale

        odom = Odometry()
        odom.header.stamp = self.get_clock().now().to_msg()
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame

        # Pose is intentionally left at identity/zero - odom0_config in
        # config/ekf.yaml only fuses twist.linear.x from this source, so the
        # EKF does the one authoritative position/yaw integration itself.
        odom.pose.pose.orientation.w = 1.0

        odom.twist.twist.linear.x = float(v)
        odom.twist.twist.angular.z = float(w)
        # Row-major 6x6 covariance; only the fused field (linear.x, index 0)
        # needs a realistic value - there are no wheel encoders, so this is
        # an open-loop estimate and shouldn't be over-trusted by the EKF.
        odom.twist.covariance[0] = self.odom_vx_variance
        odom.twist.covariance[35] = self.odom_vyaw_variance

        self.odom_pub.publish(odom)

    def stop_robot(self):

        request = urllib.request.Request(
            url=self.stop_endpoint,
            method="GET"
        )

        try:
            with urllib.request.urlopen(request, timeout=0.5) as response:
                _ = response.read()
        except urllib.error.URLError:
            pass

def parse_args():

    parser = argparse.ArgumentParser(description="Bridge ROS2 cmd_vel to RobotPi HTTP motor drive")
    parser.add_argument("--app-base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--cmd-vel-topic", default="/cmd_vel")
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--base-frame", default="base_link")
    parser.add_argument("--laser-frame", default="laser")
    parser.add_argument("--laser-x-offset", type=float, default=-0.085)
    parser.add_argument("--odom-frame", default="odom")
    parser.add_argument("--max-linear-x", type=float, default=0.24)
    parser.add_argument("--max-angular-z", type=float, default=1.0)
    parser.add_argument("--max-drive-percent", type=float, default=38.0)
    parser.add_argument("--max-turn-percent", type=float, default=46.0)
    parser.add_argument("--turn-hold-percent", type=float, default=52.0)
    parser.add_argument("--turn-breakaway-seconds", type=float, default=0.30)
    parser.add_argument("--angular-slew-rate", type=float, default=0.45)
    parser.add_argument("--min-linear-scale-at-max-turn", type=float, default=0.25)
    parser.add_argument("--command-timeout-sec", type=float, default=0.45)
    parser.add_argument("--drive-rate-hz", type=float, default=14.0)
    parser.add_argument("--odom-rate-hz", type=float, default=20.0)
    parser.add_argument("--odom-vx-variance", type=float, default=0.01)
    parser.add_argument("--odom-vyaw-variance", type=float, default=0.05)
    parser.add_argument("--imu-rate-hz", type=float, default=20.0)
    parser.add_argument("--imu-max-age-sec", type=float, default=0.5)
    parser.add_argument("--lidar-odom-correction-enabled", type=lambda v: str(v).lower() not in ("0", "false", "no"), default=True)
    parser.add_argument("--lidar-odom-slip-scale", type=float, default=0.35)
    parser.add_argument("--motor-odom-source-enabled", type=lambda v: str(v).lower() not in ("0", "false", "no"), default=True)
    parser.add_argument("--ultrasonic-topic", default="/ultrasonic_range")
    parser.add_argument("--ultrasonic-rate-hz", type=float, default=10.0)
    parser.add_argument("--ultrasonic-x-offset", type=float, default=0.115)
    return parser.parse_args()


def main():

    args = parse_args()

    rclpy.init()
    node = CmdVelBridge(args)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_robot()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
