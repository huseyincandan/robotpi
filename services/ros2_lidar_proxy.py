import json
import time
from pathlib import Path


class Ros2LidarProxyService:

    def __init__(self, scan_file, sector_deg=30.0, angle_offset_deg=0.0, max_age_seconds=1.5):

        self.scan_file = Path(scan_file)
        self.sector = float(sector_deg)
        self._angle_offset_deg = self._normalize_degrees(angle_offset_deg)
        self.max_age_seconds = float(max_age_seconds)
        self._last_error = ""
        self._cache = None
        self._cache_mtime = None

    def _normalize_degrees(self, value):

        normalized = float(value) % 360.0

        if normalized > 180.0:
            normalized -= 360.0

        return normalized

    def get_angle_offset_deg(self):

        return float(self._angle_offset_deg)

    def set_angle_offset_deg(self, offset_deg):

        self._angle_offset_deg = self._normalize_degrees(offset_deg)
        return float(self._angle_offset_deg)

    def _read_scan_payload(self):

        if not self.scan_file.exists() or not self.scan_file.is_file():
            return None

        try:
            stat = self.scan_file.stat()
            mtime = float(stat.st_mtime)

            if self._cache is not None and self._cache_mtime == mtime:
                return self._cache

            payload = json.loads(self.scan_file.read_text(encoding="utf-8"))
            self._cache = payload
            self._cache_mtime = mtime
            self._last_error = ""
            return payload
        except Exception as exc:
            self._last_error = repr(exc)
            return None

    def _is_stale(self, payload, mtime):

        if self.max_age_seconds <= 0:
            return False

        updated_at = payload.get("updated_at") if isinstance(payload, dict) else None

        if updated_at is not None:
            try:
                age_seconds = time.time() - float(updated_at)

                if age_seconds > self.max_age_seconds:
                    return True
            except Exception:
                pass

        if mtime is not None:
            try:
                age_seconds = time.time() - float(mtime)

                if age_seconds > self.max_age_seconds:
                    return True
            except Exception:
                pass

        return False

    def _apply_offset(self, angle_deg):

        return (float(angle_deg) + float(self._angle_offset_deg)) % 360.0

    def _sector_min(self, points, center_deg):

        minimum = None
        half_sector = float(self.sector) / 2.0

        for angle_deg, distance_cm in points:
            diff = (float(angle_deg) - center_deg + 540.0) % 360.0 - 180.0

            if abs(diff) > half_sector:
                continue

            if minimum is None or float(distance_cm) < minimum:
                minimum = float(distance_cm)

        return minimum

    def get_scan_points(self):

        data = self.get_distances_cm()

        if not data:
            return None

        return data.get("scan_points") or []

    def get_distances_cm(self):

        payload = self._read_scan_payload()

        if not payload:
            return None

        try:
            mtime = float(self.scan_file.stat().st_mtime)
        except Exception:
            mtime = None

        if self._is_stale(payload, mtime):
            self._last_error = "stale_scan"
            return None

        raw_points = payload.get("scan_points") or []
        transformed_points = []

        for item in raw_points:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue

            angle_deg = self._apply_offset(item[0])
            distance_cm = float(item[1])
            transformed_points.append((angle_deg, distance_cm))

        front_cm = self._sector_min(transformed_points, 0.0)
        left_cm = self._sector_min(transformed_points, 90.0)
        right_cm = self._sector_min(transformed_points, 270.0)

        return {
            "front_cm": front_cm,
            "left_cm": left_cm,
            "right_cm": right_cm,
            "scan_points": transformed_points,
            "timestamp": float(payload.get("timestamp", time.monotonic())),
            "updated_at": float(payload.get("updated_at", time.time()))
        }

    def is_ready(self):

        return self.get_distances_cm() is not None

    def status(self):

        data = self.get_distances_cm()

        if data:
            return "ready"

        if self._last_error:
            return "error"

        return "starting"

    def close(self):

        return
