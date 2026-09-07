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


class _ImuMotionMixin:
    """detect_stuck/bias-kalibrasyonu/retry-sayaci mantigi - transporttan (I2C ya
    da ESP UART telemetrisi) bagimsiz, sadece alt siniflarin _read_raw() ile
    saglamasi gereken ham accel/gyro degerlerini kullanir."""

    def _init_motion_state(self):
        self.last_sample = None
        self.last_stuck_time = 0
        self.last_read_error = None
        self._read_retry_times = deque(maxlen=64)
        self._driving_since = None

        self.gyro_bias_x = 0.0
        self.gyro_bias_y = 0.0
        self.gyro_bias_z = 0.0

    def read_motion(self):

        # Motor calisirken PWM gurultusu ile ara sira okuma hatasi olusabiliyor;
        # birkac kez daha denemek genelde gecici hatayi atlatir. Sayaca
        # (recent_read_retry_count -> BUS_RETRY_FAULT_COUNT tetigi) sadece TUM denemeler
        # tukenip kendiliginden duzelmeyen gercek/kalici bir hata eklenir - boylece
        # kendiliginden duzelen tekil glitch'ler guvenlik durdurmasini gereksiz tetiklemez.
        max_attempts = max(1, int(IMU.get("I2C_READ_MAX_ATTEMPTS", 3)))
        last_exc = None
        raw = None

        for attempt in range(max_attempts):
            try:
                raw = self._read_raw()
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
                self.last_read_error = repr(exc)
                if attempt < max_attempts - 1:
                    time.sleep(0.005)

        if last_exc is not None:
            self._read_retry_times.append(time.monotonic())
            raise last_exc

        sample = {
            "time": time.monotonic(),
            "accel_x": raw["accel_x"],
            "accel_y": raw["accel_y"],
            "accel_z": raw["accel_z"],
            "gyro_x": raw["gyro_x"] - self.gyro_bias_x,
            "gyro_y": raw["gyro_y"] - self.gyro_bias_y,
            "gyro_z": raw["gyro_z"] - self.gyro_bias_z
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

        # Impact/tilt/gyro detection itself is direction-agnostic (it only
        # reads real IMU motion vs thresholds) - only skip when truly
        # stationary (y==0). Previously gated on y<=0 (forward-only), which
        # meant an impact while backing up (e.g. a low table leg behind the
        # robot) was never detected at all, no matter how hard it hit.
        if not IMU["ENABLED"] or y == 0:
            self.last_sample = None
            self._driving_since = None
            return None

        now = time.monotonic()

        if self._driving_since is None:
            self._driving_since = now

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

            # Duruştan harekete gecisin ilk anindaki sasi sarsintisi (tekerlek
            # statik surtunmeyi yenerken) gercek carpma degilken buyuk bir
            # accel_delta uretebiliyor (bkz. IMPACT_ACCEL_DELTA_G yorumu) -
            # sadece bu kisa baslangic penceresinde "impact" nedenini gormezden gel.
            startup_elapsed = (
                now - self._driving_since if self._driving_since is not None else None
            )
            in_startup_grace = (
                startup_elapsed is not None
                and startup_elapsed < IMU["IMPACT_STARTUP_GRACE_SECONDS"]
            )

            if accel_delta >= IMU["IMPACT_ACCEL_DELTA_G"] and not in_startup_grace:
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


class Mpu6050Service(_ImuMotionMixin):
    """Pi'nin kendi I2C hattina dogrudan bagli MPU6050 - artik kullanilmiyor
    (2026-09-06: IMU+INA219, motor EMI'sinin Pi I2C'sini kilitlemesi yuzunden
    S3'un kendi I2C'sine tasindi, bkz. EspImuBridge), ama donanim tekrar Pi'ye
    baglanirsa diye korunuyor."""

    def __init__(self):

        self.bus_number = IMU["BUS"]
        self.address = IMU["ADDRESS"]
        self.lock = I2C_BUS_LOCK
        self.bus = SMBus(self.bus_number)
        self._init_motion_state()

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
        # robot tamamen dururken bile bu sapmayi surekli entegre edip driftliyor.
        self.calibrate_gyro_bias()

    def _read_raw(self):

        with self.lock:
            accel_x = self._read_word(ACCEL_XOUT_H) / ACCEL_SCALE
            accel_y = self._read_word(ACCEL_XOUT_H + 2) / ACCEL_SCALE
            accel_z = self._read_word(ACCEL_XOUT_H + 4) / ACCEL_SCALE

            gyro_x = self._read_word(ACCEL_XOUT_H + 8) / GYRO_SCALE
            gyro_y = self._read_word(ACCEL_XOUT_H + 10) / GYRO_SCALE
            gyro_z = self._read_word(ACCEL_XOUT_H + 12) / GYRO_SCALE

        return {
            "accel_x": accel_x,
            "accel_y": accel_y,
            "accel_z": accel_z,
            "gyro_x": gyro_x,
            "gyro_y": gyro_y,
            "gyro_z": gyro_z
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


class EspImuBridge(_ImuMotionMixin):
    """IMU artik Pi'de degil, ESP32-S3'un kendi I2C hattinda (bkz.
    MotorEspS3.ino) - S3, MPU6050'yi okuyup UART uzerinden "TELEM ..." satiri
    olarak Pi'ye aktariyor (motor.get_telemetry()). UART, I2C'nin aksine tek
    bayt hatasinda tum hatti kilitlemedigi icin motor EMI'sine karsi daha
    dayanikli - bkz. 2026-09-06 I2C kilitlenme arastirmasi (repo notlari)."""

    def __init__(self, motor):

        self.motor = motor
        self._init_motion_state()

        # Baslangicta bir okuma deneyip telemetri gercekten geliyor mu diye
        # dogrula - S3 henuz ilk TELEM satirini gondermediyse bu kisa sureli
        # basarisiz olabilir, kalibrasyon zaten hatalari sessizce atlar.
        print("IMU READY: source=esp_serial (S3 uzerinden UART telemetri)", flush=True)
        self.calibrate_gyro_bias()

    def _read_raw(self):

        max_age = float(IMU.get("ESP_TELEM_MAX_AGE_SECONDS", 1.0))
        telemetry = self.motor.get_telemetry(max_age_seconds=max_age)

        return {
            "accel_x": telemetry["accel_x"],
            "accel_y": telemetry["accel_y"],
            "accel_z": telemetry["accel_z"],
            "gyro_x": telemetry["gyro_x"],
            "gyro_y": telemetry["gyro_y"],
            "gyro_z": telemetry["gyro_z"]
        }

    def close(self):

        return