#!/usr/bin/env python3
"""Host tests for encoder-error fixed-PWM pulse decisions."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.fixed_pwm import fixed_pwm_wheel_command


def main():
    pwm = 150
    latency = 0.12

    # Positive and reverse target movement apply only the fixed amplitude.
    assert fixed_pwm_wheel_command(0.2, 0.05, 0.1, pwm, latency) == 150
    assert fixed_pwm_wheel_command(-0.2, -0.05, -0.1, pwm, latency) == -150

    # Predict braking from measured wheel speed, then stop without reverse torque.
    assert fixed_pwm_wheel_command(0.2, 0.010, 0.1, pwm, latency) == 0
    assert fixed_pwm_wheel_command(0.2, -0.02, 0.1, pwm, latency) == 0
    assert fixed_pwm_wheel_command(-0.2, 0.02, -0.1, pwm, latency) == 0

    # Near-zero target velocity never pulses; static deadband remains bounded.
    assert fixed_pwm_wheel_command(0.0, 1.0, 0.0, pwm, latency) == 0
    assert fixed_pwm_wheel_command(0.2, 0.002, 0.0, pwm, latency) == 0
    assert fixed_pwm_wheel_command(0.2, 0.004, 0.0, pwm, latency) == 150

    print("PASS: fixed PWM amplitude, direction, predictive stop, overshoot hold, deadband")


if __name__ == "__main__":
    main()
