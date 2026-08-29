#!/usr/bin/env python3
import os
import sys
import time

from gpiozero import Device
import gpiozero.pins.lgpio as lgpio_pins
from gpiozero.pins.lgpio import LGPIOFactory

# Work around a gpiozero/lgpio bug on some Python builds where os is not
# imported (see services/distance.py for the same workaround). Without this,
# Button() falls through to the native pin factory, which fails under
# systemd because this Pi 5 only has /dev/gpiomem0..4, not /dev/gpiomem.
if not hasattr(lgpio_pins, "os"):
    lgpio_pins.os = os

Device.pin_factory = LGPIOFactory()

from gpiozero import Button

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

from config import APP, BOOT_SWITCH


def main():
    os.chdir(PROJECT_DIR)

    switch = Button(
        BOOT_SWITCH["PIN"],
        pull_up=True,
        bounce_time=None
    )

    try:
        time.sleep(
            BOOT_SWITCH["SETTLE_SECONDS"]
        )

        if not switch.is_pressed:
            print(
                f"Boot switch GPIO{BOOT_SWITCH['PIN']} is open; app will not start.",
                flush=True
            )
            return 0

        print(
            f"Boot switch GPIO{BOOT_SWITCH['PIN']} is closed; starting app.",
            flush=True
        )

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
                str(APP["PORT"])
            ]
        )

    finally:
        switch.close()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )