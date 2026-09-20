#!/usr/bin/env python3
"""Canonical launcher for both manual development and GPIO26 boot startup."""

import argparse
import os
import shlex
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from config import APP, MAP


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

    ros_python = Path(str(MAP["ROS2_PYTHON_BIN"])).expanduser().resolve()
    ros_underlay_setup = ros_python.parent.parent / "setup.bash"
    ros_workspace_setup = Path(str(MAP["ROS2_SETUP_BASH"])).expanduser()

    if not ros_underlay_setup.is_file():
        raise RuntimeError(f"ROS2 underlay setup file not found: {ros_underlay_setup}")
    if not ros_workspace_setup.is_file():
        raise RuntimeError(f"ROS2 workspace setup file not found: {ros_workspace_setup}")

    uvicorn_args = [
        sys.executable,
        "-m",
        "uvicorn",
        "app:app",
        "--host",
        APP["HOST"],
        "--port",
        str(APP["PORT"]),
        # ROS bridges poll local sensor endpoints at 50 Hz.  Their HTTP access
        # records are expected traffic, not actionable app logs.
        "--no-access-log",
    ]
    shell_cmd = (
        f"source {shlex.quote(str(ros_underlay_setup))} && "
        f"source {shlex.quote(str(ros_workspace_setup))} && "
        f"exec {shlex.join(uvicorn_args)}"
    )
    os.execv("/bin/bash", ["bash", "-lc", shell_cmd])


if __name__ == "__main__":
    main()
