"""Regression test for fixed-PWM feedback cadence.

The old 14 Hz bridge paired with 10 Hz encoder telemetry quantized both the
motor pulse and the observed position. At low target wheel speeds that caused
large average-speed error. Use the measured 150-PWM free-wheel speed from the
Oct 6 calibration as a simple plant model; this is a control-resolution test,
not a replacement for a supervised floor test.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.fixed_pwm import fixed_pwm_wheel_command


def simulate_average_speed(control_hz, encoder_hz, stop_latency, target_speed,
                           pwm_speed=0.21, duration_s=10.0):
    dt = 1.0 / control_hz
    encoder_period = 1.0 / encoder_hz
    actual_position = 0.0
    target_position = 0.0
    observed_position = 0.0
    measured_speed = 0.0
    last_encoder_time = 0.0
    command = 0
    steps = int(duration_s * control_hz)

    for step in range(steps):
        actual_position += command / 150.0 * pwm_speed * dt
        target_position += target_speed * dt
        now = (step + 1) * dt

        if now - last_encoder_time >= encoder_period - 1e-8:
            quantized_position = round(actual_position * 13352.0) / 13352.0
            measured_speed = (
                quantized_position - observed_position
            ) / (now - last_encoder_time)
            observed_position = quantized_position
            last_encoder_time = now

        command = fixed_pwm_wheel_command(
            target_speed,
            target_position - observed_position,
            measured_speed,
            150,
            stop_latency,
        )

    return actual_position / duration_s


class FixedPwmCadenceTests(unittest.TestCase):
    def test_50hz_feedback_reduces_low_speed_tracking_error(self):
        for target_speed in (0.003, 0.01, 0.04):
            with self.subTest(target_speed=target_speed):
                old_speed = simulate_average_speed(14, 10, 0.12, target_speed)
                matched_speed = simulate_average_speed(50, 50, 0.04, target_speed)
                self.assertLessEqual(
                    abs(matched_speed - target_speed),
                    abs(old_speed - target_speed),
                )
                self.assertLess(abs(matched_speed - target_speed), 0.001)


if __name__ == "__main__":
    unittest.main()
