"""Pure fixed-amplitude pulse decisions for wheel-position feedback."""


def fixed_pwm_wheel_command(target_velocity, position_error, measured_velocity,
                            pwm, stop_latency_sec, position_deadband_m=0.003):
    """Return fixed signed PWM while position error exceeds predicted coast."""
    if abs(target_velocity) < 1e-4:
        return 0
    stop_distance = max(
        position_deadband_m,
        abs(measured_velocity) * stop_latency_sec,
    )
    if position_error * target_velocity <= stop_distance * abs(target_velocity):
        return 0
    return pwm if target_velocity > 0 else -pwm
