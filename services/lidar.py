import threading
import time
import types
import json
from pathlib import Path

from config import LIDAR

try:
    from rplidar import RPLidar
except Exception:
    RPLidar = None


class LidarService:

    def __init__(self):

        self.enabled = bool(LIDAR.get("ENABLED", True))
        self.port = LIDAR.get("PORT", "/dev/ttyUSB0")
        self.baudrate = int(LIDAR.get("BAUDRATE", 460800))
        self.min_valid_cm = float(LIDAR.get("MIN_VALID_CM", 12))
        self.max_valid_cm = float(LIDAR.get("MAX_VALID_CM", 550))
        self.sector = float(LIDAR.get("SCAN_SECTOR_DEGREES", 30))
        self.angle_offset_deg = float(LIDAR.get("ANGLE_OFFSET_DEGREES", 0.0))
        self.reconnect_seconds = float(LIDAR.get("RECONNECT_SECONDS", 2.0))
        self.disable_pwm_start = bool(LIDAR.get("DISABLE_PWM_START", True))
        self.offset_state_file = Path(
            LIDAR.get("OFFSET_STATE_FILE", "output/lidar/offset.json")
        )

        if not self.offset_state_file.is_absolute():
            self.offset_state_file = Path.cwd() / self.offset_state_file

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._lidar = None
        self._last_error = ""
        self._latest = {
            "front_cm": None,
            "left_cm": None,
            "right_cm": None,
            "scan_points": [],
            "timestamp": 0.0
        }

        self._load_persisted_offset()

        if not self.enabled:
            self._last_error = "disabled"
            return

        if RPLidar is None:
            self._last_error = "rplidar_import_failed"
            return

        self._thread = threading.Thread(
            target=self._worker,
            daemon=True
        )
        self._thread.start()

    def get_angle_offset_deg(self):

        with self._lock:
            return float(self.angle_offset_deg)

    def set_angle_offset_deg(self, offset_deg):

        normalized = float(offset_deg) % 360.0

        if normalized > 180.0:
            normalized -= 360.0

        with self._lock:
            self.angle_offset_deg = normalized

        self._save_persisted_offset(normalized)

        return normalized

    def _load_persisted_offset(self):

        try:
            if not self.offset_state_file.exists() or not self.offset_state_file.is_file():
                return

            payload = json.loads(self.offset_state_file.read_text(encoding="utf-8"))
            persisted = payload.get("angle_offset_deg")

            if persisted is None:
                return

            normalized = float(persisted) % 360.0

            if normalized > 180.0:
                normalized -= 360.0

            self.angle_offset_deg = normalized

            print(
                "LIDAR OFFSET LOADED:",
                round(normalized, 2),
                flush=True
            )

        except Exception as exc:
            print(
                "LIDAR OFFSET LOAD ERROR:",
                repr(exc),
                flush=True
            )

    def _save_persisted_offset(self, offset_deg):

        try:
            self.offset_state_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "angle_offset_deg": float(offset_deg),
                "saved_at": time.time()
            }
            self.offset_state_file.write_text(
                json.dumps(payload, ensure_ascii=True),
                encoding="utf-8"
            )

        except Exception as exc:
            print(
                "LIDAR OFFSET SAVE ERROR:",
                repr(exc),
                flush=True
            )

    def _connect(self):

        self._lidar = RPLidar(
            self.port,
            baudrate=self.baudrate,
            timeout=1
        )

        if self.disable_pwm_start:
            def _start_motor_no_pwm(lidar_self):
                lidar_self._serial.setDTR(False)
                lidar_self.motor_running = True

            self._lidar.start_motor = types.MethodType(
                _start_motor_no_pwm,
                self._lidar
            )

        original_get_health = self._lidar.get_health

        def _get_health_resilient(lidar_self):
            try:
                if lidar_self._serial.inWaiting() > 0:
                    lidar_self.clean_input()
            except Exception:
                pass

            return original_get_health()

        self._lidar.get_health = types.MethodType(
            _get_health_resilient,
            self._lidar
        )

    def _disconnect(self):

        if not self._lidar:
            return

        try:
            self._lidar.stop()
        except Exception:
            pass

        try:
            self._lidar.stop_motor()
        except Exception:
            pass

        try:
            self._lidar.disconnect()
        except Exception:
            pass

        self._lidar = None

    def _update_scan(self, scan):

        front_min = None
        left_min = None
        right_min = None
        scan_points = []

        left_center = 90.0
        right_center = 270.0
        half_sector = self.sector / 2.0

        for (_, angle_deg, distance_mm) in scan:
            distance_cm = float(distance_mm) / 10.0

            if distance_cm < self.min_valid_cm or distance_cm > self.max_valid_cm:
                continue

            angle = (float(angle_deg) + self.angle_offset_deg) % 360.0
            scan_points.append((angle, distance_cm))

            if angle <= half_sector or angle >= (360.0 - half_sector):
                if front_min is None or distance_cm < front_min:
                    front_min = distance_cm

            if abs(angle - left_center) <= half_sector:
                if left_min is None or distance_cm < left_min:
                    left_min = distance_cm

            if abs(angle - right_center) <= half_sector:
                if right_min is None or distance_cm < right_min:
                    right_min = distance_cm

        with self._lock:
            self._latest = {
                "front_cm": front_min,
                "left_cm": left_min,
                "right_cm": right_min,
                "scan_points": scan_points,
                "timestamp": time.monotonic()
            }

    def _worker(self):

        while not self._stop_event.is_set():
            try:
                self._connect()

                try:
                    self._lidar.clean_input()
                except Exception:
                    pass

                for scan in self._lidar.iter_scans(max_buf_meas=1000):
                    if self._stop_event.is_set():
                        break

                    self._update_scan(scan)

                self._last_error = ""

            except Exception as exc:
                self._last_error = repr(exc)
                print(
                    "LIDAR ERROR:",
                    self._last_error,
                    flush=True
                )
                time.sleep(self.reconnect_seconds)

            finally:
                self._disconnect()

    def get_distances_cm(self):

        with self._lock:
            data = dict(self._latest)

        if data["timestamp"] <= 0:
            return None

        return data

    def get_scan_points(self):

        data = self.get_distances_cm()

        if not data:
            return None

        return data.get("scan_points") or []

    def is_ready(self):

        return self.get_distances_cm() is not None

    def status(self):

        if not self.enabled:
            return "disabled"

        if RPLidar is None:
            return "import_error"

        if self.is_ready():
            return "ready"

        if self._last_error:
            return "error"

        return "starting"

    def close(self):

        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

        self._disconnect()
