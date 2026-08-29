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

    def __init__(self, distance=None, imu=None, speech=None, lidar=None):

        self.distance = distance
        self.imu = imu
        self.lidar = lidar
        self.speech = speech
        self.speech_lock = threading.Lock()
        self.blocked = False
        self.power_fault = False
        self.last_power_fault = None
        self.sensor_fault = False
        self.last_sensor_fault = None
        self.recovering = False
        self.last_recovery_finished_at = None
        self.recovery_direction = 1
        self.recovery_gave_up = False
        self.last_block_reason = None
        self.last_imu_event = None
        self.current_x = 0
        self.current_y = 0
        self.last_obstacle_distance = None
        self.last_distance_error = None
        self.last_requested_x = 0
        self.last_requested_y = 0
        self.last_lidar_motion_score = None
        self.last_lidar_motion_verified = None
        self._lidar_verify_last_sample = None
        self._lidar_verify_miss_count = 0
        self._lidar_verify_stall_count = 0
        self._lidar_verify_boost_percent = 0.0
        self._lidar_verify_last_log = 0.0
        self._forward_block_since = None
        self._recovery_latch_clear_samples = 0

        self._serial_lock = threading.Lock()
        self._serial = None
        self._serial_port = None
        self.last_serial_error = None
        self._last_drive_command = None
        self._stop_event = threading.Event()
        self._recovery_cancel_event = threading.Event()

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

    def _clamp_min_effective(self, value, minimum):

        if abs(value) <= 0:
            return 0.0

        if abs(value) >= minimum:
            return float(value)

        return float(minimum if value > 0 else -minimum)

    def _apply_minimum_effective_command(self, x, y):

        min_linear = float(MOTOR.get("MIN_EFFECTIVE_LINEAR_PERCENT", 12.0))
        min_turn = float(MOTOR.get("MIN_EFFECTIVE_TURN_PERCENT", 8.0))
        boost = max(0.0, float(self._lidar_verify_boost_percent))

        min_linear += boost
        min_turn += boost * 0.7

        # Sag arka teker patinaj yaptigi icin sag donusler (x>0) ayni yuzdede
        # sol donuse gore cok daha az torka ulasiyor - taban yuzdeyi yukselt.
        if x > 0:
            min_turn += float(MOTOR.get("RIGHT_TURN_EXTRA_MIN_TURN_PERCENT", 0.0))

        y = self._clamp_min_effective(y, min_linear)

        if abs(x) > 0:
            x = self._clamp_min_effective(x, min_turn)

        return x, y

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

    def _lidar_front_distance_for_recovery(self):

        if not self.lidar:
            return None

        try:
            data = self.lidar.get_distances_cm() or {}
            front_cm = data.get("front_cm")
        except Exception:
            return None

        if front_cm is None:
            return None

        return float(front_cm)

    def _lidar_rear_distance_for_recovery(self):

        sample = self._sample_lidar_signature()
        if not sample:
            return None

        rear_cm = sample["signature"].get(180.0)
        return None if rear_cm is None else float(rear_cm)

    def _recovery_backup_clear(self):

        rear_cm = self._lidar_rear_distance_for_recovery()
        if rear_cm is None:
            return False, rear_cm

        minimum_clearance = float(
            IMU.get("RECOVERY_BACKUP_MIN_LIDAR_REAR_CM", 45.0)
        )
        return rear_cm >= minimum_clearance, rear_cm

    def rear_motion_clear(self):

        return self._recovery_backup_clear()

    def _preferred_recovery_turn_direction(self):

        sample = self._sample_lidar_signature()
        if sample:
            left_cm = sample["signature"].get(90.0)
            right_cm = sample["signature"].get(270.0)
            if left_cm is not None and right_cm is not None:
                direction = -1 if float(left_cm) > float(right_cm) else 1
                print(
                    "RECOVERY OPEN SIDE:",
                    f"left={float(left_cm):.1f}cm",
                    f"right={float(right_cm):.1f}cm",
                    "turn=left" if direction < 0 else "turn=right",
                    flush=True
                )
                return direction

        direction = self.recovery_direction
        self.recovery_direction *= -1
        return direction

    def _lidar_front_clear_for_recovery(self):

        front_cm = self._lidar_front_distance_for_recovery()
        if front_cm is None:
            return False

        minimum_clearance = float(
            MOTOR.get("RECOVERY_STRAIGHT_PUSH_MIN_LIDAR_FRONT_CM", 70.0)
        )
        return front_cm >= minimum_clearance

    def _threshold_push_allowed(self, block_reason, recovery_context):

        context = recovery_context or {}
        lidar_front_cm = context.get("lidar_front_cm")
        ultrasonic_cm = context.get("ultrasonic_cm")
        if (
            lidar_front_cm is None
            or ultrasonic_cm is None
            or not bool(context.get("ultrasonic_stable", False))
        ):
            return False

        stop_distance_cm = float(ULTRASONIC.get("STOP_DISTANCE_CM", 35.0))
        if float(ultrasonic_cm) <= stop_distance_cm:
            return False

        minimum_lidar_cm = float(
            MOTOR.get("RECOVERY_THRESHOLD_MIN_LIDAR_FRONT_CM", 45.0)
        )
        minimum_disagreement_cm = float(
            MOTOR.get("RECOVERY_THRESHOLD_SENSOR_GAP_CM", 10.0)
        )
        minimum_ultrasonic_cm = float(
            MOTOR.get("RECOVERY_THRESHOLD_MIN_ULTRASONIC_CM", 15.0)
        )
        return (
            float(ultrasonic_cm) >= max(minimum_ultrasonic_cm, stop_distance_cm)
            and float(lidar_front_cm) >= minimum_lidar_cm
            and (float(lidar_front_cm) - float(ultrasonic_cm)) >= minimum_disagreement_cm
        )

    def _verify_motion_with_lidar(self, x, y):

        if not bool(MOTOR.get("LIDAR_VERIFY_ENABLED", True)):
            return

        if abs(x) < 1e-3 and abs(y) < 1e-3:
            self._lidar_verify_last_sample = None
            self._lidar_verify_miss_count = 0
            self._lidar_verify_stall_count = 0
            self.last_lidar_motion_score = None
            self.last_lidar_motion_verified = None
            return

        current = self._sample_lidar_signature()

        if not current:
            return

        previous = self._lidar_verify_last_sample

        if not previous:
            self._lidar_verify_last_sample = current
            return

        interval = float(MOTOR.get("LIDAR_VERIFY_INTERVAL_SECONDS", 0.35))
        if (current["time"] - previous["time"]) < interval:
            return

        self._lidar_verify_last_sample = current

        deltas = []

        for center, current_value in current["signature"].items():
            previous_value = previous["signature"].get(center)

            if current_value is None or previous_value is None:
                continue

            deltas.append(abs(float(current_value) - float(previous_value)))

        if not deltas:
            return

        score = sum(deltas) / float(len(deltas))
        turn_dominant = abs(x) > abs(y)
        threshold = float(
            MOTOR.get(
                "LIDAR_VERIFY_MIN_DELTA_CM_TURN" if turn_dominant else "LIDAR_VERIFY_MIN_DELTA_CM_LINEAR",
                1.8 if turn_dominant else 1.2
            )
        )

        verified = score >= threshold

        self.last_lidar_motion_score = score
        self.last_lidar_motion_verified = verified

        if verified:
            self._lidar_verify_miss_count = 0
            # A single noisy lidar sample (reflection glitch, jitter) can
            # exceed the small verify threshold even while genuinely stuck -
            # observed scores of 8-34cm with near-zero real displacement.
            # Decay the stall count instead of snapping it to 0, so one blip
            # doesn't erase a real, sustained stall's progress toward the
            # lidar-stall recovery trigger.
            self._lidar_verify_stall_count = max(0, self._lidar_verify_stall_count - 4)
            self._lidar_verify_boost_percent = max(0.0, self._lidar_verify_boost_percent - 0.5)
            return

        self._lidar_verify_miss_count += 1
        self._lidar_verify_stall_count += 1
        boost_after = int(MOTOR.get("LIDAR_VERIFY_CONSECUTIVE_MISSES_TO_BOOST", 3))

        if self._lidar_verify_miss_count >= max(1, boost_after):
            step = float(MOTOR.get("LIDAR_VERIFY_BOOST_STEP_PERCENT", 2.0))
            boost_max = float(MOTOR.get("LIDAR_VERIFY_BOOST_MAX_PERCENT", 12.0))
            self._lidar_verify_boost_percent = min(
                boost_max,
                self._lidar_verify_boost_percent + step
            )
            self._lidar_verify_miss_count = 0

            now = time.monotonic()
            if now - self._lidar_verify_last_log > 1.0:
                self._lidar_verify_last_log = now
                print(
                    "LIDAR VERIFY: low motion detected, boosting minimum drive",
                    f"score={score:.2f}",
                    f"threshold={threshold:.2f}",
                    f"boost={self._lidar_verify_boost_percent:.1f}%",
                    flush=True
                )

    def notify(self, text):

        if not self.speech or not IMU["VOICE_NOTIFICATIONS"]:
            return

        threading.Thread(
            target=self._notify_worker,
            args=(text,),
            daemon=True
        ).start()

    def _notify_worker(self, text):

        if not self.speech_lock.acquire(blocking=False):
            return

        try:
            self.speech.say_local(
                text
            )

        except Exception as exc:
            print(
                "RECOVERY VOICE ERROR:",
                repr(exc),
                flush=True
            )

        finally:
            self.speech_lock.release()

    def _stop_motor(self):

        self._last_drive_command = None
        self._send_line("STOP")
        self.current_x = 0
        self.current_y = 0
        self.last_requested_x = 0
        self.last_requested_y = 0

    def stop(self):

        self._recovery_cancel_event.set()
        self._stop_motor()
        self.clear_forward_block()
        self.recovery_gave_up = False
        self._recovery_latch_clear_samples = 0
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
        minimum_speed_percent=None
    ):

        if self.sensor_fault and (abs(float(x)) > 1e-3 or abs(float(y)) > 1e-3):
            self._stop_motor()
            self.blocked = True
            self.last_block_reason = "sensor_fault"
            return False

        if self.recovery_gave_up and not self.recovering:
            if y > 0 and self._recovery_latch_forward_clear():
                print("RECOVERY LATCH CLEARED: forward path confirmed clear", flush=True)
                self.rearm_recovery()
            else:
                self._stop_motor()
                self.blocked = True
                self.last_block_reason = "recovery_gave_up"
                return False

        if not self.recovering:
            self._recovery_cancel_event.clear()

        self.last_requested_x = x
        self.last_requested_y = y

        x, y = self._apply_minimum_effective_command(x, y)

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
            self.note_forward_block()
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
        self._verify_motion_with_lidar(x, y)

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

    def is_forward_blocked(self):

        centimeters = self.read_distance_centimeters()

        if centimeters is None:
            return True

        return centimeters <= ULTRASONIC["STOP_DISTANCE_CM"]

    def is_lidar_motion_stalled(self):

        if self.recovering or not bool(MOTOR.get("LIDAR_STALL_RECOVERY_ENABLED", False)):
            return False

        boost_max = float(MOTOR.get("LIDAR_VERIFY_BOOST_MAX_PERCENT", 25.0))
        stall_threshold = int(MOTOR.get("LIDAR_VERIFY_STALL_MISSES_TO_RECOVER", 8))

        return (
            self._lidar_verify_boost_percent >= boost_max
            and self._lidar_verify_stall_count >= stall_threshold
        )

    def note_forward_block(self):

        if self._forward_block_since is None:
            self._forward_block_since = time.monotonic()

    def clear_forward_block(self):

        self._forward_block_since = None

    def rearm_recovery(self):

        self.recovery_gave_up = False
        self._recovery_latch_clear_samples = 0
        self.blocked = False
        self.last_block_reason = None
        self.clear_forward_block()

    def _recovery_latch_forward_clear(self):

        ultrasonic = self.read_distance_observation()
        ultrasonic_cm = ultrasonic.get("distance_cm")
        lidar_front_cm = self._lidar_front_distance_for_recovery()
        minimum_ultrasonic_cm = float(
            MOTOR.get("RECOVERY_LATCH_CLEAR_ULTRASONIC_CM", 50.0)
        )
        minimum_lidar_cm = float(
            MOTOR.get("RECOVERY_STRAIGHT_PUSH_MIN_LIDAR_FRONT_CM", 70.0)
        )

        clear = (
            ultrasonic_cm is not None
            and bool(ultrasonic.get("stable", False))
            and lidar_front_cm is not None
            and float(ultrasonic_cm) >= minimum_ultrasonic_cm
            and float(lidar_front_cm) >= minimum_lidar_cm
        )
        if clear:
            self._recovery_latch_clear_samples += 1
        else:
            self._recovery_latch_clear_samples = 0

        required_samples = int(
            MOTOR.get("RECOVERY_LATCH_CLEAR_CONSECUTIVE_SAMPLES", 5)
        )
        return self._recovery_latch_clear_samples >= max(1, required_samples)

    def is_forward_block_stalled(self):

        if self.recovering or self.recovery_gave_up or self._forward_block_since is None:
            return False

        stall_seconds = float(MOTOR.get("ULTRASONIC_STALL_SECONDS_TO_RECOVER", 6.0))

        return (time.monotonic() - self._forward_block_since) >= stall_seconds

    def read_imu_stuck_event(self, allow_recovery=False):

        if not self.imu or (self.recovering and not allow_recovery):
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

    async def recover_from_stuck(self, stop_event=None):

        return await asyncio.to_thread(
            self.recover_until_clear,
            stop_event
        )

    def recover_until_clear(self, stop_event=None):

        if self.recovering:
            return False

        max_seconds = IMU["RECOVERY_MAX_SECONDS"]
        start_time = time.monotonic()
        cleared = False
        self.recovering = True
        self._recovery_cancel_event.clear()
        self.blocked = True
        self.recovery_gave_up = False
        block_reason = self.last_block_reason or "imu"
        recovery_context = {
            "ultrasonic_cm": self.last_obstacle_distance,
            "lidar_front_cm": self._lidar_front_distance_for_recovery()
        }
        last_voice_attempt = 0

        try:
            attempt = 0
            print(
                "RECOVERY START:",
                block_reason,
                flush=True
            )
            self.notify(
                IMU["VOICE_STUCK_TEXT"]
            )

            while time.monotonic() - start_time < max_seconds:
                if self._recovery_cancelled(stop_event):
                    break

                attempt += 1

                now = time.monotonic()

                if now - last_voice_attempt >= IMU["VOICE_ATTEMPT_INTERVAL_SECONDS"]:
                    last_voice_attempt = now
                    self.notify(
                        IMU["VOICE_ATTEMPT_TEXT"]
                    )

                if not self.recover_once(
                    attempt,
                    stop_event,
                    block_reason,
                    recovery_context
                ):
                    break

                if self._recovery_cancelled(stop_event):
                    break

                if block_reason in {"forward_block_stall", "obstacle"} and self.is_forward_blocked():
                    cleared = True
                    print(
                        "RECOVERY REPLAN: forward remains blocked after escape maneuver",
                        flush=True
                    )
                    break

                if self.test_recovery_clear(stop_event):
                    cleared = True
                    print(
                        "RECOVERY CLEAR:",
                        attempt,
                        flush=True
                    )
                    self.notify(
                        IMU["VOICE_CLEAR_TEXT"]
                    )
                    break

            cancelled = self._recovery_cancelled(stop_event)
            if not cleared and not cancelled:
                self.recovery_gave_up = True
                print(
                    "RECOVERY GIVE UP:",
                    round(time.monotonic() - start_time, 1),
                    "seconds",
                    flush=True
                )
                self.notify(
                    IMU["VOICE_GIVE_UP_TEXT"]
                )
            elif cancelled:
                self.recovery_gave_up = False

            return cleared

        finally:
            self._stop_motor()
            self.blocked = not cleared
            self.last_block_reason = None if cleared else block_reason
            self.last_recovery_finished_at = time.monotonic()
            self.recovering = False

            if cleared:
                self.clear_forward_block()

    def _recovery_cancelled(self, stop_event=None):

        return self._recovery_cancel_event.is_set() or (
            stop_event is not None and stop_event.is_set()
        )

    def _recovery_wait(self, seconds, stop_event=None):

        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            if self._recovery_cancelled(stop_event):
                return False
            if (
                self.recovering
                and self.current_y > 0
                and self.read_imu_stuck_event(allow_recovery=True)
            ):
                self._stop_motor()
                self.blocked = True
                self.last_block_reason = "imu"
                return False
            remaining = deadline - time.monotonic()
            self._recovery_cancel_event.wait(min(0.05, max(0.0, remaining)))
        return not self._recovery_cancelled(stop_event)

    def _run_smooth_recovery_turn(self, target_percent, hold_seconds, stop_event=None):

        target_percent = float(target_percent)
        hold_percent = min(
            abs(target_percent),
            float(IMU.get("RECOVERY_TURN_HOLD_SPEED", abs(target_percent)))
        )
        breakaway_seconds = min(
            max(0.0, float(hold_seconds)),
            max(0.0, float(IMU.get("RECOVERY_TURN_BREAKAWAY_SECONDS", 0.20)))
        )
        ramp_step = max(1.0, float(IMU.get("RECOVERY_TURN_RAMP_STEP_PERCENT", 5.0)))
        ramp_interval = max(0.02, float(IMU.get("RECOVERY_TURN_RAMP_INTERVAL_SECONDS", 0.08)))
        direction = 1.0 if target_percent >= 0 else -1.0
        speed = 0.0

        while speed < abs(target_percent):
            if self._recovery_cancelled(stop_event):
                return False
            speed = min(abs(target_percent), speed + ramp_step)
            self.drive(direction * speed, 0)
            if not self._recovery_wait(ramp_interval, stop_event):
                return False

        if not self._recovery_wait(breakaway_seconds, stop_event):
            return False

        while speed > hold_percent:
            if self._recovery_cancelled(stop_event):
                return False
            speed = max(hold_percent, speed - ramp_step)
            self.drive(direction * speed, 0)
            if not self._recovery_wait(ramp_interval, stop_event):
                return False

        remaining_hold = max(0.0, float(hold_seconds) - breakaway_seconds)
        if not self._recovery_wait(remaining_hold, stop_event):
            return False

        while speed > 0.0:
            if self._recovery_cancelled(stop_event):
                return False
            speed = max(0.0, speed - ramp_step)
            if speed > 0.0:
                self.drive(direction * speed, 0)
            else:
                self._stop_motor()
            if not self._recovery_wait(ramp_interval, stop_event):
                return False

        return True

    def recover_once(
        self,
        attempt,
        stop_event=None,
        block_reason="imu",
        recovery_context=None
    ):

        self._stop_motor()
        if not self._recovery_wait(IMU["RECOVERY_PAUSE_SECONDS"], stop_event):
            return False

        backup_seconds = float(IMU["RECOVERY_BACKUP_SECONDS"])
        max_backup_seconds = float(IMU.get("RECOVERY_BACKUP_MAX_SECONDS", 1.6))
        backup_tries = int(IMU.get("RECOVERY_BACKUP_MAX_TRIES", 3))
        max_backup_speed = float(IMU.get("RECOVERY_BACKUP_SPEED_MAX", 80.0))
        # Escalate the starting backup power across recovery attempts too,
        # not just within a single attempt's retries - a stubborn stall
        # (e.g. a sock caught under a wheel) needs more force over time.
        backup_speed = min(
            float(IMU["RECOVERY_BACKUP_SPEED"]) * (1 + (attempt - 1) * 0.15),
            max_backup_speed
        )

        for backup_try in range(max(1, backup_tries)):
            if self._recovery_cancelled(stop_event):
                return False

            backup_clear, rear_cm = self._recovery_backup_clear()
            if not backup_clear:
                print(
                    "RECOVERY BACKUP SKIPPED: rear clearance",
                    "unknown" if rear_cm is None else f"{rear_cm:.1f} cm",
                    flush=True
                )
                break

            self.drive(
                0,
                -backup_speed
            )
            backup_deadline = time.monotonic() + backup_seconds
            while time.monotonic() < backup_deadline:
                if self._recovery_cancelled(stop_event):
                    return False

                backup_clear, rear_cm = self._recovery_backup_clear()
                if not backup_clear:
                    self._stop_motor()
                    print(
                        "RECOVERY BACKUP STOP: rear clearance",
                        "unknown" if rear_cm is None else f"{rear_cm:.1f} cm",
                        flush=True
                    )
                    break

                if not self._recovery_wait(0.05, stop_event):
                    return False

            if not backup_clear:
                break

            if self.last_lidar_motion_verified is not False:
                break

            print(
                "RECOVERY BACKUP: no confirmed motion, retrying backup",
                "try",
                backup_try + 1,
                flush=True
            )
            backup_seconds = min(backup_seconds * 1.5, max_backup_seconds)
            # Fabric/wheel-slip stalls (e.g. a sock caught under a wheel) need
            # more force, not just more time, to actually break free.
            backup_speed = min(backup_speed * 1.3, max_backup_speed)

        # A small room/corridor threshold bump needs a straight, full-power push,
        # not a turn - turning wastes the backup and enters the bump at an angle,
        # splitting motor power instead of using all wheels to climb it.
        straight_push_attempts = int(IMU.get("RECOVERY_STRAIGHT_PUSH_MAX_ATTEMPTS", 0))

        live_recovery_context = {
            **self.read_distance_observation(),
            "lidar_front_cm": self._lidar_front_distance_for_recovery()
        }
        live_recovery_context["ultrasonic_cm"] = live_recovery_context.get("distance_cm")
        live_recovery_context["ultrasonic_stable"] = live_recovery_context.get("stable", False)
        threshold_push_allowed = self._threshold_push_allowed(
            block_reason,
            live_recovery_context
        )
        if (
            bool(IMU.get("RECOVERY_STRAIGHT_PUSH_ENABLED", False))
            and attempt <= straight_push_attempts
            and threshold_push_allowed
        ):
            # Escalate push force/duration across attempts too - a stubborn
            # threshold bump may need more than one gentle try.
            push_speed = min(
                float(IMU["RECOVERY_STRAIGHT_PUSH_SPEED"]) * (1 + (attempt - 1) * 0.1),
                100.0
            )
            push_seconds = min(
                float(IMU["RECOVERY_STRAIGHT_PUSH_SECONDS"]) * (1 + (attempt - 1) * 0.3),
                3.5
            )

            print(
                "RECOVERY TRY:",
                attempt,
                "straight push",
                push_speed,
                "% for",
                push_seconds,
                "seconds",
                flush=True
            )

            push_deadline = time.monotonic() + push_seconds
            while time.monotonic() < push_deadline:
                if not self.drive(
                    0,
                    push_speed,
                    use_forward_safety=True
                ):
                    return False
                if not self._recovery_wait(
                    ULTRASONIC["SAFETY_CHECK_INTERVAL_SECONDS"],
                    stop_event
                ):
                    return False

            self._stop_motor()
            return self._recovery_wait(IMU["RECOVERY_PAUSE_SECONDS"], stop_event)

        if self.is_forward_blocked():
            print(
                "RECOVERY SKIP STRAIGHT PUSH: ultrasonic blocked"
                if not threshold_push_allowed
                else "RECOVERY THRESHOLD PUSH: ultrasonic blocked but lidar front clear",
                flush=True
            )

        direction = self._preferred_recovery_turn_direction()
        turn_seconds = IMU["RECOVERY_TURN_SECONDS"] * min(
            1 + (attempt - 1) * 0.25,
            2.0
        )

        print(
            "RECOVERY TRY:",
            attempt,
            "turn",
            "right" if direction > 0 else "left",
            round(turn_seconds, 2),
            "seconds",
            flush=True
        )

        if not self._run_smooth_recovery_turn(
            direction * IMU["RECOVERY_TURN_SPEED"],
            turn_seconds,
            stop_event
        ):
            return False

        self._stop_motor()
        return self._recovery_wait(IMU["RECOVERY_PAUSE_SECONDS"], stop_event)

    def test_recovery_clear(self, stop_event=None):

        start_sample = self._sample_lidar_signature()
        end_time = time.monotonic() + IMU["RECOVERY_FORWARD_TEST_SECONDS"]

        while time.monotonic() < end_time:
            if self._recovery_cancelled(stop_event):
                return False

            if not self.drive(
                0,
                IMU["RECOVERY_FORWARD_TEST_SPEED"]
            ):
                return False

            if not self._recovery_wait(
                ULTRASONIC["SAFETY_CHECK_INTERVAL_SECONDS"],
                stop_event
            ):
                return False

        # A single favorable lidar sample near the end of the periodic
        # (~0.45s) verifier can falsely satisfy "not False" even when the
        # net motion across the whole push was near zero - that let the
        # code declare "clear" while the robot barely moved. Measure net
        # displacement directly across the full test window instead.
        end_sample = self._sample_lidar_signature()

        if not start_sample or not end_sample:
            return self.last_lidar_motion_verified is not False

        deltas = []
        for center, start_value in start_sample["signature"].items():
            end_value = end_sample["signature"].get(center)

            if start_value is None or end_value is None:
                continue

            deltas.append(abs(float(end_value) - float(start_value)))

        if not deltas:
            return self.last_lidar_motion_verified is not False

        score = sum(deltas) / float(len(deltas))
        threshold = float(MOTOR.get("LIDAR_VERIFY_MIN_DELTA_CM_LINEAR", 1.2))

        if score < threshold:
            print(
                "RECOVERY CLEAR TEST: no confirmed net motion, still stuck",
                f"score={score:.2f}",
                f"threshold={threshold:.2f}",
                flush=True
            )
            return False

        return True

    def _detect_stall_reason(self, driving_forward, stuck_event):

        # Single priority-ordered check: IMU stuck event > lidar motion
        # stall > forward-block timeout. Only IMU/lidar checks require the
        # robot to actually be driving forward; forward-block timeout can
        # also fire while turning in place against a blocked path.
        if driving_forward:
            if stuck_event:
                return "imu"

            if self.is_lidar_motion_stalled():
                print(
                    "LIDAR STALL: no confirmed motion at max boost, starting recovery",
                    flush=True
                )
                self._lidar_verify_stall_count = 0
                self.last_block_reason = "lidar_stall"
                return "lidar_stall"

        if self.is_forward_block_stalled():
            print(
                "FORWARD BLOCK STALL: blocked too long, starting recovery",
                flush=True
            )
            self.clear_forward_block()
            self.last_block_reason = "forward_block_stall"
            return "forward_block_stall"

        return None

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

            if self._detect_stall_reason(driving_forward, stuck_event):
                await self.recover_from_stuck()

            await asyncio.sleep(
                ULTRASONIC["SAFETY_CHECK_INTERVAL_SECONDS"]
            )