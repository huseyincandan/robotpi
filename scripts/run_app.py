#!/usr/bin/env python3
"""Canonical launcher for both manual development and GPIO26 boot startup."""

import argparse
import os
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from config import APP


def main():
    parser = argparse.ArgumentParser(description="Start RobotPi's web application")
    parser.add_argument(
        "--launch-mode",
        choices=("manual", "gpio26"),
        required=True,
        help="Records whether this run was started by a developer or GPIO26 service",
    )
    args = parser.parse_args()

    os.chdir(PROJECT_DIR)
    os.environ["ROBOTPI_LAUNCH_MODE"] = args.launch_mode
    os.environ["ROBOTPI_LAUNCH_ENTRYPOINT"] = str(Path(__file__).resolve())

    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            APP["HOST"],
            "--port",
            str(APP["PORT"]),
            # ROS bridges poll local sensor endpoints at 50 Hz.  Their HTTP
            # access records are expected traffic, not actionable app logs;
            # keep the manual launcher terminal readable for startup/errors.
            "--no-access-log",
        ],
    )


if __name__ == "__main__":
    main()
