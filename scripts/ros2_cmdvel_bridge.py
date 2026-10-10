#!/usr/bin/env python3
import argparse
import json
import math
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import sys
from pathlib import Path

# This file is launched by absolute path, so Python normally puts only
# ``scripts/`` on sys.path. The bridge imports its shared controller helper
# from the repository's ``services`` package; add the repository root first.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import rclpy
from geometry_msgs.msg import TransformStamped
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Range
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
from services.fixed_pwm import fixed_pwm_wheel_command


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
        self.s3_yaw_rate_control = args.s3_yaw_rate_control
        self.max_angular = max(0.01, float(args.max_angular_z))
        self.max_drive = max(10.0, float(args.max_drive_percent))
        self.max_turn = max(10.0, float(args.max_turn_percent))
        self.angular_slew_rate = max(0.05, float(args.angular_slew_rate))
        self.min_linear_scale_at_max_turn = max(
            0.0,
            min(1.0, float(args.min_linear_scale_at_max_turn))
        )
        self.command_timeout = max(0.05, float(args.command_timeout_sec))
        self.fixed_pwm = max(0, min(155, int(args.fixed_pwm)))
        self.fixed_pwm_stop_latency = max(0.02, float(args.fixed_pwm_stop_latency_sec))

        self.odom_frame = str(args.odom_frame)
        self.base_frame = str(args.base_frame)
        self.laser_frame = str(args.laser_frame)
        self.laser_x_offset = float(args.laser_x_offset)

        self.current_linear = 0.0
        self.current_angular = 0.0
        self.target_angular = 0.0
        self.last_cmd_time = self.get_clock().now()
        self._last_drive_monotonic = time.monotonic()
        self._last_sent_was_idle = True

        self.odom_vx_variance = max(1e-6, float(args.odom_vx_variance))
        self.odom_vyaw_variance = max(1e-6, float(args.odom_vyaw_variance))

        # Real wheel-encoder-derived odometry is the sole translation source.
        # Stale or missing ticks produce zero velocity instead of pretending
        # that a commanded wheel movement actually happened.
        self.encoder_odom_source_enabled = bool(args.encoder_odom_source_enabled)
        self.encoder_ticks_per_meter = max(1.0, float(args.encoder_ticks_per_meter))
        self.encoder_track_width_m = max(0.01, float(args.encoder_track_width_m))
        self.encoder_max_age_sec = max(0.1, float(args.encoder_max_age_sec))
        self.encoder_max_tick_rate = max(100.0, float(args.encoder_max_tick_rate))
        self._enc_prev_rl = None
        self._enc_prev_rr = None
        self._enc_prev_monotonic = None
        self._encoder_v = 0.0
        self._encoder_w = 0.0
        self._encoder_last_update_monotonic = None
        self._encoder_last_sequence = None
        self._encoder_left_position_m = None
        self._encoder_right_position_m = None
        self._fixed_target_left_m = None
        self._fixed_target_right_m = None

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

        # Encoder tick data (enc_rl/enc_rr) rides along on the same /imu/motion
        # HTTP response polled by the IMU bridge - fused gyro_z itself is now
        # read independently by ros2_imu_bridge.py and fused by
        # robot_localization's EKF instead of here.
        if self.encoder_odom_source_enabled:
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
            f"drive={self.drive_endpoint} fixed_pwm={self.fixed_pwm}"
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
            # Keep last known encoder ticks; the position controller uses the
            # encoder freshness limit before issuing any fixed-PWM pulse.
            return

        if payload.get("status") != "OK":
            return

        self._update_encoder_odom(payload)

    def _update_encoder_odom(self, payload):

        enc_rl = payload.get("enc_rl")
        enc_rr = payload.get("enc_rr")
        if enc_rl is None or enc_rr is None:
            return

        # /imu/motion contains cached S3 TELEM data. The bridge polls HTTP
        # faster than that UART stream, so repeated encoder values are not new
        # measurements and must not be converted into a fake zero velocity.
        sequence = payload.get("telemetry_sequence")
        if sequence is not None and sequence == self._encoder_last_sequence:
            return

        now = time.monotonic()

        if self._enc_prev_monotonic is not None:
            dt = now - self._enc_prev_monotonic
            if dt > 1e-3:
                delta_l = enc_rl - self._enc_prev_rl
                delta_r = enc_rr - self._enc_prev_rr
                # A reboot/reset returns encoder counters near zero. Do not
                # publish its huge discontinuity as robot velocity; rebase on
                # the new counters and wait for the next real sample instead.
                max_delta = max(500.0, self.encoder_max_tick_rate * max(dt, 0.05) * 2.5)
                if abs(delta_l) > max_delta or abs(delta_r) > max_delta:
                    self.get_logger().warn(
                        "discarding encoder discontinuity "
                        f"dl={delta_l} dr={delta_r} dt={dt:.3f}s"
                    )
                    self._encoder_v = 0.0
                    self._encoder_w = 0.0
                    self._encoder_last_update_monotonic = None
                    self._enc_prev_rl = enc_rl
                    self._enc_prev_rr = enc_rr
                    self._enc_prev_monotonic = now
                    self._encoder_last_sequence = sequence
                    self._encoder_left_position_m = enc_rl / self.encoder_ticks_per_meter
                    self._encoder_right_position_m = enc_rr / self.encoder_ticks_per_meter
                    self._fixed_target_left_m = self._encoder_left_position_m
                    self._fixed_target_right_m = self._encoder_right_position_m
                    return

                dist_l = delta_l / self.encoder_ticks_per_meter
                dist_r = delta_r / self.encoder_ticks_per_meter
                self._encoder_v = (dist_l + dist_r) / 2.0 / dt
                self._encoder_w = (dist_r - dist_l) / self.encoder_track_width_m / dt
                self._encoder_last_update_monotonic = now

        self._enc_prev_rl = enc_rl
        self._enc_prev_rr = enc_rr
        self._enc_prev_monotonic = now
        self._encoder_last_sequence = sequence
        self._encoder_left_position_m = enc_rl / self.encoder_ticks_per_meter
        self._encoder_right_position_m = enc_rr / self.encoder_ticks_per_meter

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

        try:
            measured_range = (
                float(distance_cm) / 100.0
                + self.ultrasonic_x_offset
            )
        except (TypeError, ValueError, OverflowError):
            return

        msg = Range()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self.base_frame
        msg.radiation_type = Range.ULTRASOUND
        msg.field_of_view = math.radians(24.0)
        msg.min_range = 0.02
        msg.max_range = 4.2
        if not math.isfinite(measured_range) or not (
            msg.min_range <= measured_range <= msg.max_range
        ):
            return
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

        y_percent = max(
            -self.max_drive,
            min(self.max_drive, (self.current_linear / self.max_linear) * self.max_drive)
        )

        turn_ratio = min(1.0, abs(self.current_angular) / self.max_angular)
        linear_scale = 1.0 - (
            (1.0 - self.min_linear_scale_at_max_turn) * turn_ratio
        )
        y_percent *= linear_scale

        # nav2 idle iken bile bu 0,0'i tekrar tekrar gondermek ESP32'nin
        # paylasilan UART hattinda ayni motorWrite()'i cagiran web arayuzuyle
        # (robomotor.local) yarisiyordu - kullanicinin butona basili tuttugu
        # komutu her ~50-100ms'de bir sifirlayip "kesik kesik" donmeye yol
        # aciyordu. Idle'a gecis kenarinda TEK sefer 0,0 gonderilir, tekrar
        # hareket komutu gelene kadar sessiz kalinir.
        is_idle = abs(x_percent) < 0.01 and abs(y_percent) < 0.01
        if is_idle and self._last_sent_was_idle:
            return
        if self.fixed_pwm:
            self._drive_fixed_pwm(now_monotonic, elapsed)
        else:
            self._send_drive(x_percent, y_percent)
            self._last_sent_was_idle = is_idle

    def _drive_fixed_pwm(self, now_monotonic, elapsed):
        if (
            self._encoder_left_position_m is None
            or self._encoder_right_position_m is None
            or self._encoder_last_update_monotonic is None
            or now_monotonic - self._encoder_last_update_monotonic > self.encoder_max_age_sec
        ):
            if not self._last_sent_was_idle:
                self._send_drive(0.0, 0.0)
                self._last_sent_was_idle = True
            self._fixed_target_left_m = self._encoder_left_position_m
            self._fixed_target_right_m = self._encoder_right_position_m
            return

        actual_left = self._encoder_left_position_m
        actual_right = self._encoder_right_position_m
        if self._fixed_target_left_m is None or self._fixed_target_right_m is None:
            self._fixed_target_left_m = actual_left
            self._fixed_target_right_m = actual_right

        # Stopping commands freeze each target at the measured wheel position;
        # do not drive backwards to compensate for coast after a requested stop.
        if abs(self.current_linear) < 1e-4 and abs(self.current_angular) < 1e-4:
            self._fixed_target_left_m = actual_left
            self._fixed_target_right_m = actual_right
            self._send_drive(0.0, 0.0)
            self._last_sent_was_idle = True
            return

        target_linear = max(-self.max_linear, min(self.max_linear, self.current_linear))
        target_angular = max(-self.max_angular, min(self.max_angular, self.current_angular))
        left_target_velocity = (
            target_linear - target_angular * self.encoder_track_width_m / 2.0
        )
        right_target_velocity = (
            target_linear + target_angular * self.encoder_track_width_m / 2.0
        )
        self._fixed_target_left_m += left_target_velocity * elapsed
        self._fixed_target_right_m += right_target_velocity * elapsed

        left_measured_velocity = self._encoder_v - self._encoder_w * self.encoder_track_width_m / 2.0
        right_measured_velocity = self._encoder_v + self._encoder_w * self.encoder_track_width_m / 2.0
        left_pwm = fixed_pwm_wheel_command(
            left_target_velocity,
            self._fixed_target_left_m - actual_left,
            left_measured_velocity,
            self.fixed_pwm,
            self.fixed_pwm_stop_latency,
        )
        right_pwm = fixed_pwm_wheel_command(
            right_target_velocity,
            self._fixed_target_right_m - actual_right,
            right_measured_velocity,
            self.fixed_pwm,
            self.fixed_pwm_stop_latency,
        )

        # Convert per-wheel fixed outputs back to the S3 tank-drive convention:
        # left = vx - omega, right = vx + omega.
        vx_pwm = (left_pwm + right_pwm) / 2.0
        omega_pwm = (right_pwm - left_pwm) / 2.0
        response = self._send_drive(omega_pwm / 2.55, vx_pwm / 2.55)
        if response and response.get("status") == "BLOCKED":
            # The HTTP safety gate may suppress a wheel pulse even though
            # Nav2 still requests motion. Do not accumulate that unexecuted
            # distance: it would cause a catch-up burst when the gate clears.
            self._fixed_target_left_m = actual_left
            self._fixed_target_right_m = actual_right
        self._last_sent_was_idle = left_pwm == 0 and right_pwm == 0

    def _send_drive(self, x_percent, y_percent):

        params = {
            "x": f"{float(x_percent):.4f}",
            "y": f"{float(y_percent):.4f}",
            "source": "nav2"
        }
        if self.s3_yaw_rate_control:
            params["yaw_rate_dps"] = f"{math.degrees(max(-self.max_angular, min(self.max_angular, self.current_angular))):.4f}"
        query = urllib.parse.urlencode(params)

        url = f"{self.drive_endpoint}?{query}"

        request = urllib.request.Request(
            url=url,
            method="GET"
        )

        try:
            with urllib.request.urlopen(request, timeout=0.35) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, socket.timeout):
            # Keep bridge loop quiet on transient HTTP hiccups.
            return None

    def _odom_loop(self):

        # This publishes a raw velocity-only source (/odom_raw) for
        # robot_localization's EKF to fuse - no local pose integration or
        # odom->base_link TF here anymore (the EKF owns both, see
        # config/ekf.yaml and services/ros2_navigation.py).
        # Never substitute commanded velocity for missing wheel feedback.
        # That would make a stuck, reset, or disconnected robot appear to
        # Nav2 as if it were moving.  A conservative zero makes Nav2's normal
        # progress/recovery logic stop and report the fault instead.
        v = 0.0
        w = self.current_angular

        if (
            self.encoder_odom_source_enabled
            and self._encoder_last_update_monotonic is not None
            and (time.monotonic() - self._encoder_last_update_monotonic) <= self.encoder_max_age_sec
        ):
            # Real wheel-tick-derived velocity is the sole translation source.
            # Stale or unavailable encoder feedback stays at zero above so a
            # stopped robot is never reported as moving from its command alone.
            v = self._encoder_v

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
        # Row-major 6x6 covariance; only linear.x is fused from this source.
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
    parser.add_argument("--s3-yaw-rate-control", action="store_true", help="Use calibrated S3 gyro rate controller")
    parser.add_argument("--max-angular-z", type=float, default=0.45)
    parser.add_argument("--max-drive-percent", type=float, default=38.0)
    parser.add_argument("--max-turn-percent", type=float, default=100.0)
    parser.add_argument("--angular-slew-rate", type=float, default=0.45)
    parser.add_argument("--min-linear-scale-at-max-turn", type=float, default=0.25)
    parser.add_argument("--command-timeout-sec", type=float, default=0.45)
    parser.add_argument("--fixed-pwm", type=int, default=0,
                        help="Encoder-feedback pulse mode using this fixed per-wheel PWM (0 disables)")
    parser.add_argument("--fixed-pwm-stop-latency-sec", type=float, default=0.04)
    parser.add_argument("--drive-rate-hz", type=float, default=50.0)
    parser.add_argument("--odom-rate-hz", type=float, default=50.0)
    parser.add_argument("--odom-vx-variance", type=float, default=0.01)
    parser.add_argument("--odom-vyaw-variance", type=float, default=0.05)
    parser.add_argument("--imu-rate-hz", type=float, default=50.0)
    parser.add_argument("--encoder-odom-source-enabled", type=lambda v: str(v).lower() not in ("0", "false", "no"), default=True)
    parser.add_argument("--encoder-ticks-per-meter", type=float, default=21786.0)
    parser.add_argument("--encoder-track-width-m", type=float, default=0.243)
    parser.add_argument("--encoder-max-age-sec", type=float, default=0.5)
    parser.add_argument("--encoder-max-tick-rate", type=float, default=15000.0)
    parser.add_argument("--ultrasonic-topic", default="/ultrasonic_range")
    parser.add_argument("--ultrasonic-rate-hz", type=float, default=10.0)
    parser.add_argument("--ultrasonic-x-offset", type=float, default=0.27)
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
