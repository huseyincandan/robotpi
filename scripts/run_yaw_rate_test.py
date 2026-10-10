#!/usr/bin/env python3
"""Safely exercise ESP32-S3 TURNRATE and record IMU/encoder response.

Run on the Pi while the RobotPi app is already running. No second serial
connection is opened. Without --run this only checks live status/sensors.
"""
import argparse
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


BASE = "http://127.0.0.1:5000"
S3_STATUS_URL = "http://robomotor.local/status"


def request(path, timeout=2.0):
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post(path, timeout=2.0):
    req = urllib.request.Request(BASE + path, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def request_s3_status(timeout=1.0):
    req = urllib.request.Request(S3_STATUS_URL)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        text = response.read().decode("utf-8", "replace")
    return dict(
        token.split("=", 1) for token in text.split()
        if "=" in token
    )


def sample(duration, interval=0.1):
    rows = []
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        try:
            row = request("/imu/motion")
            if row.get("status") != "OK":
                raise RuntimeError(row.get("message", "IMU unavailable"))
            if row.get("enc_rl") is None or row.get("enc_rr") is None:
                raise RuntimeError("S3 encoder telemetry is stale or unavailable")
            s3 = request_s3_status()
            row["yaw_debug"] = {
                key: s3.get(key) for key in (
                    "yawActive", "yawTargetDps", "yawMeasuredDps", "yawErrorDps",
                    "yawFeedforwardPwm", "yawIntegralPwm", "yawRequestedPwm",
                    "yawOutput", "yawPwmRL", "yawPwmRR", "yawFault",
                )
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(f"SAMPLE ERROR: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)
    return rows


def median_rate(rows):
    vals = [float(r["gyro_z_dps"]) for r in rows]
    return statistics.median(vals) if vals else float("nan")


def rate_peak(rows):
    vals = [float(r["gyro_z_dps"]) for r in rows]
    return max(vals, key=abs) if vals else float("nan")


def median_encoder_delta(rows, key):
    vals = [int(r[key]) for r in rows if r.get(key) is not None]
    return (vals[-1] - vals[0]) if len(vals) >= 2 else None


def median_yaw_debug(rows, key):
    vals = []
    for row in rows:
        value = (row.get("yaw_debug") or {}).get(key)
        try:
            vals.append(float(value))
        except (TypeError, ValueError):
            pass
    return statistics.median(vals) if vals else None


def stop():
    try:
        post("/motor/stop")
    except Exception as exc:
        print(f"STOP ERROR: {exc}", file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="send physical TURNRATE pulses")
    parser.add_argument(
        "--rates",
        default="8,12,18",
        help="positive target rates in degrees/s; each is tested in both directions",
    )
    parser.add_argument(
        "--direction", choices=("both", "left", "right"), default="both",
        help="test both directions, or only one physical turn direction",
    )
    parser.add_argument("--vx", type=int, default=0, help="forward PWM component, limited by firmware to +/-155")
    parser.add_argument("--pulse", type=float, default=0.7, help="each pulse duration, seconds (max 1.5)")
    args = parser.parse_args()

    try:
        rates = [float(item.strip()) for item in args.rates.split(",") if item.strip()]
    except ValueError:
        parser.error("--rates must be comma-separated numbers")
    if not rates or any(not math.isfinite(rate) or not 1 <= rate <= 25 for rate in rates):
        parser.error("each --rates value must be between 1 and 25 degrees/s")
    if abs(args.vx) > 155:
        parser.error("--vx must be between -155 and 155")
    if not 0.2 <= args.pulse <= 1.5:
        parser.error("--pulse must be between 0.2 and 1.5 seconds")

    status = request("/motor/status")
    battery = request("/battery/status")
    navigation = request("/nav2/status")
    lidar = request("/lidar/readings")
    s3_status = request_s3_status()
    print("MOTOR", json.dumps(status, ensure_ascii=False))
    print("BATTERY", json.dumps(battery, ensure_ascii=False))
    print("NAVIGATION", json.dumps(navigation, ensure_ascii=False))
    print("S3_YAW_STATUS", json.dumps(s3_status, ensure_ascii=False))
    if not status.get("status") == "OK" or status.get("power_fault") or status.get("sensor_fault"):
        raise RuntimeError("motor/power/sensor status is not clear; refusing motion")
    if abs(float(status.get("current_x", 0))) > 0.01 or abs(float(status.get("current_y", 0))) > 0.01:
        raise RuntimeError("motor is already commanded to move; refusing test")
    if navigation.get("nav2_running") or navigation.get("explore_running"):
        raise RuntimeError("stop Nav2/exploration before the manual TURNRATE calibration")
    voltage = battery.get("bus_voltage", battery.get("voltage"))
    if voltage is not None and float(voltage) < 11.0:
        raise RuntimeError(f"battery too low for calibration test: {voltage} V")
    if not isinstance(lidar, dict) or lidar.get("status") != "OK":
        raise RuntimeError("LIDAR is not ready; refusing physical TURNRATE test")
    required_yaw_fields = (
        "yawActive", "yawTargetDps", "yawErrorDps", "yawFeedforwardPwm",
        "yawIntegralPwm", "yawRequestedPwm", "yawOutput", "yawPwmRL",
        "yawPwmRR", "yawFault",
    )
    missing_yaw_fields = [key for key in required_yaw_fields if key not in s3_status]
    if missing_yaw_fields:
        raise RuntimeError(
            "S3 diagnostic firmware is not flashed or status is incomplete; "
            f"missing {missing_yaw_fields}"
        )
    clearances = [
        float(lidar[key]) for key in ("front_cm", "left_cm", "back_cm", "right_cm")
        if lidar.get(key) is not None and float(lidar[key]) > 0
    ]
    if len(clearances) < 4:
        raise RuntimeError("LIDAR does not have fresh clearance readings in all four sectors")
    if not clearances or min(clearances) < 45:
        raise RuntimeError(f"LIDAR clearance is insufficient/unknown: min={min(clearances) if clearances else None} cm")

    baseline = sample(0.6)
    if len(baseline) < 3:
        raise RuntimeError("not enough fresh baseline IMU/encoder samples")
    if not args.run:
        print(
            "PRECHECK OK. Re-run with --run to test both directions at "
            f"{rates} degrees/s."
        )
        return

    results = []
    try:
        targets = [
            target
            for rate in rates
            for target in (
                (rate, -rate) if args.direction == "both"
                else (rate,) if args.direction == "left"
                else (-rate,)
            )
        ]
        for target in targets:
            # Re-check immediately before each individual physical pulse.
            pulse_status = request("/motor/status")
            pulse_battery = request("/battery/status")
            pulse_navigation = request("/nav2/status")
            pulse_lidar = request("/lidar/readings")
            pulse_voltage = pulse_battery.get("bus_voltage", pulse_battery.get("voltage"))
            pulse_clearances = [
                float(pulse_lidar[key])
                for key in ("front_cm", "left_cm", "back_cm", "right_cm")
                if pulse_lidar.get(key) is not None and float(pulse_lidar[key]) > 0
            ] if isinstance(pulse_lidar, dict) else []
            failures = []
            if pulse_status.get("power_fault"):
                failures.append("power_fault")
            if pulse_status.get("sensor_fault"):
                failures.append("sensor_fault")
            if abs(float(pulse_status.get("current_x", 0))) > 0.01 or abs(float(pulse_status.get("current_y", 0))) > 0.01:
                failures.append("motor_not_idle")
            if pulse_navigation.get("nav2_running") or pulse_navigation.get("explore_running"):
                failures.append("navigation_running")
            if pulse_voltage is None or float(pulse_voltage) < 11.0:
                failures.append(f"battery_voltage={pulse_voltage}")
            if pulse_lidar.get("status") != "OK":
                failures.append("lidar_unavailable")
            if len(pulse_clearances) < 4:
                failures.append("lidar_missing_sector")
            if min(pulse_clearances, default=0) < 45:
                sectors = {
                    key: pulse_lidar.get(key)
                    for key in ("front_cm", "left_cm", "back_cm", "right_cm")
                }
                failures.append(f"lidar_clearance_below_45cm={sectors}")
            if failures:
                raise RuntimeError(
                    "live safety precondition changed; aborting remaining pulses: "
                    + "; ".join(failures)
                )
            # Positive z rotation is counterclockwise/left in the robot frame.
            direction = "LEFT" if target > 0 else "RIGHT"
            print(f"PULSE {direction} target={target:g} dps duration={args.pulse:g}s")
            before = sample(0.3)
            query = urllib.parse.urlencode({
                "x": target / 60 * 100,
                "y": 0,
                "source": "manual",
                "yaw_rate_dps": target,
            })
            ack = request("/drive?" + query)
            print("DRIVE ACK", json.dumps(ack, ensure_ascii=False))
            if ack.get("status") != "OK":
                raise RuntimeError("drive request was rejected")
            moving = sample(args.pulse)
            stop()
            after = sample(0.4)
            # Commanded interval is approximated by samples collected after ACK.
            result = {
                "target_dps": target,
                "measured_median_dps_during": median_rate(moving),
                "measured_median_dps_last_3": median_rate(moving[-3:]),
                "measured_peak_dps": rate_peak(moving),
                "measured_median_dps_baseline": median_rate(before),
                "enc_rl_delta": median_encoder_delta(moving, "enc_rl"),
                "enc_rr_delta": median_encoder_delta(moving, "enc_rr"),
                "yaw_error_median_dps": median_yaw_debug(moving, "yawErrorDps"),
                "yaw_feedforward_median_pwm": median_yaw_debug(moving, "yawFeedforwardPwm"),
                "yaw_integral_median_pwm": median_yaw_debug(moving, "yawIntegralPwm"),
                "yaw_requested_median_pwm": median_yaw_debug(moving, "yawRequestedPwm"),
                "yaw_output_median_pwm": median_yaw_debug(moving, "yawOutput"),
                "yaw_pwm_rl_median": median_yaw_debug(moving, "yawPwmRL"),
                "yaw_pwm_rr_median": median_yaw_debug(moving, "yawPwmRR"),
                "sample_count": len(moving),
            }
            results.append(result)
            print("RESULT", json.dumps(result))
            time.sleep(0.5)
    finally:
        stop()

    print("SUMMARY", json.dumps(results, ensure_ascii=False))
    if len(results) == len(targets):
        if any(not math.isfinite(r["measured_median_dps_last_3"]) for r in results):
            print("ASSESSMENT: incomplete IMU data")
            return
        print("Assessment: compare last-three medians with targets; check response symmetry and encoder/yaw signs.")


if __name__ == "__main__":
    try:
        main()
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
        print(f"TEST ABORTED: {exc}", file=sys.stderr)
        sys.exit(2)
