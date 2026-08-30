import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
import asyncio
import atexit
import signal
import threading
import time
from dotenv import load_dotenv


def _sanitize_python_paths_for_venv():
    """Keep app imports on the active venv to avoid ABI-mismatched native modules."""

    ros2_markers = (
        ".micromamba/envs/ros2_jazzy/",
        "/python3.12/site-packages"
    )

    pythonpath = os.environ.get("PYTHONPATH", "")

    if pythonpath:
        kept = []
        for entry in pythonpath.split(os.pathsep):
            lowered = entry.lower()
            if any(marker in lowered for marker in ros2_markers):
                continue
            kept.append(entry)

        if kept:
            os.environ["PYTHONPATH"] = os.pathsep.join(kept)
        else:
            os.environ.pop("PYTHONPATH", None)

    cleaned = []
    for entry in sys.path:
        lowered = str(entry).lower()
        if any(marker in lowered for marker in ros2_markers):
            continue
        cleaned.append(entry)
    sys.path[:] = cleaned


_sanitize_python_paths_for_venv()

load_dotenv()

from config import APP
from config import AUDIO
from config import LIDAR
from config import MAP
from config import LOGGING
from config import POWER_MONITOR
from config import WAKE

from utils.logger import (
    setup_run_logging
)

setup_run_logging()

from services.motor import (
    MotorService
)

from routes.control import (
    register_control_routes
)

from routes.webrtc import (
    register_webrtc_routes
)

from services.audio import (
    set_microphone_capture_volume,
    set_speaker_volume
)

from services.distance import (
    DistanceService
)

from services.imu import (
    Mpu6050Service
)

from services.power import (
    Ina219Service
)

from services.music import (
    MusicService
)

from services.movement import (
    MovementService
)

from services.ros2_slam import (
    Ros2SlamService
)

from services.ros2_lidar_proxy import (
    Ros2LidarProxyService
)

from services.ros2_navigation import (
    Ros2NavigationService
)

from services.speech import (
    SpeechService
)

from services.wake import (
    run_wake_loop
)


def _try_init_service(factory, label):
    try:
        service = factory()
        print(f"{label} SERVICE READY", flush=True)
        return service
    except Exception as exc:
        print(f"{label} SERVICE DISABLED:", repr(exc), flush=True)
        return None


class NullMotorService:

    def __init__(self):
        self.available = False
        self.current_x = 0.0
        self.current_y = 0.0
        self.last_obstacle_distance = None

    def drive(self, x, y):
        self.current_x = float(x)
        self.current_y = float(y)
        return False

    def stop(self):
        self.current_x = 0.0
        self.current_y = 0.0

    async def safety_loop(self):
        while True:
            await asyncio.sleep(1.0)

    def close(self):
        return

app = FastAPI()

templates = Jinja2Templates(
    directory="templates"
)

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)

distance = _try_init_service(DistanceService, "DISTANCE")
imu = _try_init_service(Mpu6050Service, "IMU")

if bool(POWER_MONITOR.get("ENABLED", True)):
    power_monitor = _try_init_service(Ina219Service, "POWER MONITOR")
else:
    power_monitor = None
    print("POWER MONITOR DISABLED BY CONFIG", flush=True)

speech = SpeechService()

try:
    motor = MotorService(
        distance=distance,
        imu=imu,
        speech=speech
    )
    print("MOTOR SERVICE READY", flush=True)
except Exception as exc:
    motor = NullMotorService()
    print(
        "MOTOR SERVICE DISABLED:",
        repr(exc),
        flush=True
    )

music = MusicService()
mapping_provider = str(MAP.get("PROVIDER", "ros2")).lower()

map_dir = Path(MAP.get("DIR", "output/maps"))
if not map_dir.is_absolute():
    map_dir = Path.cwd() / map_dir


def _cleanup_map_outputs_on_start():

    if not bool(MAP.get("CLEAN_OUTPUT_ON_START", True)):
        return

    map_dir.mkdir(parents=True, exist_ok=True)

    patterns = [
        str(MAP.get("LIVE_IMAGE_NAME", "live_map.pgm")),
        str(MAP.get("ROS2_EXPORT_POSE_FILE", "live_pose.json")),
        str(MAP.get("ROS2_EXPORT_META_FILE", "live_map_meta.json")),
        str(MAP.get("ROS2_EXPORT_SCAN_FILE", "live_scan.json")),
        str(MAP.get("ROS2_EXPORT_RESET_FILE", "map_reset.json")),
        "robot_map-*.pgm",
        "robot_map-*.yaml"
    ]

    removed = 0

    for pattern in patterns:
        for path in map_dir.glob(pattern):
            if not path.exists() or not path.is_file():
                continue

            try:
                path.unlink()
                removed += 1
            except Exception:
                pass

    if removed > 0:
        print(
            "MAP OUTPUT CLEANUP:",
            f"removed={removed}",
            flush=True
        )


_cleanup_map_outputs_on_start()

scan_file = Path(MAP.get("DIR", "output/maps")) / str(
    MAP.get("ROS2_EXPORT_SCAN_FILE", "live_scan.json")
)
if not scan_file.is_absolute():
    scan_file = Path.cwd() / scan_file

lidar = Ros2LidarProxyService(
    scan_file=scan_file,
    sector_deg=float(LIDAR.get("SCAN_SECTOR_DEGREES", 30.0)),
    angle_offset_deg=float(MAP.get("ROS2_MOVEMENT_LOCAL_SCAN_OFFSET_DEG", 0.0)),
    max_age_seconds=float(MAP.get("ROS2_MOVEMENT_SCAN_MAX_AGE_SECONDS", 2.5))
)
print("LIDAR SERVICE: ros2 scan proxy", flush=True)

if hasattr(motor, "set_lidar"):
    motor.set_lidar(lidar)

movement = None

if getattr(motor, "available", True):
    movement = MovementService(
        motor,
        lidar=lidar
    )
else:
    print("MOVEMENT SERVICE DISABLED: motor unavailable", flush=True)

if mapping_provider != "ros2":
    print("MAP.PROVIDER forced to ros2 for SLAM-only mapping", flush=True)

mapping = Ros2SlamService()
print("MAPPING PROVIDER: ros2", flush=True)

try:
    navigator = Ros2NavigationService()
    print("NAVIGATION SERVICE: ros2 nav2/explore_lite ready", flush=True)
except Exception as exc:
    navigator = None
    print(
        "NAVIGATION SERVICE DISABLED:",
        repr(exc),
        flush=True
    )

register_control_routes(
    app,
    motor,
    music,
    movement,
    mapping,
    lidar,
    navigator,
    power_monitor
)

register_webrtc_routes(
    app
)

wake_task = None
motor_safety_task = None
startup_calibration_task = None
map_jump_watchdog_task = None
power_safety_task = None
exploration_liveness_task = None
_shutdown_lock = threading.Lock()
_motors_stopped = False


def _safe_stop_motors(reason="unknown"):
    global _motors_stopped

    with _shutdown_lock:
        if _motors_stopped:
            return

        print(
            "SAFETY STOP MOTORS:",
            reason,
            flush=True
        )

        try:
            motor.stop()
        except Exception as exc:
            print(
                "SAFETY STOP MOTOR ERROR:",
                repr(exc),
                flush=True
            )

        _motors_stopped = True


def _install_shutdown_safety_handlers():
    previous_handlers = {}

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.getsignal(sig)

    def _handle_signal(sig, frame):
        _safe_stop_motors(reason=f"signal_{sig}")

        previous = previous_handlers.get(sig)

        if callable(previous) and previous is not _handle_signal:
            return previous(sig, frame)

        if previous == signal.SIG_DFL:
            raise SystemExit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)


_install_shutdown_safety_handlers()
atexit.register(_safe_stop_motors, "atexit")


@app.on_event("startup")
async def start_wake_listener():
    global wake_task
    global motor_safety_task
    global startup_calibration_task
    global map_jump_watchdog_task
    global power_safety_task
    global exploration_liveness_task

    try:
        volume = set_speaker_volume(
            AUDIO["SPEAKER_STARTUP_VOLUME"]
        )
        print(
            "SPEAKER VOLUME:",
            volume,
            flush=True
        )

    except Exception as exc:
        print(
            "SPEAKER VOLUME ERROR:",
            repr(exc),
            flush=True
        )

    try:
        volume = set_microphone_capture_volume(
            AUDIO["MICROPHONE_STARTUP_VOLUME"]
        )
        print(
            "MICROPHONE CAPTURE VOLUME:",
            volume,
            flush=True
        )

    except Exception as exc:
        print(
            "MICROPHONE VOLUME ERROR:",
            repr(exc),
            flush=True
        )

    if WAKE["ENABLED"] and movement and getattr(motor, "available", True):
        wake_task = asyncio.create_task(
            run_wake_loop(
                motor=motor,
                music=music,
                movement=movement,
                speech=speech
            )
        )

    if getattr(motor, "available", True):
        motor_safety_task = asyncio.create_task(
            motor.safety_loop()
        )

    if lidar and movement and bool(LIDAR.get("AUTO_CALIBRATE_ON_STARTUP", False)):
        startup_calibration_task = asyncio.create_task(
            _run_startup_lidar_calibration()
        )

    if mapping and bool(MAP.get("MAP_JUMP_WATCHDOG_ENABLED", True)):
        map_jump_watchdog_task = asyncio.create_task(
            _run_map_jump_watchdog()
        )

    if (
        power_monitor
        and bool(POWER_MONITOR.get("ENABLED", True))
        and bool(POWER_MONITOR.get("DRIVE_SAFETY_ENABLED", True))
    ):
        power_safety_task = asyncio.create_task(
            _run_power_safety_watchdog()
        )

    if (
        navigator
        and getattr(motor, "available", True)
        and bool(MAP.get("ROS2_EXPLORE_LIVENESS_WATCHDOG_ENABLED", True))
    ):
        exploration_liveness_task = asyncio.create_task(
            _run_exploration_liveness_watchdog()
        )


async def _run_exploration_liveness_watchdog():

    idle_since = None
    last_recovery_at = 0.0
    idle_seconds = max(
        2.0,
        float(MAP.get("ROS2_EXPLORE_IDLE_RECOVERY_SECONDS", 8.0))
    )
    cooldown_seconds = max(
        idle_seconds,
        float(MAP.get("ROS2_EXPLORE_RECOVERY_COOLDOWN_SECONDS", 20.0))
    )

    while True:
        await asyncio.sleep(1.0)

        state = navigator.status()
        no_frontiers = (
            bool(state.get("nav2_running"))
            and bool(state.get("explore_process_running"))
            and state.get("explore_reason") == "no_frontiers"
            and bool(state.get("autonomous_recovery_allowed"))
        )
        stationary = (
            abs(float(getattr(motor, "current_x", 0.0))) < 0.5
            and abs(float(getattr(motor, "current_y", 0.0))) < 0.5
            and not bool(getattr(motor, "recovering", False))
        )

        if not no_frontiers or not stationary:
            idle_since = None
            continue

        if idle_since is None:
            idle_since = time.monotonic()
            continue

        now = time.monotonic()
        if now - idle_since < idle_seconds or now - last_recovery_at < cooldown_seconds:
            continue

        front_blocked = await asyncio.to_thread(motor.is_forward_blocked)
        if not front_blocked:
            print(
                "EXPLORE COMPLETE: no frontiers and forward path is clear",
                flush=True
            )
            idle_since = None
            continue

        last_recovery_at = now
        idle_since = None
        print(
            "EXPLORE IDLE RECOVERY: no frontiers while forward path is blocked",
            flush=True
        )

        navigator.stop_exploration(cancel_recovery=False)
        motor.last_block_reason = "forward_block_stall"
        recovered = await motor.recover_from_stuck(
            navigator.recovery_cancel_event
        )

        if not recovered or navigator.recovery_cancel_event.is_set():
            print(
                "EXPLORE IDLE RECOVERY: local escape failed; exploration remains stopped",
                flush=True
            )
            continue

        result = await asyncio.to_thread(navigator.start_exploration)
        print(
            "EXPLORE IDLE RECOVERY: exploration restart",
            result,
            flush=True
        )


async def _run_power_safety_watchdog():

    interval = max(
        0.02,
        float(POWER_MONITOR.get("DRIVE_SAFETY_INTERVAL_SECONDS", 0.05))
    )
    critical_voltage = float(
        POWER_MONITOR.get("DRIVE_CRITICAL_VOLTAGE", 10.8)
    )
    critical_samples = max(
        1,
        int(POWER_MONITOR.get("DRIVE_CRITICAL_SAMPLES", 2))
    )
    read_timeout = max(
        0.1,
        float(POWER_MONITOR.get("DRIVE_READ_TIMEOUT_SECONDS", 0.35))
    )
    critical_read_errors = max(
        1,
        int(POWER_MONITOR.get("DRIVE_READ_ERROR_SAMPLES", 1))
    )
    log_interval = max(
        0.1,
        float(POWER_MONITOR.get("DRIVE_LOG_INTERVAL_SECONDS", 0.25))
    )
    low_samples = 0
    read_errors = 0
    last_log = 0.0

    while True:
        await asyncio.sleep(interval)

        moving = (
            abs(float(getattr(motor, "current_x", 0.0))) >= 0.5
            or abs(float(getattr(motor, "current_y", 0.0))) >= 0.5
        )
        if not moving or bool(getattr(motor, "power_fault", False)):
            low_samples = 0
            continue

        try:
            sample = await asyncio.wait_for(
                asyncio.to_thread(power_monitor.read),
                timeout=read_timeout
            )
        except Exception as exc:
            print("POWER SAFETY READ ERROR:", repr(exc), flush=True)
            read_errors += 1
            if read_errors >= critical_read_errors:
                motor.last_power_fault = {
                    "status": "ERROR",
                    "reason": "power_monitor_read",
                    "error": repr(exc),
                    "time": time.monotonic()
                }
                motor.power_fault = True
                motor.stop()
                if navigator:
                    try:
                        navigator.stop_exploration()
                    except Exception as stop_exc:
                        print(
                            "POWER SAFETY: stop_exploration failed:",
                            repr(stop_exc),
                            flush=True
                        )
            continue

        read_errors = 0
        now = time.monotonic()
        if now - last_log >= log_interval:
            last_log = now
            print(
                "POWER DRIVE:",
                f"voltage={sample['bus_voltage']:.3f}V",
                f"current={sample['current_ma']:.1f}mA",
                f"power={sample['power_w']:.2f}W",
                f"motor=({motor.current_x:.1f},{motor.current_y:.1f})",
                flush=True
            )

        if float(sample["bus_voltage"]) <= critical_voltage:
            low_samples += 1
        else:
            low_samples = 0

        if low_samples < critical_samples:
            continue

        motor.last_power_fault = dict(sample)
        motor.power_fault = True
        print("POWER SAFETY TRIP:", motor.last_power_fault, flush=True)
        motor.stop()

        if navigator:
            try:
                navigator.stop_exploration()
            except Exception as exc:
                print("POWER SAFETY: stop_exploration failed:", repr(exc), flush=True)


async def _run_map_jump_watchdog():

    interval = float(MAP.get("MAP_JUMP_CHECK_INTERVAL_SECONDS", 2.0))

    while True:
        await asyncio.sleep(max(0.5, interval))

        try:
            jump = mapping.detect_pose_jump()
        except Exception as exc:
            print("MAP JUMP WATCHDOG CHECK ERROR:", repr(exc), flush=True)
            continue

        if not jump and bool(MAP.get("MAP_IMU_YAW_WATCHDOG_ENABLED", True)) and imu:
            try:
                sample = await asyncio.to_thread(imu.read_motion)
                recovery_finished_at = getattr(motor, "last_recovery_finished_at", None)
                recovery_settling = recovery_finished_at is not None and (
                    time.monotonic() - float(recovery_finished_at)
                    < float(MAP.get("MAP_IMU_YAW_DISTURBANCE_GRACE_SECONDS", 3.0))
                )
                robot_moving = (
                    not bool(getattr(motor, "recovering", False))
                    and not recovery_settling
                    and (
                        abs(float(getattr(motor, "current_x", 0.0))) >= 0.5
                        or abs(float(getattr(motor, "current_y", 0.0))) >= 0.5
                    )
                )
                jump = mapping.detect_imu_yaw_divergence(
                    sample["gyro_z"],
                    robot_moving=robot_moving
                )
            except Exception as exc:
                print("MAP IMU YAW WATCHDOG CHECK ERROR:", repr(exc), flush=True)

        if not jump:
            continue

        print("MAP JUMP DETECTED, AUTO-RESETTING SLAM MAP:", jump, flush=True)

        if navigator:
            try:
                navigator.stop_exploration()
            except Exception as exc:
                print("MAP JUMP WATCHDOG: stop_exploration failed:", repr(exc), flush=True)

        try:
            motor.stop()
        except Exception as exc:
            print("MAP JUMP WATCHDOG: motor stop failed:", repr(exc), flush=True)

        try:
            result = mapping.reset()
            print("MAP JUMP WATCHDOG: auto reset result:", result, flush=True)
        except Exception as exc:
            print("MAP JUMP WATCHDOG: mapping.reset failed:", repr(exc), flush=True)

        print("MAP JUMP WATCHDOG: exploration remains stopped after reset", flush=True)


async def _run_startup_lidar_calibration():

    try:
        wait_seconds = float(LIDAR.get("AUTO_CALIBRATE_WAIT_SECONDS", 18))
        deadline = asyncio.get_running_loop().time() + max(2.0, wait_seconds)

        while asyncio.get_running_loop().time() < deadline:
            if lidar.is_ready():
                break

            await asyncio.sleep(0.4)

        if not lidar.is_ready():
            print(
                "LIDAR AUTO CALIBRATION: skipped (lidar not ready)",
                flush=True
            )
            return

        attempts = int(LIDAR.get("AUTO_CALIBRATE_ATTEMPTS", 3))
        attempts = max(1, min(8, attempts))
        retry_seconds = float(LIDAR.get("AUTO_CALIBRATE_RETRY_SECONDS", 2.0))
        last_result = None

        for attempt in range(1, attempts + 1):
            last_result = movement.calibrate_lidar_mount()

            print(
                "LIDAR AUTO CALIBRATION ATTEMPT:",
                attempt,
                last_result,
                flush=True
            )

            if isinstance(last_result, dict) and last_result.get("status") == "OK":
                break

            if attempt < attempts:
                await asyncio.sleep(max(0.2, retry_seconds))

        print(
            "LIDAR AUTO CALIBRATION:",
            last_result,
            flush=True
        )

    except Exception as exc:
        print(
            "LIDAR AUTO CALIBRATION ERROR:",
            repr(exc),
            flush=True
        )


@app.on_event("shutdown")
async def stop_wake_listener():
    global startup_calibration_task
    global power_safety_task
    global exploration_liveness_task

    if exploration_liveness_task:
        navigator.recovery_cancel_event.set()
        motor.stop()
        exploration_liveness_task.cancel()

        try:
            await exploration_liveness_task

        except asyncio.CancelledError:
            pass

    if wake_task:
        wake_task.cancel()

        try:
            await wake_task

        except asyncio.CancelledError:
            pass

    if motor_safety_task:
        motor_safety_task.cancel()

        try:
            await motor_safety_task

        except asyncio.CancelledError:
            pass

    if startup_calibration_task:
        startup_calibration_task.cancel()

        try:
            await startup_calibration_task

        except asyncio.CancelledError:
            pass

    if map_jump_watchdog_task:
        map_jump_watchdog_task.cancel()

        try:
            await map_jump_watchdog_task

        except asyncio.CancelledError:
            pass

    if power_safety_task:
        power_safety_task.cancel()

        try:
            await power_safety_task

        except asyncio.CancelledError:
            pass

    _safe_stop_motors(reason="fastapi_shutdown")
    if navigator:
        navigator.close()

    if mapping:
        mapping.close()

    if motor:
        motor.close()

    if distance:
        distance.close()

    if imu:
        imu.close()

    if lidar:
        lidar.close()


@app.get("/")
async def index(
    request: Request
):

    return templates.TemplateResponse(
        request,
        "index.html",
        {}
    )


if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host=APP["HOST"],
        port=APP["PORT"],
        reload=False
    )