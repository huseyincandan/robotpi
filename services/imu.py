import math
import time
from collections import deque

from config import IMU
from services.i2c_bus import I2C_BUS_LOCK

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus


PWR_MGMT_1 = 0x6B
WHO_AM_I = 0x75
ACCEL_XOUT_H = 0x3B

ACCEL_SCALE = 16384.0
GYRO_SCALE = 131.0


class Mpu6050Service:

    def __init__(self):

        self.bus_number = IMU["BUS"]
        self.address = IMU["ADDRESS"]
        self.lock = I2C_BUS_LOCK
        self.bus = SMBus(self.bus_number)
        self.last_sample = None
        self.last_stuck_time = 0
        self.last_read_error = None
        self._read_retry_times = deque(maxlen=64)

        self.gyro_bias_x = 0.0
        self.gyro_bias_y = 0.0
        self.gyro_bias_z = 0.0

        with self.lock:
            self.bus.write_byte_data(
                self.address,
                PWR_MGMT_1,
                0
            )
            self.who_am_i = self.bus.read_byte_data(
                self.address,
                WHO_AM_I
            )

        print(
            f"IMU READY: bus={self.bus_number} address=0x{self.address:02x} "
            f"who_am_i=0x{self.who_am_i:02x}",
            flush=True
        )

        # Robotun sensor yerlesimi/titresim gibi nedenlerle her acilista farkli
        # bir dinlenme-hali sapmasi (bias) olabiliyor; kalibre etmezsek odom yaw
        # robot tamamen sabitken bile bu sapmayi surekli entegre edip driftliyor.
        self.calibrate_gyro_bias()

    def read_motion(self):

        # Motor calisirken PWM gurultusu ile ara sira tek seferlik I2C hatasi (Remote I/O
        # error) olusabiliyor; bir kez daha denemek gecici hatayi cogunlukla atlatir.
        try:
            with self.lock:
                accel_x = self._read_word(ACCEL_XOUT_H) / ACCEL_SCALE
                accel_y = self._read_word(ACCEL_XOUT_H + 2) / ACCEL_SCALE
                accel_z = self._read_word(ACCEL_XOUT_H + 4) / ACCEL_SCALE

                gyro_x = self._read_word(ACCEL_XOUT_H + 8) / GYRO_SCALE
                gyro_y = self._read_word(ACCEL_XOUT_H + 10) / GYRO_SCALE
                gyro_z = self._read_word(ACCEL_XOUT_H + 12) / GYRO_SCALE
        except OSError as exc:
            self.last_read_error = repr(exc)
            self._read_retry_times.append(time.monotonic())
            time.sleep(0.005)
            with self.lock:
                accel_x = self._read_word(ACCEL_XOUT_H) / ACCEL_SCALE
                accel_y = self._read_word(ACCEL_XOUT_H + 2) / ACCEL_SCALE
                accel_z = self._read_word(ACCEL_XOUT_H + 4) / ACCEL_SCALE

                gyro_x = self._read_word(ACCEL_XOUT_H + 8) / GYRO_SCALE
                gyro_y = self._read_word(ACCEL_XOUT_H + 10) / GYRO_SCALE
                gyro_z = self._read_word(ACCEL_XOUT_H + 12) / GYRO_SCALE

        sample = {
            "time": time.monotonic(),
            "accel_x": accel_x,
            "accel_y": accel_y,
            "accel_z": accel_z,
            "gyro_x": gyro_x - self.gyro_bias_x,
            "gyro_y": gyro_y - self.gyro_bias_y,
            "gyro_z": gyro_z - self.gyro_bias_z
        }

        return sample

    def recent_read_retry_count(self, window_seconds):

        cutoff = time.monotonic() - max(0.0, float(window_seconds))
        return sum(timestamp >= cutoff for timestamp in self._read_retry_times)

    def calibrate_gyro_bias(self):

        # Robot bu cagri sirasinda hareketsiz olmali; ham gyro okumalarinin
        # ortalamasi dinlenme-hali sapmasi olarak alinip sonraki okumalardan
        # cikarilir (read_motion bias'i zaten uyguluyor, o yuzden once sifirla).
        samples = max(1, int(IMU.get("GYRO_BIAS_CALIBRATION_SAMPLES", 60)))
        interval = max(0.0, float(IMU.get("GYRO_BIAS_CALIBRATION_INTERVAL_SECONDS", 0.02)))

        self.gyro_bias_x = 0.0
        self.gyro_bias_y = 0.0
        self.gyro_bias_z = 0.0

        sum_x = 0.0
        sum_y = 0.0
        sum_z = 0.0
        collected = 0

        for _ in range(samples):
            try:
                sample = self.read_motion()
            except OSError:
                continue
            sum_x += sample["gyro_x"]
            sum_y += sample["gyro_y"]
            sum_z += sample["gyro_z"]
            collected += 1
            time.sleep(interval)

        if collected > 0:
            self.gyro_bias_x = sum_x / collected
            self.gyro_bias_y = sum_y / collected
            self.gyro_bias_z = sum_z / collected

        print(
            "IMU GYRO BIAS CALIBRATED: "
            f"x={self.gyro_bias_x:.3f} y={self.gyro_bias_y:.3f} z={self.gyro_bias_z:.3f} "
            f"samples={collected}/{samples}",
            flush=True
        )

        return {
            "gyro_bias_x": round(self.gyro_bias_x, 4),
            "gyro_bias_y": round(self.gyro_bias_y, 4),
            "gyro_bias_z": round(self.gyro_bias_z, 4),
            "samples": collected
        }

    def detect_stuck(self, x, y):

        if not IMU["ENABLED"] or y <= 0:
            self.last_sample = None
            return None

        now = time.monotonic()

        if now - self.last_stuck_time < IMU["STUCK_COOLDOWN_SECONDS"]:
            return None

        sample = self.read_motion()
        previous = self.last_sample
        self.last_sample = sample

        horizontal_accel = math.hypot(
            sample["accel_x"],
            sample["accel_y"]
        )
        gyro_total = math.sqrt(
            sample["gyro_x"] ** 2
            + sample["gyro_y"] ** 2
            + sample["gyro_z"] ** 2
        )

        reasons = []
        accel_delta = None

        if horizontal_accel >= IMU["TILT_ACCEL_G"]:
            reasons.append("tilt")

        if gyro_total >= IMU["UNEXPECTED_GYRO_DPS"]:
            reasons.append("rotation")

        if previous:
            accel_delta = math.sqrt(
                (sample["accel_x"] - previous["accel_x"]) ** 2
                + (sample["accel_y"] - previous["accel_y"]) ** 2
                + (sample["accel_z"] - previous["accel_z"]) ** 2
            )

            if accel_delta >= IMU["IMPACT_ACCEL_DELTA_G"]:
                reasons.append("impact")

        if not reasons:
            return None

        self.last_stuck_time = now
        self.last_sample = None

        return {
            "reasons": reasons,
            "sample": sample,
            "metrics": {
                "horizontal_accel": horizontal_accel,
                "gyro_total": gyro_total,
                "accel_delta": accel_delta
            },
            "command": {
                "x": x,
                "y": y
            }
        }

    def _read_word(self, register):

        high = self.bus.read_byte_data(
            self.address,
            register
        )
        low = self.bus.read_byte_data(
            self.address,
            register + 1
        )
        value = (high << 8) | low

        if value >= 0x8000:
            value -= 0x10000

        return value

    def close(self):

        self.bus.close()