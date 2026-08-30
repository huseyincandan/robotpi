import asyncio
import mimetypes
import json
import time
from datetime import datetime
from pathlib import Path

import cv2
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Response
from fastapi import WebSocket
from fastapi import WebSocketDisconnect

from services.audio import (
    get_speaker_volume,
    set_speaker_volume
)
from config import AUDIO
from config import LIDAR
from config import MAP
from config import MOTOR
from config import POWER_MONITOR
from config import ULTRASONIC


def register_control_routes(
    app,
    motor,
    music=None,
    movement=None,
    mapping=None,
    lidar=None,
    navigator=None,
    power_monitor=None
):

    router = APIRouter()

    def _map_output_dir():

        configured = Path(
            MAP.get("DIR", "output/maps")
        )

        if not configured.is_absolute():
            configured = Path.cwd() / configured

        return configured

    def _map_pose_file():
        return _map_output_dir() / str(
            MAP.get("ROS2_EXPORT_POSE_FILE", "live_pose.json")
        )

    def _map_meta_file():
        return _map_output_dir() / str(
            MAP.get("ROS2_EXPORT_META_FILE", "live_map_meta.json")
        )

    def _map_reset_file():
        return _map_output_dir() / str(
            MAP.get("ROS2_EXPORT_RESET_FILE", "map_reset.json")
        )

    def _read_json_file(path):
        if not path.exists() or not path.is_file():
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _read_reset_timestamp():

        payload = _read_json_file(_map_reset_file())

        if not payload:
            return None

        try:
            return float(payload.get("reset_at"))
        except Exception:
            return None

    def _lidar_forward_block_reason():

        lidar_service = getattr(movement, "lidar", None) if movement else None

        if lidar_service:
            try:
                distances = lidar_service.get_distances_cm()

                if distances:
                    front_cm = distances.get("front_cm")

                    if front_cm is not None and front_cm <= float(LIDAR.get("FRONT_STOP_CM", 40)):
                        print(
                            "FORWARD BLOCK: lidar",
                            round(float(front_cm), 1),
                            "cm",
                            flush=True
                        )
                        return {
                            "reason": "lidar",
                            "distance": float(front_cm)
                        }
            except Exception as exc:
                print(
                    "FORWARD BLOCK CHECK ERROR (lidar):",
                    repr(exc),
                    flush=True
                )

        return None

    def _ultrasonic_forward_block_reason(stop_distance_cm=None):

        # The lidar has a hardware blind zone below LIDAR.MIN_VALID_CM, so it
        # cannot see an obstacle directly against the bumper. Ultrasonic is the
        # only sensor covering that range, so this check must run for every
        # drive source (including nav2/explore_lite) and can never be bypassed.
        # Ultrasonic readings are also published as a LaserScan into Nav2's
        # costmap (config/nav2_params.yaml ultrasonic_layer), so autonomous
        # sources already plan around what this sensor sees; callers may pass
        # a tighter stop_distance_cm to use this only as a last-resort check.
        threshold_cm = (
            float(stop_distance_cm)
            if stop_distance_cm is not None
            else float(ULTRASONIC.get("STOP_DISTANCE_CM", 20))
        )

        if hasattr(motor, "read_distance_centimeters"):
            try:
                centimeters = motor.read_distance_centimeters()

                if centimeters is None:
                    print("FORWARD BLOCK: ultrasonic unstable", flush=True)
                    return {
                        "reason": "ultrasonic_unstable",
                        "distance": None
                    }

                if centimeters <= threshold_cm:
                    print(
                        "FORWARD BLOCK: ultrasonic",
                        round(float(centimeters), 1),
                        "cm",
                        flush=True
                    )
                    return {
                        "reason": "ultrasonic",
                        "distance": float(centimeters)
                    }
            except Exception as exc:
                print(
                    "FORWARD BLOCK CHECK ERROR (ultrasonic):",
                    repr(exc),
                    flush=True
                )

        return None

    def _forward_motion_block_reason():

        return _lidar_forward_block_reason() or _ultrasonic_forward_block_reason()

    def _latest_map_file():

        provider = str(MAP.get("PROVIDER", "ros2")).lower()
        live_name = str(MAP.get("LIVE_IMAGE_NAME", "live_map.pgm")).strip()
        reset_at = _read_reset_timestamp()

        def _is_newer_than_reset(path):
            if reset_at is None:
                return True

            try:
                return float(path.stat().st_mtime) > reset_at
            except Exception:
                return False

        if live_name:
            live_path = _map_output_dir() / live_name
            if live_path.exists() and live_path.is_file() and _is_newer_than_reset(live_path):
                return live_path
            if provider == "ros2":
                return None

        extensions = (
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".pgm"
        )

        map_dir = _map_output_dir()
        if not map_dir.exists() or not map_dir.is_dir():
            return None

        candidates = []
        for extension in extensions:
            candidates.extend(map_dir.glob(f"*{extension}"))
            candidates.extend(map_dir.glob(f"*map*{extension}"))

        valid_files = [
            path for path in candidates
            if path.exists() and path.is_file() and _is_newer_than_reset(path)
        ]

        if not valid_files:
            return None

        return max(
            valid_files,
            key=lambda item: item.stat().st_mtime
        )

    def _map_health():
        map_dir = _map_output_dir()

        latest = _latest_map_file()
        latest_mtime = None
        latest_updated_at = ""
        lidar_ready = None
        lidar_status = "unknown"
        lidar_front_cm = None

        lidar_service = getattr(movement, "lidar", None) if movement else None

        if lidar_service is None:
            lidar_service = lidar

        if lidar_service:
            try:
                lidar_status = lidar_service.status()
                lidar_ready = bool(lidar_service.is_ready())
                distances = lidar_service.get_distances_cm()
                if distances:
                    lidar_front_cm = distances.get("front_cm")
            except Exception:
                lidar_status = "error"
                lidar_ready = False

        if latest:
            latest_mtime = latest.stat().st_mtime
            latest_updated_at = datetime.fromtimestamp(
                latest_mtime
            ).isoformat(timespec="seconds")

        save_ready = bool(mapping and hasattr(mapping, "save_map"))
        save_reason = "ok" if save_ready else "mapping_save_not_supported"

        return {
            "provider": str(MAP.get("PROVIDER", "ros2")),
            "mapping_status": mapping.status() if mapping and hasattr(mapping, "status") else "unknown",
            "save_ready": save_ready,
            "save_reason": save_reason,
            "output_dir": str(map_dir),
            "latest_exists": latest is not None,
            "latest_file": str(latest) if latest else "",
            "latest_mtime": latest_mtime,
            "latest_updated_at": latest_updated_at,
            "pose_exists": _map_pose_file().exists(),
            "meta_exists": _map_meta_file().exists(),
            "lidar_ready": lidar_ready,
            "lidar_status": lidar_status,
            "lidar_front_cm": lidar_front_cm
        }

    @router.get("/drive")
    async def drive(
        x: float = 0,
        y: float = 0,
        source: str = ""
    ):

        source_value = str(source).strip().lower()
        bypass_forward_safety = source_value in {"nav2", "explore", "ros2"}

        if (
            (abs(x) > 1e-3 or abs(y) > 1e-3)
            and bool(getattr(motor, "sensor_fault", False))
        ):
            motor.stop()
            if navigator:
                navigator.stop_exploration()
            return {
                "status": "BLOCKED",
                "reason": "sensor_fault",
                "distance": motor.last_obstacle_distance
            }

        if (
            (abs(x) > 1e-3 or abs(y) > 1e-3)
            and bool(getattr(motor, "power_fault", False))
        ):
            motor.stop()
            return {
                "status": "BLOCKED",
                "reason": "power_fault",
                "distance": motor.last_obstacle_distance
            }

        if bypass_forward_safety and motor.recovering:
            return {
                "status": "BLOCKED",
                "reason": "recovery_active",
                "distance": motor.last_obstacle_distance
            }

        if y > 0:
            if not bypass_forward_safety:
                block = _forward_motion_block_reason()

                if block:
                    motor.stop()
                    motor.note_forward_block()
                    return {
                        "status": "BLOCKED",
                        "reason": block["reason"],
                        "distance": block["distance"]
                    }
            else:
                # Ultrasonic is fused into Nav2's costmap (see nav2_params.yaml
                # ultrasonic_layer), so the planner/controller already steer
                # around what it sees; this is now just a tight last-resort
                # failsafe for the blind gap below the lidar's minimum range.
                ultrasonic_block = _ultrasonic_forward_block_reason(
                    stop_distance_cm=float(ULTRASONIC.get("AUTONOMOUS_STOP_DISTANCE_CM", 12))
                )

                if ultrasonic_block:
                    motor.note_forward_block()

                    if abs(x) > 1e-3:
                        # Only the forward component is unsafe at this range -
                        # still let nav2 turn away from the obstacle instead of
                        # freezing the whole command. Preserve the bridge's
                        # slew-limited value; amplifying it here would recreate
                        # the turn impulse that corrupts lidar scan matching.
                        motor.drive(x, 0, use_forward_safety=False, source=source_value)
                    else:
                        motor.stop()
                        # Tell the cmd_vel bridge's slip-correction no real motion
                        # happened, so nav2's odom (and progress checker) reflect
                        # reality instead of believing the blocked drive succeeded.
                        motor.last_lidar_motion_verified = False

                    return {
                        "status": "BLOCKED",
                        "reason": ultrasonic_block["reason"],
                        "distance": ultrasonic_block["distance"]
                    }

        if y > 0:
            # We only reach here once the forward blind spot is confirmed
            # clear, so any earlier stall timer no longer reflects reality.
            motor.clear_forward_block()

        if y < 0:
            # Was gated on bypass_forward_safety (nav2/explore/ros2 only), which
            # meant manual/joystick reverse never got a lidar rear check at all -
            # any source can back into something, so always check.
            rear_clear, rear_cm = motor.rear_motion_clear()
            if not rear_clear:
                motor.stop()
                return {
                    "status": "BLOCKED",
                    "reason": "rear_obstacle" if rear_cm is not None else "rear_lidar_unavailable",
                    "distance": rear_cm
                }

        moved = motor.drive(
            x,
            y,
            use_forward_safety=not bypass_forward_safety,
            source=source_value
        )

        if not moved:
            return {
                "status": "BLOCKED",
                "reason": "obstacle",
                "distance": motor.last_obstacle_distance
            }

        return {
            "status": "OK"
        }

    @router.get("/stop")
    async def stop():

        if navigator:
            try:
                navigator.stop_exploration()
            except Exception:
                pass

        motor.stop()

        return {
            "status": "OK"
        }

    @router.post("/motor/stop")
    async def motor_stop():

        if navigator:
            try:
                navigator.stop_exploration()
            except Exception:
                pass

        motor.stop()

        return {
            "status": "OK"
        }

    @router.get("/motor/status")
    async def motor_status():

        return {
            "status": "OK",
            "current_x": float(getattr(motor, "current_x", 0.0)),
            "current_y": float(getattr(motor, "current_y", 0.0)),
            "last_requested_x": float(getattr(motor, "last_requested_x", 0.0)),
            "last_requested_y": float(getattr(motor, "last_requested_y", 0.0)),
            "blocked": bool(getattr(motor, "blocked", False)),
            "last_block_reason": getattr(motor, "last_block_reason", None),
            "last_obstacle_distance": getattr(motor, "last_obstacle_distance", None),
            "power_fault": bool(getattr(motor, "power_fault", False)),
            "last_power_fault": getattr(motor, "last_power_fault", None),
            "sensor_fault": bool(getattr(motor, "sensor_fault", False)),
            "last_sensor_fault": getattr(motor, "last_sensor_fault", None),
            "lidar_motion_verified": getattr(motor, "last_lidar_motion_verified", None),
            "lidar_motion_score": getattr(motor, "last_lidar_motion_score", None),
            "lidar_verify_boost_percent": float(getattr(motor, "_lidar_verify_boost_percent", 0.0))
        }

    @router.get("/ultrasonic/readings")
    async def ultrasonic_readings():

        try:
            observation = await asyncio.wait_for(
                asyncio.to_thread(motor.read_distance_observation),
                timeout=float(POWER_MONITOR.get("DRIVE_READ_TIMEOUT_SECONDS", 0.35))
            )
        except Exception as exc:
            return {
                "status": "ERROR",
                "distance_cm": None,
                "message": str(exc)
            }

        return {
            "status": "OK" if observation.get("distance_cm") is not None else "ERROR",
            **observation
        }

    @router.get("/imu/motion")
    async def imu_motion():

        imu = getattr(motor, "imu", None)

        if not imu:
            return {
                "status": "ERROR",
                "message": "IMU service not available"
            }

        try:
            sample = await asyncio.wait_for(
                asyncio.to_thread(imu.read_motion),
                timeout=float(POWER_MONITOR.get("DRIVE_READ_TIMEOUT_SECONDS", 0.35))
            )
        except Exception as exc:
            return {
                "status": "ERROR",
                "message": str(exc)
            }

        return {
            "status": "OK",
            "gyro_z_dps": float(sample["gyro_z"]),
            "gyro_x_dps": float(sample["gyro_x"]),
            "gyro_y_dps": float(sample["gyro_y"]),
            "time": float(sample["time"]),
            "lidar_motion_verified": motor.last_lidar_motion_verified,
            "lidar_motion_score": motor.last_lidar_motion_score,
            "motor_x_percent": float(getattr(motor, "current_x", 0.0)),
            "motor_y_percent": float(getattr(motor, "current_y", 0.0))
        }

    @router.get("/battery/status")
    async def battery_status():

        if not power_monitor:
            raise HTTPException(
                status_code=503,
                detail="Power monitor service is not available"
            )

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(power_monitor.read),
                timeout=float(POWER_MONITOR.get("DRIVE_READ_TIMEOUT_SECONDS", 0.35))
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Battery status read failed: {repr(exc)}"
            )

    @router.post("/imu/calibrate")
    async def imu_calibrate():

        imu = getattr(motor, "imu", None)

        if not imu:
            raise HTTPException(
                status_code=503,
                detail="IMU service not available"
            )

        try:
            result = imu.calibrate_gyro_bias()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"IMU calibration failed: {repr(exc)}"
            )

        return {
            "status": "OK",
            **result
        }

    @router.get("/wander/status")
    async def wander_status():

        if not navigator:
            return {
                "wandering": False
            }

        state = navigator.status()
        return {
            "wandering": bool(state.get("explore_running"))
        }

    @router.post("/wander/start")
    async def wander_start():

        if not navigator:
            return {
                "status": "ERROR",
                "wandering": False,
                "message": "Navigation service is not available"
            }

        motor.rearm_recovery()
        result = navigator.start_exploration()

        return {
            "status": result.get("status", "OK"),
            "wandering": bool(navigator.status().get("explore_running")),
            "message": result.get("message", "Kesif baslatildi")
        }

    @router.post("/wander/stop")
    async def wander_stop():

        if not navigator:
            motor.stop()
            return {
                "status": "OK",
                "wandering": False,
                "stopped": True
            }

        result = navigator.stop_exploration()

        motor.stop()

        return {
            "status": result.get("status", "OK"),
            "wandering": bool(navigator.status().get("explore_running")),
            "stopped": True,
            "message": result.get("message", "Kesif durduruldu")
        }

    @router.post("/lidar/calibrate")
    async def lidar_calibrate():

        if not movement:
            raise HTTPException(
                status_code=503,
                detail="Movement service is not available"
            )

        try:
            result = movement.calibrate_lidar_mount()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Lidar calibration failed: {repr(exc)}"
            )

        return result

    @router.get("/nav2/status")
    async def nav2_status():

        if not navigator:
            return {
                "status": "ERROR",
                "message": "Navigation service is not available",
                "nav2_running": False,
                "explore_running": False
            }

        state = navigator.status()

        return {
            "status": "OK",
            **state
        }

    @router.post("/nav2/start")
    async def nav2_start():

        if not navigator:
            return {
                "status": "ERROR",
                "message": "Navigation service is not available"
            }

        result = navigator.start_nav2()
        state = navigator.status()

        return {
            **result,
            "nav2_running": bool(state.get("nav2_running")),
            "explore_running": bool(state.get("explore_running"))
        }

    @router.post("/nav2/stop")
    async def nav2_stop():

        if not navigator:
            return {
                "status": "ERROR",
                "message": "Navigation service is not available"
            }

        result = navigator.stop_nav2()

        motor.stop()

        state = navigator.status()

        return {
            **result,
            "nav2_running": bool(state.get("nav2_running")),
            "explore_running": bool(state.get("explore_running"))
        }

    @router.post("/explore/start")
    async def explore_start():

        if not navigator:
            return {
                "status": "ERROR",
                "message": "Navigation service is not available"
            }

        result = navigator.start_exploration()
        state = navigator.status()

        return {
            **result,
            "nav2_running": bool(state.get("nav2_running")),
            "explore_running": bool(state.get("explore_running"))
        }

    @router.post("/explore/stop")
    async def explore_stop():

        if not navigator:
            return {
                "status": "ERROR",
                "message": "Navigation service is not available"
            }

        result = navigator.stop_exploration()

        motor.stop()

        state = navigator.status()

        return {
            **result,
            "nav2_running": bool(state.get("nav2_running")),
            "explore_running": bool(state.get("explore_running"))
        }

    @router.get("/lidar/readings")
    async def lidar_readings():

        lidar_service = getattr(movement, "lidar", None) if movement else None

        if lidar_service is None:
            lidar_service = lidar

        if not lidar_service:
            raise HTTPException(
                status_code=503,
                detail="Lidar service is not available"
            )

        if not lidar_service.is_ready():
            raise HTTPException(
                status_code=503,
                detail="Lidar is not ready"
            )

        points = lidar_service.get_scan_points() or []

        if not points:
            raise HTTPException(
                status_code=503,
                detail="No lidar points"
            )

        half_sector = float(getattr(lidar_service, "sector", 30.0)) / 2.0

        def sector_min(center_deg):
            minimum = None

            for angle, distance_cm in points:
                diff = (float(angle) - center_deg + 540.0) % 360.0 - 180.0

                if abs(diff) > half_sector:
                    continue

                if minimum is None or distance_cm < minimum:
                    minimum = float(distance_cm)

            return minimum

        return {
            "status": "OK",
            "offset_deg": float(lidar_service.get_angle_offset_deg()) if hasattr(lidar_service, "get_angle_offset_deg") else 0.0,
            "front_cm": sector_min(0.0),
            "left_cm": sector_min(90.0),
            "back_cm": sector_min(180.0),
            "right_cm": sector_min(270.0),
            "points_count": len(points)
        }

    @router.get("/speaker-volume")
    async def speaker_volume():

        try:
            volume = get_speaker_volume()
            available = True

        except Exception:
            volume = int(AUDIO.get("SPEAKER_STARTUP_VOLUME", 70))
            available = False

        return {
            "volume": volume,
            "available": available
        }

    @router.post("/speaker-volume")
    async def update_speaker_volume(
        volume: int
    ):

        try:
            speaker_volume = set_speaker_volume(
                volume
            )
            available = True

        except Exception:
            speaker_volume = int(AUDIO.get("SPEAKER_STARTUP_VOLUME", 70))
            available = False

        if music:
            music.set_volume(
                speaker_volume
            )

        return {
            "volume": speaker_volume,
            "available": available
        }

    @router.get("/map/latest")
    async def latest_map_image():

        map_file = _latest_map_file()

        if not map_file:
            raise HTTPException(
                status_code=404,
                detail="Map not found"
            )

        suffix = map_file.suffix.lower()

        if suffix == ".pgm":
            image = cv2.imread(
                str(map_file),
                cv2.IMREAD_UNCHANGED
            )

            if image is None:
                raise HTTPException(
                    status_code=500,
                    detail="Map file could not be read"
                )

            ok, encoded = cv2.imencode(
                ".png",
                image
            )

            if not ok:
                raise HTTPException(
                    status_code=500,
                    detail="Map file could not be encoded"
                )

            return Response(
                content=encoded.tobytes(),
                media_type="image/png",
                headers={
                    "Cache-Control": "no-store"
                }
            )

        media_type, _ = mimetypes.guess_type(
            str(map_file)
        )

        try:
            content = map_file.read_bytes()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Map file could not be read: {exc}"
            )

        return Response(
            content=content,
            media_type=media_type or "application/octet-stream",
            headers={
                "Cache-Control": "no-store"
            }
        )

    @router.post("/map/save")
    async def save_map_snapshot():

        if not mapping or not hasattr(mapping, "save_map"):
            raise HTTPException(
                status_code=503,
                detail="Map save service is not available"
            )

        map_dir = _map_output_dir()
        map_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        timestamp = datetime.now().strftime(
            "%Y%m%d-%H%M%S"
        )

        base_name = MAP.get(
            "SAVE_BASENAME",
            "robot_map"
        )

        output_base = map_dir / f"{base_name}-{timestamp}"
        result = mapping.save_map(output_base)
        if result.get("status") != "OK":
            raise HTTPException(
                status_code=500,
                detail=result
            )

        return result

    @router.post("/map/reset")
    async def reset_map_snapshot():

        if not mapping:
            raise HTTPException(
                status_code=503,
                detail="Mapping service is not available"
            )

        map_dir = _map_output_dir()
        map_dir.mkdir(parents=True, exist_ok=True)

        reset_payload = {
            "reset_at": datetime.now().timestamp(),
            "mode": "pending"
        }

        try:
            _map_reset_file().write_text(
                json.dumps(reset_payload, ensure_ascii=True),
                encoding="utf-8"
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Map reset marker could not be written: {repr(exc)}"
            )

        # Clear stale artifacts before restarting SLAM so fresh outputs are always newer than reset marker.
        for candidate in (
            _map_output_dir() / str(MAP.get("LIVE_IMAGE_NAME", "live_map.pgm")),
            _map_pose_file(),
            _map_meta_file(),
            _map_output_dir() / str(MAP.get("ROS2_EXPORT_SCAN_FILE", "live_scan.json"))
        ):
            try:
                if candidate.exists() and candidate.is_file():
                    candidate.unlink()
            except Exception:
                pass

        try:
            result = mapping.reset()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Map reset failed: {repr(exc)}"
            )

        reset_payload["mode"] = result.get("mode") if isinstance(result, dict) else "unknown"
        try:
            _map_reset_file().write_text(
                json.dumps(reset_payload, ensure_ascii=True),
                encoding="utf-8"
            )
        except Exception:
            pass

        if isinstance(result, dict):
            return result

        return {"status": "OK", "message": "Map reset"}

    @router.get("/map/health")
    async def map_health():

        return _map_health()

    @router.get("/map/pose")
    async def map_pose():

        payload = _read_json_file(_map_pose_file())
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail="Map pose not found"
            )

        updated_at = payload.get("updated_at")
        stale_seconds = float(MAP.get("ROS2_POSE_STALE_SECONDS", 3.0))
        if not isinstance(updated_at, (int, float)) or time.time() - updated_at > stale_seconds:
            raise HTTPException(
                status_code=503,
                detail="Map pose is stale"
            )

        return payload

    @router.get("/map/meta")
    async def map_meta():

        payload = _read_json_file(_map_meta_file())
        if payload is None:
            raise HTTPException(
                status_code=404,
                detail="Map metadata not found"
            )

        return payload

    @router.get("/music/status")
    async def music_status():

        return {
            "playing": bool(
                music and music.is_playing()
            )
        }

    @router.post("/music/stop")
    async def music_stop():

        stopped = False

        if music:
            stopped = music.stop()

        return {
            "stopped": stopped,
            "playing": bool(
                music and music.is_playing()
            )
        }

    @router.post("/music/next")
    async def music_next():

        changed = False

        if music:
            changed = music.next()

        return {
            "changed": changed,
            "playing": bool(
                music and music.is_playing()
            )
        }

    @router.websocket("/ws/drive")
    async def drive_websocket(
        websocket: WebSocket
    ):

        await websocket.accept()

        try:
            while True:
                data = await websocket.receive_json()

                x = float(
                    data.get(
                        "x",
                        0
                    )
                )

                y = float(
                    data.get(
                        "y",
                        0
                    )
                )

                if y > 0 and _forward_motion_block_reason():
                    motor.stop()
                    continue

                if not motor.drive(x, y):
                    print(
                        "WS DRIVE BLOCKED:",
                        "x=", x,
                        "y=", y,
                        "reason=", motor.last_block_reason,
                        flush=True
                    )

        except WebSocketDisconnect:
            print(
                "WS DRIVE DISCONNECTED",
                flush=True
            )
            motor.stop()

    app.include_router(
        router
    )