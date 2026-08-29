import asyncio
from collections import deque
import os
import statistics
import threading

from gpiozero import Device
import gpiozero.pins.lgpio as lgpio_pins
from gpiozero.pins.lgpio import LGPIOFactory

# Work around a gpiozero/lgpio bug on some Python builds where os is not imported.
# This used to live in services/motor.py, but motor control moved to the ESP32-S3
# over serial, so this is now the only gpiozero user left in the main app process.
if not hasattr(lgpio_pins, "os"):
    lgpio_pins.os = os

Device.pin_factory = LGPIOFactory()

from gpiozero import DistanceSensor

from config import ULTRASONIC


def nearest_confirmed_cluster(samples, minimum_samples, maximum_spread):

    ordered = sorted(float(sample) for sample in samples)
    best = None

    for start in range(len(ordered)):
        end = start
        while end < len(ordered) and ordered[end] - ordered[start] <= maximum_spread:
            end += 1

        cluster = ordered[start:end]
        if len(cluster) < minimum_samples:
            continue

        candidate = {
            "distance_cm": float(statistics.median(cluster)),
            "sample_count": len(cluster),
            "spread_cm": float(cluster[-1] - cluster[0])
        }
        if best is None or candidate["distance_cm"] < best["distance_cm"]:
            best = candidate

    return best


class DistanceService:

    def __init__(self):

        self.sensor = DistanceSensor(
            echo=ULTRASONIC["ECHO_PIN"],
            trigger=ULTRASONIC["TRIGGER_PIN"],
            max_distance=ULTRASONIC["MAX_DISTANCE_METERS"]
        )
        self._samples = deque(maxlen=max(1, int(ULTRASONIC.get("FILTER_WINDOW_SIZE", 7))))
        self._samples_lock = threading.Lock()

    def read_centimeters(self):

        centimeters = self.sensor.distance * 100
        with self._samples_lock:
            self._samples.append(float(centimeters))
        return centimeters

    def read_safety_centimeters(self):

        self.read_centimeters()

        with self._samples_lock:
            samples = list(self._samples)

        cluster = nearest_confirmed_cluster(
            samples,
            max(1, int(ULTRASONIC.get("CLUSTER_MIN_SAMPLES", 3))),
            max(0.1, float(ULTRASONIC.get("CLUSTER_MAX_SPREAD_CM", 3.0)))
        )

        if cluster is None:
            return None

        return cluster["distance_cm"]

    def read_observation(self):

        self.read_centimeters()
        with self._samples_lock:
            samples = list(self._samples)

        distance_cm = float(statistics.median(samples))
        spread_cm = float(max(samples) - min(samples))
        minimum_samples = max(1, int(ULTRASONIC.get("STABLE_MIN_SAMPLES", 5)))
        maximum_spread = max(0.1, float(ULTRASONIC.get("STABLE_MAX_SPREAD_CM", 3.0)))
        stable = len(samples) >= minimum_samples and spread_cm <= maximum_spread
        confidence = min(1.0, len(samples) / minimum_samples) * max(
            0.0,
            1.0 - spread_cm / maximum_spread
        )
        cluster = nearest_confirmed_cluster(
            samples,
            max(1, int(ULTRASONIC.get("CLUSTER_MIN_SAMPLES", 3))),
            max(0.1, float(ULTRASONIC.get("CLUSTER_MAX_SPREAD_CM", 3.0)))
        )

        return {
            "distance_cm": distance_cm,
            "stable": stable,
            "confidence": confidence,
            "sample_count": len(samples),
            "spread_cm": spread_cm,
            "nearest_cluster_confirmed": cluster is not None,
            "nearest_cluster_distance_cm": cluster["distance_cm"] if cluster else None,
            "nearest_cluster_sample_count": cluster["sample_count"] if cluster else 0,
            "nearest_cluster_spread_cm": cluster["spread_cm"] if cluster else None
        }

    def close(self):

        self.sensor.close()


async def log_distance_loop(distance):

    while True:
        try:
            centimeters = await asyncio.to_thread(
                distance.read_centimeters
            )
            print(
                "DISTANCE:",
                round(centimeters, 1),
                "cm",
                flush=True
            )

        except Exception as exc:
            print(
                "DISTANCE ERROR:",
                repr(exc),
                flush=True
            )

        await asyncio.sleep(
            ULTRASONIC["LOG_INTERVAL_SECONDS"]
        )
