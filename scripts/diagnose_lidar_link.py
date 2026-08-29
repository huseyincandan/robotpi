#!/usr/bin/env python3
import argparse
import time
import types

from rplidar import RPLidar


def _safe_close(lidar):
    if lidar is None:
        return

    for fn_name in ("stop", "stop_motor", "disconnect"):
        try:
            getattr(lidar, fn_name)()
        except Exception:
            pass


def test_scan(port, baudrate, scan_type, timeout_s, disable_pwm_start=True):
    lidar = None
    scan_batches = 0
    error = ""

    try:
        lidar = RPLidar(port, baudrate=baudrate, timeout=1)

        if disable_pwm_start:
            def _start_motor_no_pwm(lidar_self):
                lidar_self._serial.setDTR(False)
                lidar_self.motor_running = True

            lidar.start_motor = types.MethodType(_start_motor_no_pwm, lidar)

        start = time.time()

        for _scan in lidar.iter_scans(scan_type=scan_type, max_buf_meas=1000):
            scan_batches += 1

            if scan_batches >= 3:
                break

            if (time.time() - start) >= timeout_s:
                break

    except Exception as exc:
        error = repr(exc)

    finally:
        _safe_close(lidar)

    return {
        "port": port,
        "baudrate": baudrate,
        "scan_type": scan_type,
        "scan_batches": scan_batches,
        "error": error,
    }


def main():
    parser = argparse.ArgumentParser(description="Diagnose RPLIDAR serial link")
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument("--disable-pwm-start", dest="disable_pwm_start", action="store_true")
    parser.add_argument("--enable-pwm-start", dest="disable_pwm_start", action="store_false")
    parser.set_defaults(disable_pwm_start=True)
    args = parser.parse_args()

    bauds = (460800, 256000, 115200)
    scan_types = ("normal", "express", "force")

    print("LIDAR DIAG START")
    print(f"port={args.port}")

    results = []

    for baud in bauds:
        for scan_type in scan_types:
            result = test_scan(
                args.port,
                baud,
                scan_type,
                args.timeout,
                disable_pwm_start=args.disable_pwm_start,
            )
            results.append(result)
            print(result)

    any_ok = any(item["scan_batches"] > 0 for item in results)

    print("SUMMARY")

    if any_ok:
        print("status=OK")
        print("message=At least one scan mode/baud produced frames")
        return

    unique_errors = sorted(
        {item["error"] for item in results if item["error"]}
    )

    print("status=FAIL")
    print("message=No scan frames received from lidar")

    if unique_errors:
        print("errors=")
        for err in unique_errors:
            print(f"- {err}")

    print("next_steps=")
    print("- Ensure only one process accesses the port (stop app and ROS lidar nodes).")
    print("- Re-seat USB cable and try a short, shielded cable.")
    print("- Provide stable 5V power; avoid underpowered hubs.")
    print("- Confirm motor spins physically during test.")
    print("- If available, test same lidar on a laptop to isolate hardware fault.")


if __name__ == "__main__":
    main()