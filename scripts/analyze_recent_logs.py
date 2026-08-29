#!/usr/bin/env python3
import os
import re
import sys
from collections import Counter

PROJECT_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

if PROJECT_DIR not in sys.path:
    sys.path.insert(
        0,
        PROJECT_DIR
    )

from config import LOGGING


INTERESTING_PATTERNS = [
    "MOVEMENT:",
    "WANDER",
    "FORWARD DISTANCE:",
    "OBSTACLE STOP:",
    "IMU STUCK:",
    "RECOVERY",
    "ERROR",
    "Traceback"
]


def main():
    logs_dir = LOGGING["DIR"]
    run_dirs = recent_run_dirs(
        logs_dir,
        LOGGING["KEEP_RUNS"]
    )

    if not run_dirs:
        print("No run logs found.")
        return 0

    for run_dir in run_dirs:
        analyze_run(
            run_dir
        )

    return 0


def recent_run_dirs(logs_dir, limit):
    if not os.path.isdir(logs_dir):
        return []

    run_dirs = [
        os.path.join(logs_dir, name)
        for name in os.listdir(logs_dir)
        if name.startswith("run-")
        and os.path.isdir(os.path.join(logs_dir, name))
    ]
    run_dirs.sort(
        key=lambda path: os.path.getmtime(path),
        reverse=True
    )

    return run_dirs[:limit]


def analyze_run(run_dir):
    app_log = os.path.join(
        run_dir,
        LOGGING["APP_LOG_FILE"]
    )
    print("\n===", run_dir, "===")

    if not os.path.exists(app_log):
        print("missing app log")
        return

    with open(
        app_log,
        "r",
        encoding="utf-8",
        errors="replace"
    ) as log_file:
        lines = log_file.readlines()

    counters = Counter()
    interesting_lines = []

    for line in lines:
        for pattern in INTERESTING_PATTERNS:
            if pattern in line:
                counters[pattern] += 1
                interesting_lines.append(
                    line.rstrip()
                )
                break

    print("lines:", len(lines))

    for pattern, count in counters.most_common():
        print(f"{pattern} {count}")

    print("recent interesting lines:")

    for line in interesting_lines[-40:]:
        print(
            redact_noise(line)
        )


def redact_noise(line):
    return re.sub(
        r"Corrupt JPEG data:.*",
        "Corrupt JPEG data: ...",
        line
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )