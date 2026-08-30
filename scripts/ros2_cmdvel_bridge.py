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
from std_srvs.srv import Trigger
from tf2_ros import TransformBroadcaster
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster


def _yaw_to_quaternion(yaw):
    half = yaw * 0.5
    return (0.0, 0.0, math.sin(half), math.cos(half))


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

        self.pose_x = 0.0
        self.pose_y = 0.0
        self.pose_yaw = 0.0
        self._last_odom_time = self.get_clock().now()

        self.imu_fusion_enabled = bool(args.imu_fusion_enabled)
        self.imu_gyro_sign = float(args.imu_gyro_sign)
        self.imu_stationary_deadband_rad = math.radians(
            max(0.0, float(args.imu_stationary_deadband_dps))
        )
        self.imu_max_age_sec = max(0.1, float(args.imu_max_age_sec))
        self._imu_gyro_z_rad = 0.0
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
        self.tf_broadcaster = TransformBroadcaster(self)
        self.static_tf_broadcaster = StaticTransformBroadcaster(self)
        self._publish_laser_transform()
        self.reset_odom_service = self.create_service(
            Trigger,
            "/robotpi/reset_odom",
            self._reset_odom
        )

        self.drive_timer = self.create_timer(
            max(0.02, 1.0 / max(5.0, float(args.drive_rate_hz))),
            self._drive_loop
        )

        self.odom_timer = self.create_timer(
            max(0.02, 1.0 / max(5.0, float(args.odom_rate_hz))),
            self._odom_loop
        )

        # IMU yaw fusion, lidar-based odom slip correction and the motor's
        # actual drive percentage are all read from the same /imu/motion HTTP
        # response, so any one of these features being enabled is enough to
        # start polling it.
        if self.imu_fusion_enabled or self.lidar_odom_correction_enabled or self.motor_odom_source_enabled:
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
            f"drive={self.drive_endpoint} imu_fusion={self.imu_fusion_enabled}"
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

        gyro_z_dps = float(payload.get("gyro_z_dps", 0.0))
        self._imu_gyro_z_rad = self.imu_gyro_sign * math.radians(gyro_z_dps)
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

    def _reset_odom(self, request, response):

        _ = request
        self.pose_x = 0.0
        self.pose_y = 0.0
        self.pose_yaw = 0.0
        self._last_odom_time = self.get_clock().now()
        response.success = True
        response.message = "odometry reset"
        self.get_logger().info("odometry pose reset to origin")
        return response

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

        now = self.get_clock().now()
        dt = (now - self._last_odom_time).nanoseconds / 1e9
        self._last_odom_time = now

        if dt <= 0.0:
            return

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
            self.imu_fusion_enabled
            and self._imu_last_update_monotonic is not None
            and (time.monotonic() - self._imu_last_update_monotonic) <= self.imu_max_age_sec
        ):
            # Use the real measured yaw rate instead of the commanded one:
            # there are no wheel encoders, so this is the only closed-loop
            # feedback available for heading (translation is still open-loop).
            w = self._imu_gyro_z_rad

            motor_feedback_fresh = (
                self._motor_last_update_monotonic is not None
                and (time.monotonic() - self._motor_last_update_monotonic) <= self.imu_max_age_sec
            )
            robot_commanded_still = (
                motor_feedback_fresh
                and abs(self._motor_x_percent) < 0.5
                and abs(self._motor_y_percent) < 0.5
                and abs(self.current_linear) < 1e-6
                and abs(self.current_angular) < 1e-6
            )
            if robot_commanded_still and abs(w) <= self.imu_stationary_deadband_rad:
                w = 0.0

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
            # velocity used for odom integration down accordingly. This makes
            # Nav2's own pose estimate reflect reality instead of the ideal
            # commanded motion, so it naturally keeps driving toward the goal
            # (instead of believing it already arrived) until the lidar
            # confirms real progress again.
            v *= self.lidar_odom_slip_scale

        self.pose_yaw += w * dt
        self.pose_x += v * math.cos(self.pose_yaw) * dt
        self.pose_y += v * math.sin(self.pose_yaw) * dt

        qx, qy, qz, qw = _yaw_to_quaternion(self.pose_yaw)

        odom = Odometry()
        odom.header.stamp = now.to_msg()
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame

        odom.pose.pose.position.x = float(self.pose_x)
        odom.pose.pose.position.y = float(self.pose_y)
        odom.pose.pose.position.z = 0.0
        odom.pose.pose.orientation.x = qx
        odom.pose.pose.orientation.y = qy
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw

        odom.twist.twist.linear.x = float(v)
        odom.twist.twist.angular.z = float(w)

        self.odom_pub.publish(odom)

        transform = TransformStamped()
        transform.header.stamp = now.to_msg()
        transform.header.frame_id = self.odom_frame
        transform.child_frame_id = self.base_frame
        transform.transform.translation.x = float(self.pose_x)
        transform.transform.translation.y = float(self.pose_y)
        transform.transform.translation.z = 0.0
        transform.transform.rotation.x = qx
        transform.transform.rotation.y = qy
        transform.transform.rotation.z = qz
        transform.transform.rotation.w = qw

        self.tf_broadcaster.sendTransform(transform)

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
    parser.add_argument("--imu-fusion-enabled", type=lambda v: str(v).lower() not in ("0", "false", "no"), default=True)
    parser.add_argument("--imu-gyro-sign", type=float, default=1.0)
    parser.add_argument("--imu-stationary-deadband-dps", type=float, default=0.5)
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
