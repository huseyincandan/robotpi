import asyncio
import errno
import glob
import termios
import threading
import time

import serial

from config import IMU
from config import MOTOR
from config import MOTOR_SERIAL
from config import ULTRASONIC


class MotorSerialError(RuntimeError):
    pass


class MotorService:

    def __init__(self, distance=None, imu=None, lidar=None):

        self.distance = distance
        self.imu = imu
        self.lidar = lidar
        self.blocked = False
        self.power_fault = False
        self.last_power_fault = None
        self.sensor_fault = False
        self.last_sensor_fault = None
        self.last_block_reason = None
        self.last_imu_event = None
        self.last_drive_source = ""
        self.current_x = 0
        self.current_y = 0
        self.last_obstacle_distance = None
        self.last_distance_error = None
        self.last_requested_x = 0
        self.last_requested_y = 0

        self._serial_lock = threading.Lock()
        self._serial = None
        self._serial_port = None
        self.last_serial_error = None
        self._last_drive_command = None
        self._stop_event = threading.Event()

        # IMU+INA219 artik Pi'de degil, S3'un kendi I2C hattinda (2026-09-06,
        # motor EMI'sinin Pi I2C'sini kilitlemesi yuzunden) - S3 bu verileri
        # UART uzerinden "TELEM ..." satiri olarak gonderiyor, burada onbelleklenir.
        self._telem_lock = threading.Lock()
        self._telem_data = None

        self._open_serial()
        self._handshake()

        self._reader_thread = threading.Thread(
            target=self._serial_reader_loop,
            daemon=True
        )
        self._reader_thread.start()

        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            daemon=True
        )
        self._keepalive_thread.start()

    def set_lidar(self, lidar):

        self.lidar = lidar

    def _candidate_ports(self):

        candidates = []

        configured = MOTOR_SERIAL.get("PORT")
        if configured:
            candidates.append(configured)

        for pattern in MOTOR_SERIAL.get("PORT_CANDIDATES", []):
            for match in sorted(glob.glob(pattern)):
                if match not in candidates:
                    candidates.append(match)

        return candidates

    def _open_serial(self):

        candidates = self._candidate_ports()
        last_exc = None

        for port in candidates:
            try:
                self._serial = serial.Serial(
                    port,
                    baudrate=MOTOR_SERIAL.get("BAUDRATE", 115200),
                    timeout=MOTOR_SERIAL.get("READ_TIMEOUT_SECONDS", 0.05),
                    write_timeout=MOTOR_SERIAL.get("WRITE_TIMEOUT_SECONDS", 0.2)
                )
                self._serial_port = port
                print("MOTOR SERIAL OPEN:", port, flush=True)
                return

            except Exception as exc:
                last_exc = exc

        raise MotorSerialError(
            f"S3 motor serial port not found (tried {candidates}): {last_exc!r}"
        )

    def _handshake(self):

        timeout = float(MOTOR_SERIAL.get("CONNECT_TIMEOUT_SECONDS", 25.0))
        retry_interval = float(MOTOR_SERIAL.get("PING_RETRY_INTERVAL_SECONDS", 0.5))
        deadline = time.monotonic() + timeout

        # S3'un setup() fonksiyonu WiFi baglantisini denerken ~20sn'ye kadar bloklanabilir,
        # bu yuzden ilk PONG cevabi gelene kadar sabirla tekrar deneriz.
        while time.monotonic() < deadline:
            try:
                with self._serial_lock:
                    self._serial.reset_input_buffer()
                    self._serial.write(b"PING\n")
                    self._serial.flush()
                    reply = self._serial.readline().decode("utf-8", "ignore").strip()

                if reply == "PONG":
                    print("MOTOR SERIAL READY:", self._serial_port, flush=True)
                    return

            except Exception as exc:
                self.last_serial_error = exc

            time.sleep(retry_interval)

        raise MotorSerialError(
            f"S3 did not answer PING within {timeout}s on {self._serial_port}"
        )

    def _serial_reader_loop(self):

        while not self._stop_event.is_set():
            try:
                line = self._serial.readline()

            except Exception as exc:
                self.last_serial_error = exc
                time.sleep(0.5)
                continue

            if not line:
                continue

            text = line.decode("utf-8", "ignore").strip()

            if text.startswith("ERR"):
                print("MOTOR SERIAL ERROR REPLY:", text, flush=True)
            elif text.startswith("TELEM "):
                self._parse_telemetry(text)

    def _parse_telemetry(self, text):

        # Beklenen format: "TELEM ax ay az gx gy gz bus_voltage shunt_voltage_mv enc_rl enc_rr"
        # (bkz. MotorEspS3.ino pollTelemetry()) - bozuk/eksik bir satir sessizce
        # atlanir, bir sonraki TELEM satiri zaten yeni veri getirir.
        parts = text.split()

        if len(parts) != 11:
            return

        try:
            values = [float(p) for p in parts[1:]]
        except ValueError:
            return

        with self._telem_lock:
            self._telem_data = {
                "accel_x": values[0],
                "accel_y": values[1],
                "accel_z": values[2],
                "gyro_x": values[3],
                "gyro_y": values[4],
                "gyro_z": values[5],
                "bus_voltage": values[6],
                "shunt_voltage_mv": values[7],
                "enc_rl": int(values[8]),
                "enc_rr": int(values[9]),
                "received_at": time.monotonic()
            }

    def get_telemetry(self, max_age_seconds=1.0):

        with self._telem_lock:
            data = self._telem_data

        if data is None:
            raise TimeoutError("ESP telemetrisi henuz alinmadi")

        if time.monotonic() - data["received_at"] > max_age_seconds:
            raise TimeoutError("ESP telemetrisi bayat (S3 UART baglantisini kontrol et)")

        return data

    def _keepalive_loop(self):

        interval = float(MOTOR_SERIAL.get("KEEPALIVE_INTERVAL_SECONDS", 0.2))

        while not self._stop_event.wait(interval):
            command = self._last_drive_command

            if command is None:
                continue

            vx, omega = command
            self._send_line(f"DRIVE {vx} {omega}")

    def _send_line(self, line):

        payload = (line + "\n").encode("ascii")
        # EINTR ('Interrupted system call') is a transient signal interruption,
        # not a real failure - it was being treated as fatal and silently
        # dropping drive commands, causing the robot to visibly pause every
        # time it fired (the S3 auto-stops ~500ms after the last command).
        # flush() calls termios.tcdrain() under the hood, which raises
        # termios.error (NOT OSError - it only subclasses Exception) on EINTR,
        # so that type must be caught explicitly too or this never retries.
        max_attempts = 3

        for attempt in range(max_attempts):
            try:
                with self._serial_lock:
                    self._serial.write(payload)
                    self._serial.flush()

                self.last_serial_error = None
                return True

            except (OSError, termios.error) as exc:
                exc_errno = getattr(exc, "errno", None)
                if exc_errno is None and exc.args:
                    exc_errno = exc.args[0]
                if exc_errno == errno.EINTR and attempt < max_attempts - 1:
                    continue
                self.last_serial_error = exc
                print("MOTOR SERIAL WRITE ERROR:", repr(exc), flush=True)
                return False

            except Exception as exc:
                self.last_serial_error = exc
                print("MOTOR SERIAL WRITE ERROR:", repr(exc), flush=True)
                return False

        return False

    def _send_drive(self, x, y):

        vx = int(max(-255, min(255, round(y * 2.55))))
        omega = int(max(-255, min(255, round(x * 2.55))))

        sent = self._send_line(f"DRIVE {vx} {omega}")
        self._last_drive_command = (vx, omega)

        return sent

    def _lidar_sector_min(self, points, center_deg, half_sector=15.0):

        minimum = None

        for angle_deg, distance_cm in points:
            diff = (float(angle_deg) - float(center_deg) + 540.0) % 360.0 - 180.0

            if abs(diff) > half_sector:
                continue

            if minimum is None or float(distance_cm) < minimum:
                minimum = float(distance_cm)

        return minimum

    def _sample_lidar_signature(self):

        if not self.lidar:
            return None

        try:
            data = self.lidar.get_distances_cm()
        except Exception:
            return None

        if not data:
            return None

        points = data.get("scan_points") or []
        if not points:
            return None

        centers = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
        signature = {}

        for center in centers:
            signature[center] = self._lidar_sector_min(points, center)

        return {
            "time": time.monotonic(),
            "signature": signature
        }

    def _lidar_min_over_sectors(self, centers_deg):

        sample = self._sample_lidar_signature()
        if not sample:
            return None

        signature = sample["signature"]
        values = [signature[c] for c in centers_deg if signature.get(c) is not None]
        return min(values) if values else None

    def _lidar_rear_distance_for_recovery(self, wide=True):

        # Same diagonal-gap reasoning as the front check above, applied to
        # the rear: min across back + both rear diagonals, not just 180deg.
        # Only meaningful for a backup that also turns (sweeps a wider arc) -
        # a pure straight backup never enters those diagonal cones, so
        # requiring them clear too can falsely block on an object (e.g. a
        # couch the robot is already wedged against sideways) that a real
        # straight retreat would never approach. 2026-08-30 live incident:
        # wide check read 29cm (blocked) while the true 180deg-only reading
        # was 123cm+ clear the whole time - confirmed via /lidar/readings.
        if wide:
            return self._lidar_min_over_sectors([135.0, 180.0, 225.0])

        return self._lidar_min_over_sectors([180.0])

    def _recovery_backup_clear(self, x=0.0):

        rear_cm = self._lidar_rear_distance_for_recovery(wide=abs(x) > 0)
        if rear_cm is None:
            return False, rear_cm

        minimum_clearance = float(
            IMU.get("RECOVERY_BACKUP_MIN_LIDAR_REAR_CM", 45.0)
        )
        return rear_cm >= minimum_clearance, rear_cm

    def rear_motion_clear(self, x=0.0):

        return self._recovery_backup_clear(x=x)

    def _stop_motor(self):

        self._last_drive_command = None
        self._send_line("STOP")
        self.current_x = 0
        self.current_y = 0
        self.last_requested_x = 0
        self.last_requested_y = 0

    def stop(self):

        self._stop_motor()
        self.blocked = False
        self.last_block_reason = None

    def close(self):

        self.stop()
        self._stop_event.set()

        try:
            if self._serial and self._serial.is_open:
                self._serial.close()

        except Exception as exc:
            print("MOTOR SERIAL CLOSE ERROR:", repr(exc), flush=True)

    def drive(
        self,
        x,
        y,
        use_forward_safety=True,
        use_slowdown=True,
        stop_distance_cm=None,
        slow_distance_cm=None,
        minimum_speed_percent=None,
        source=None
    ):

        if source is not None:
            self.last_drive_source = str(source).strip().lower()

        if self.sensor_fault and (abs(float(x)) > 1e-3 or abs(float(y)) > 1e-3):
            self._stop_motor()
            self.blocked = True
            self.last_block_reason = "sensor_fault"
            return False

        self.last_requested_x = x
        self.last_requested_y = y

        max_turn = float(MOTOR.get("MAX_TURN_PERCENT", 100.0))
        if abs(x) > max_turn:
            x = max_turn if x > 0 else -max_turn

        if y > 0:
            if use_forward_safety:
                y = self.safe_forward_speed(
                    y,
                    use_slowdown=use_slowdown,
                    stop_distance_cm=stop_distance_cm,
                    slow_distance_cm=slow_distance_cm,
                    minimum_speed_percent=minimum_speed_percent
                )
            else:
                minimum_speed = (
                    float(minimum_speed_percent)
                    if minimum_speed_percent is not None
                    else float(ULTRASONIC["MIN_FORWARD_SPEED_PERCENT"])
                )

                if y < minimum_speed:
                    y = minimum_speed

        if y is None:
            self.stop()
            self.blocked = True
            self.last_block_reason = "obstacle"
            distance_display = (
                round(self.last_obstacle_distance, 1)
                if self.last_obstacle_distance is not None
                else "unknown"
            )
            print(
                "OBSTACLE STOP:",
                distance_display,
                "cm",
                flush=True
            )
            return False

        self.blocked = False
        self.last_block_reason = None

        # Mixing artik Pi'de degil S3'un skidSteerDrive() fonksiyonunda yapiliyor.
        if not self._send_drive(x, y):
            self.blocked = True
            self.last_block_reason = "serial"
            print("MOTOR SERIAL STOP: command not delivered", flush=True)
            return False

        self.current_x = x
        self.current_y = y

        return True

    def read_distance_centimeters(self):

        if not self.distance:
            self.last_distance_error = None
            return None

        try:
            if hasattr(self.distance, "read_safety_centimeters"):
                centimeters = self.distance.read_safety_centimeters()
            else:
                centimeters = self.distance.read_centimeters()

        except Exception as exc:
            self.last_distance_error = exc
            print(
                "DISTANCE SAFETY ERROR:",
                repr(exc),
                flush=True
            )
            return None

        self.last_distance_error = None
        self.last_obstacle_distance = centimeters

        return centimeters

    def read_distance_observation(self):

        if not self.distance:
            return {
                "distance_cm": None,
                "stable": False,
                "confidence": 0.0,
                "sample_count": 0,
                "spread_cm": None
            }

        try:
            if hasattr(self.distance, "read_observation"):
                observation = self.distance.read_observation()
            else:
                centimeters = self.distance.read_centimeters()
                observation = {
                    "distance_cm": centimeters,
                    "stable": centimeters is not None,
                    "confidence": 1.0 if centimeters is not None else 0.0,
                    "sample_count": 1,
                    "spread_cm": 0.0
                }
        except Exception as exc:
            self.last_distance_error = exc
            return {
                "distance_cm": None,
                "stable": False,
                "confidence": 0.0,
                "sample_count": 0,
                "spread_cm": None
            }

        self.last_distance_error = None
        self.last_obstacle_distance = observation.get("distance_cm")
        return observation

    def safe_forward_speed(
        self,
        speed,
        use_slowdown=True,
        stop_distance_cm=None,
        slow_distance_cm=None,
        minimum_speed_percent=None
    ):

        centimeters = self.read_distance_centimeters()

        if centimeters is None:
            # Fail-safe: when distance is unknown, do not continue forward blindly.
            return None

        stop_distance = (
            float(stop_distance_cm)
            if stop_distance_cm is not None
            else float(ULTRASONIC["STOP_DISTANCE_CM"])
        )
        slow_distance = (
            float(slow_distance_cm)
            if slow_distance_cm is not None
            else float(ULTRASONIC["SLOW_DISTANCE_CM"])
        )

        if centimeters <= stop_distance:
            return None

        if not use_slowdown:
            return float(speed)

        if centimeters >= slow_distance:
            return speed

        ratio = (
            (centimeters - stop_distance)
            / (slow_distance - stop_distance)
        )

        minimum_speed = (
            float(minimum_speed_percent)
            if minimum_speed_percent is not None
            else float(ULTRASONIC["MIN_FORWARD_SPEED_PERCENT"])
        )
        scaled_speed = minimum_speed + (
            abs(speed) - minimum_speed
        ) * ratio

        return min(
            abs(speed),
            max(
                minimum_speed,
                scaled_speed
            )
        )

    def read_imu_stuck_event(self):

        if not self.imu:
            return None

        try:
            event = self.imu.detect_stuck(
                self.current_x,
                self.current_y
            )

        except Exception as exc:
            print(
                "IMU SAFETY ERROR:",
                repr(exc),
                flush=True
            )
            return None

        if not event:
            return None

        self.last_imu_event = event
        self.last_block_reason = "imu"

        print(
            "IMU STUCK:",
            ",".join(event["reasons"]),
            "accel=",
            round(event["sample"]["accel_x"], 2),
            round(event["sample"]["accel_y"], 2),
            round(event["sample"]["accel_z"], 2),
            "gyro=",
            round(event["sample"]["gyro_x"], 1),
            round(event["sample"]["gyro_y"], 1),
            round(event["sample"]["gyro_z"], 1),
            "horizontal=",
            round(event["metrics"]["horizontal_accel"], 2),
            "gyro_total=",
            round(event["metrics"]["gyro_total"], 1),
            "accel_delta=",
            None if event["metrics"]["accel_delta"] is None else round(event["metrics"]["accel_delta"], 2),
            flush=True
        )

        return event

    def _imu_bus_unstable(self):

        if not self.imu or not hasattr(self.imu, "recent_read_retry_count"):
            return False

        window_seconds = float(IMU.get("BUS_RETRY_FAULT_WINDOW_SECONDS", 3.0))
        retry_count = self.imu.recent_read_retry_count(window_seconds)
        threshold = max(1, int(IMU.get("BUS_RETRY_FAULT_COUNT", 2)))
        return retry_count >= threshold

    def stop_for_imu_stuck(self):

        self.stop()
        self.blocked = True
        self.last_block_reason = "imu"

    async def safety_loop(self):

        while True:
            moving = (
                abs(float(self.current_x)) >= 0.5
                or abs(float(self.current_y)) >= 0.5
            )
            if moving and not self.sensor_fault and self._imu_bus_unstable():
                window_seconds = float(IMU.get("BUS_RETRY_FAULT_WINDOW_SECONDS", 3.0))
                self.last_sensor_fault = {
                    "reason": "imu_i2c_retries",
                    "retry_count": self.imu.recent_read_retry_count(window_seconds),
                    "window_seconds": window_seconds,
                    "last_error": getattr(self.imu, "last_read_error", None),
                    "time": time.monotonic()
                }
                self.sensor_fault = True
                self.stop()
                self.blocked = True
                self.last_block_reason = "sensor_fault"
                print("IMU BUS SAFETY TRIP:", self.last_sensor_fault, flush=True)
                await asyncio.sleep(ULTRASONIC["SAFETY_CHECK_INTERVAL_SECONDS"])
                continue

            driving_forward = self.current_y > 0
            driving_backward = self.current_y < 0
            stuck_event = None

            if driving_forward:
                self.drive(
                    self.last_requested_x,
                    self.last_requested_y
                )

                stuck_event = await asyncio.to_thread(
                    self.read_imu_stuck_event
                )

                if stuck_event:
                    self.stop_for_imu_stuck()

            elif driving_backward:
                # Backward driving has no equivalent of forward's continuous
                # ultrasonic re-check baked into drive()/safe_forward_speed(),
                # so mirror it here: re-verify rear clearance and IMU impact
                # every tick (50ms). Does not re-call self.drive() (would
                # extend a manual pulse's lifetime past what the caller
                # intended, unlike forward where re-driving is what keeps a
                # caller-refreshed command alive) - on impact/obstacle this
                # only stops; nav2's own BT recovery (or a human, for manual
                # driving) is responsible for what happens next.
                rear_clear, rear_cm = self.rear_motion_clear(x=self.current_x)
                if not rear_clear:
                    self.stop()
                    self.blocked = True
                    self.last_block_reason = "rear_obstacle"
                    print(
                        "REAR SAFETY STOP (continuous):",
                        "unknown" if rear_cm is None else f"{rear_cm:.1f} cm",
                        flush=True
                    )
                else:
                    backward_stuck_event = await asyncio.to_thread(
                        self.read_imu_stuck_event
                    )

                    if backward_stuck_event:
                        self.stop_for_imu_stuck()

            await asyncio.sleep(
                ULTRASONIC["SAFETY_CHECK_INTERVAL_SECONDS"]
            )