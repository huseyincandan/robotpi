import json
import math
import shlex
import signal
import subprocess
import re
import shutil
import os
import time
from pathlib import Path

from config import MAP
from config import LIDAR


class Ros2SlamService:

    def __init__(self):

        self.enabled = True
        self._process = None
        self._lidar_process = None
        self._slam_process = None
        self._scan_process = None
        self._virtual_obstacles_process = None
        self._setup_bash = None
        self._lidar_cmd = None
        self._slam_cmd = None
        self._export_cmd = None
        self._scan_cmd = None
        self._virtual_obstacles_cmd = None

        self._cleanup_stale_processes()

        output_dir = Path(MAP.get("DIR", "output/maps"))
        if not output_dir.is_absolute():
            output_dir = Path.cwd() / output_dir

        output_dir.mkdir(parents=True, exist_ok=True)

        self.output_file = output_dir / MAP.get("LIVE_IMAGE_NAME", "live_map.pgm")
        self.pose_file = output_dir / MAP.get("ROS2_EXPORT_POSE_FILE", "live_pose.json")
        self.meta_file = output_dir / MAP.get("ROS2_EXPORT_META_FILE", "live_map_meta.json")
        self.scan_file = output_dir / MAP.get("ROS2_EXPORT_SCAN_FILE", "live_scan.json")
        self.virtual_obstacles_file = output_dir / MAP.get("ROS2_VIRTUAL_OBSTACLES_FILE", "virtual_obstacles.json")

        self._last_jump_check_pose = None
        self._last_imu_yaw_check = None
        self._slam_imu_yaw_error = 0.0
        self._imu_yaw_stationary_samples = 0
        self._imu_yaw_disturbance_active = False
        self._imu_yaw_disturbance_until = 0.0

        setup_bash = str(MAP.get("ROS2_SETUP_BASH", "~/ros2_ws/install/setup.bash"))
        setup_bash = str(Path(setup_bash).expanduser())
        self._setup_bash = setup_bash
        ros_python_bin = str(Path(str(MAP.get(
            "ROS2_PYTHON_BIN",
            "~/.micromamba/envs/ros2_jazzy/bin/python3"
        ))).expanduser())
        self._ros_bin_dir = str(Path(ros_python_bin).resolve().parent)
        self._ros_lib_dir = str(Path(ros_python_bin).resolve().parent.parent / "lib")
        self._rmw_implementation = str(MAP.get(
            "ROS2_RMW_IMPLEMENTATION",
            "rmw_cyclonedds_cpp"
        ))

        exporter_script = Path(__file__).resolve().parents[1] / "scripts" / "ros2_slam_exporter.py"
        scan_exporter_script = Path(__file__).resolve().parents[1] / "scripts" / "ros2_scan_exporter.py"
        virtual_obstacles_script = Path(__file__).resolve().parents[1] / "scripts" / "ros2_virtual_obstacles.py"

        if not Path(setup_bash).exists():
            raise RuntimeError(f"ROS2 setup file not found: {setup_bash}")

        if not exporter_script.exists():
            raise RuntimeError(f"ROS2 exporter script not found: {exporter_script}")

        if not scan_exporter_script.exists():
            raise RuntimeError(f"ROS2 scan exporter script not found: {scan_exporter_script}")

        if not virtual_obstacles_script.exists():
            raise RuntimeError(f"ROS2 virtual obstacles script not found: {virtual_obstacles_script}")

        preflight_cmd = (
            f"source {shlex.quote(setup_bash)} >/dev/null 2>&1 && "
            "command -v ros2 >/dev/null 2>&1 && "
            "python3 -c 'import rclpy'"
        )

        preflight = subprocess.run(
            ["bash", "-lc", preflight_cmd],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True
        )

        if preflight.returncode != 0:
            details = (preflight.stderr or preflight.stdout or "").strip()
            if not details:
                details = "ros2 command or rclpy not available in sourced environment"
            raise RuntimeError(f"ROS2 preflight failed: {details}")

        map_topic = str(MAP.get("ROS2_MAP_TOPIC", "/map"))
        tf_topic = str(MAP.get("ROS2_TF_TOPIC", "/tf"))
        map_frame = str(MAP.get("ROS2_MAP_FRAME", "map"))
        base_frame = str(MAP.get("ROS2_BASE_FRAME", "base_link"))
        export_hz = float(MAP.get("ROS2_EXPORT_RATE_HZ", 3.0))
        export_scan_hz = float(MAP.get("ROS2_EXPORT_SCAN_RATE_HZ", 8.0))

        autostart_stack = bool(MAP.get("ROS2_AUTOSTART_STACK", True))
        lidar_port = str(MAP.get("ROS2_LIDAR_PORT", LIDAR.get("PORT", "/dev/ttyUSB0")))
        lidar_baudrate = int(MAP.get("ROS2_LIDAR_BAUDRATE", LIDAR.get("BAUDRATE", 460800)))
        lidar_frame_id = str(MAP.get("ROS2_LIDAR_FRAME_ID", "laser"))
        lidar_driver = str(MAP.get("ROS2_LIDAR_DRIVER", "python_bridge")).lower().strip()
        lidar_reverse_angle = bool(MAP.get("ROS2_LIDAR_REVERSE_ANGLE", False))
        lidar_angle_offset_deg = float(MAP.get("ROS2_LIDAR_ANGLE_OFFSET_DEG", 0.0))
        slam_launch = str(MAP.get("ROS2_SLAM_LAUNCH", "online_async_launch.py"))
        slam_params = str(MAP.get("ROS2_SLAM_PARAMS_FILE", "")).strip()
        use_sim_time = bool(MAP.get("ROS2_USE_SIM_TIME", False))

        slam_params_arg = ""
        if slam_params:
            slam_params_path = Path(slam_params)
            if not slam_params_path.is_absolute():
                slam_params_path = Path.cwd() / slam_params_path

            if not slam_params_path.exists():
                raise RuntimeError(f"ROS2 SLAM params file not found: {slam_params_path}")

            slam_params_arg = f" slam_params_file:={shlex.quote(str(slam_params_path))}"

        if autostart_stack:
            if lidar_driver == "rplidar_ros":
                lidar_cmd = (
                    f"source {shlex.quote(setup_bash)} && "
                    "ros2 run rplidar_ros rplidar_composition "
                    "--ros-args "
                    f"-p serial_port:={shlex.quote(lidar_port)} "
                    f"-p serial_baudrate:={lidar_baudrate} "
                    f"-p frame_id:={shlex.quote(lidar_frame_id)} "
                    "-p inverted:=false "
                    "-p angle_compensate:=true"
                )
            else:
                bridge_script = Path(__file__).resolve().parents[1] / "scripts" / "ros2_rplidar_bridge.py"
                if not bridge_script.exists():
                    raise RuntimeError(f"ROS2 lidar bridge script not found: {bridge_script}")

                lidar_cmd = (
                    f"source {shlex.quote(setup_bash)} && "
                    f"python3 {shlex.quote(str(bridge_script))} "
                    f"--serial-port {shlex.quote(lidar_port)} "
                    f"--serial-baudrate {lidar_baudrate} "
                    f"--frame-id {shlex.quote(lidar_frame_id)} "
                    f"--angle-offset-deg {shlex.quote(str(lidar_angle_offset_deg))} "
                    f"{'--reverse-angle ' if lidar_reverse_angle else ''}"
                    "--disable-pwm-start"
                )

            self._lidar_cmd = lidar_cmd

            slam_cmd = (
                f"source {shlex.quote(setup_bash)} && "
                f"ros2 launch slam_toolbox {shlex.quote(slam_launch)}"
                f" use_sim_time:={'true' if use_sim_time else 'false'}"
                f" autostart:=true"
                f"{slam_params_arg}"
            )

            self._lidar_process = self._spawn_command(lidar_cmd)
            self._slam_process = self._spawn_command(slam_cmd)

            self._slam_cmd = slam_cmd

        shell_cmd = (
            f"source {shlex.quote(setup_bash)} && "
            f"python3 {shlex.quote(str(exporter_script))} "
            f"--map-topic {shlex.quote(map_topic)} "
            f"--tf-topic {shlex.quote(tf_topic)} "
            f"--map-frame {shlex.quote(map_frame)} "
            f"--base-frame {shlex.quote(base_frame)} "
            f"--rate {shlex.quote(str(export_hz))} "
            f"--output-pgm {shlex.quote(str(self.output_file))} "
            f"--output-pose {shlex.quote(str(self.pose_file))} "
            f"--output-meta {shlex.quote(str(self.meta_file))}"
        )

        self._export_cmd = shell_cmd

        scan_cmd = (
            f"source {shlex.quote(setup_bash)} && "
            f"python3 {shlex.quote(str(scan_exporter_script))} "
            "--scan-topic /scan "
            f"--rate {shlex.quote(str(export_scan_hz))} "
            f"--min-valid-cm {shlex.quote(str(float(LIDAR.get('MIN_VALID_CM', 12))))} "
            f"--max-valid-cm {shlex.quote(str(float(LIDAR.get('MAX_VALID_CM', 550))))} "
            f"--sector-deg {shlex.quote(str(float(LIDAR.get('SCAN_SECTOR_DEGREES', 30))))} "
            f"--output-scan {shlex.quote(str(self.scan_file))}"
        )

        self._scan_cmd = scan_cmd

        virtual_obstacles_cmd = (
            f"source {shlex.quote(setup_bash)} && "
            f"python3 {shlex.quote(str(virtual_obstacles_script))} "
            f"--input-file {shlex.quote(str(self.virtual_obstacles_file))} "
            f"--topic {shlex.quote(str(MAP.get('ROS2_VIRTUAL_OBSTACLES_TOPIC', '/virtual_obstacles')))} "
            f"--frame {shlex.quote(map_frame)} "
            f"--rate {shlex.quote(str(float(MAP.get('ROS2_VIRTUAL_OBSTACLES_RATE_HZ', 2.0))))} "
            f"--ring-radius-m {shlex.quote(str(float(MAP.get('ROS2_VIRTUAL_OBSTACLES_RING_RADIUS_M', 0.06))))} "
            f"--ring-points {shlex.quote(str(int(MAP.get('ROS2_VIRTUAL_OBSTACLES_RING_POINTS', 10))))} "
            f"--min-hit-count {shlex.quote(str(int(MAP.get('ROS2_VIRTUAL_OBSTACLES_MIN_HIT_COUNT', 2))))}"
        )

        self._virtual_obstacles_cmd = virtual_obstacles_cmd

        self._process = subprocess.Popen(
            ["bash", "-lc", self._with_ros_environment(shell_cmd)],
            cwd=str(Path.cwd()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )

        self._scan_process = subprocess.Popen(
            ["bash", "-lc", self._with_ros_environment(scan_cmd)],
            cwd=str(Path.cwd()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )

        self._virtual_obstacles_process = subprocess.Popen(
            ["bash", "-lc", self._with_ros_environment(virtual_obstacles_cmd)],
            cwd=str(Path.cwd()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )

    def _with_ros_environment(self, command):

        return (
            f"export PATH={shlex.quote(self._ros_bin_dir)}:$PATH && "
            f"export LD_LIBRARY_PATH={shlex.quote(self._ros_lib_dir)}:$LD_LIBRARY_PATH && "
            f"export RMW_IMPLEMENTATION={shlex.quote(self._rmw_implementation)} && "
            f"{command}"
        )

    def _spawn_command(self, shell_cmd):

        return subprocess.Popen(
            ["bash", "-lc", self._with_ros_environment(shell_cmd)],
            cwd=str(Path.cwd()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )

    def _terminate_process_group(self, process):

        if process is None:
            return

        code = process.poll()
        if code is not None:
            return

        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=2)
        except Exception:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                pass

    def _cleanup_stale_processes(self):

        patterns = [
            "ros2 launch slam_toolbox",
            "async_slam_toolbox_node",
            "ros2_slam_exporter.py",
            "ros2_scan_exporter.py",
            "ros2_virtual_obstacles.py",
            "ros2_rplidar_bridge.py",
            "rplidar_composition"
        ]

        for pattern in patterns:
            try:
                subprocess.run(
                    ["pkill", "-f", pattern],
                    cwd=str(Path.cwd()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2
                )
            except Exception:
                pass

    def _run_ros2_command(self, command, timeout=45):
        shell_cmd = f"source {shlex.quote(self._setup_bash)} >/dev/null 2>&1 && {command}"
        return subprocess.run(
            ["bash", "-lc", self._with_ros_environment(shell_cmd)],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=timeout
        )

    def status(self):

        if not self.enabled:
            return "disabled"

        if self._process is None:
            return "stopped"

        code = self._process.poll()

        if self._lidar_process is not None and self._lidar_process.poll() is not None:
            return f"lidar_stopped({self._lidar_process.poll()})"

        if self._slam_process is not None and self._slam_process.poll() is not None:
            return f"slam_stopped({self._slam_process.poll()})"

        if self._scan_process is not None and self._scan_process.poll() is not None:
            return f"scan_stopped({self._scan_process.poll()})"

        if self._virtual_obstacles_process is not None and self._virtual_obstacles_process.poll() is not None:
            return f"virtual_obstacles_stopped({self._virtual_obstacles_process.poll()})"

        if code is None:
            return "running"

        return f"stopped({code})"

    def detect_pose_jump(self):

        try:
            payload = json.loads(self.pose_file.read_text(encoding="utf-8"))
        except Exception:
            return None

        x = payload.get("x")
        y = payload.get("y")
        yaw = payload.get("yaw_rad")
        updated_at = payload.get("updated_at")

        if (
            not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
            or not isinstance(yaw, (int, float))
            or not isinstance(updated_at, (int, float))
        ):
            return None

        previous = self._last_jump_check_pose
        self._last_jump_check_pose = (x, y, yaw, updated_at)

        if previous is None:
            return None

        prev_x, prev_y, prev_yaw, prev_updated_at = previous
        dt = updated_at - prev_updated_at

        if dt <= 0:
            return None

        distance = math.hypot(x - prev_x, y - prev_y)
        speed = distance / dt
        yaw_delta = abs(math.atan2(math.sin(yaw - prev_yaw), math.cos(yaw - prev_yaw)))
        yaw_rate = yaw_delta / dt

        max_speed = float(MAP.get("MAP_JUMP_MAX_SPEED_MPS", 1.0))
        min_distance = float(MAP.get("MAP_JUMP_MIN_DISTANCE_M", 0.8))
        max_yaw_rate = float(MAP.get("MAP_JUMP_MAX_YAW_RATE_RAD_S", 2.0))
        min_yaw_delta = math.radians(float(MAP.get("MAP_JUMP_MIN_YAW_DEG", 30.0)))

        if distance >= min_distance and speed > max_speed:
            return {
                "distance_m": distance,
                "dt_sec": dt,
                "speed_mps": speed
            }

        if yaw_delta >= min_yaw_delta and yaw_rate > max_yaw_rate:
            return {
                "yaw_delta_deg": math.degrees(yaw_delta),
                "dt_sec": dt,
                "yaw_rate_rad_s": yaw_rate
            }

        return None

    def detect_imu_yaw_divergence(self, gyro_z_dps, robot_moving=False):

        try:
            payload = json.loads(self.pose_file.read_text(encoding="utf-8"))
            yaw = float(payload["yaw_rad"])
            updated_at = float(payload["updated_at"])
            gyro_z = math.radians(float(gyro_z_dps))
        except Exception:
            return None

        previous = self._last_imu_yaw_check
        self._last_imu_yaw_check = (yaw, updated_at, gyro_z)
        if previous is None:
            return None

        prev_yaw, prev_updated_at, prev_gyro_z = previous
        dt = updated_at - prev_updated_at
        if dt <= 0.0 or dt > 3.0:
            return None

        slam_delta = math.atan2(math.sin(yaw - prev_yaw), math.cos(yaw - prev_yaw))
        imu_delta = 0.5 * (prev_gyro_z + gyro_z) * dt
        instantaneous_error = math.atan2(
            math.sin(slam_delta - imu_delta),
            math.cos(slam_delta - imu_delta)
        )

        disturbance_delta = math.radians(float(
            MAP.get("MAP_IMU_YAW_DISTURBANCE_DELTA_DEG", 8.0)
        ))
        disturbance_grace = float(
            MAP.get("MAP_IMU_YAW_DISTURBANCE_GRACE_SECONDS", 3.0)
        )

        if abs(instantaneous_error) >= disturbance_delta:
            if not self._imu_yaw_disturbance_active:
                self._imu_yaw_disturbance_active = True
                self._imu_yaw_disturbance_until = updated_at + disturbance_grace

            if updated_at < self._imu_yaw_disturbance_until:
                self._slam_imu_yaw_error = 0.0
                self._imu_yaw_stationary_samples = 0
                return None
        else:
            self._imu_yaw_disturbance_active = False
            self._imu_yaw_disturbance_until = 0.0

        self._slam_imu_yaw_error = math.atan2(
            math.sin(self._slam_imu_yaw_error + instantaneous_error),
            math.cos(self._slam_imu_yaw_error + instantaneous_error)
        )

        if not robot_moving:
            self._slam_imu_yaw_error = 0.0
            self._imu_yaw_stationary_samples = 0
            self._imu_yaw_disturbance_active = False
            self._imu_yaw_disturbance_until = 0.0
            return None

        self._imu_yaw_stationary_samples += 1
        if self._imu_yaw_stationary_samples < 2:
            return None

        max_error = math.radians(float(MAP.get("MAP_IMU_YAW_MAX_ERROR_DEG", 60.0)))
        if abs(self._slam_imu_yaw_error) >= max_error:
            return {
                "slam_imu_yaw_error_deg": math.degrees(self._slam_imu_yaw_error),
                "slam_delta_deg": math.degrees(slam_delta),
                "imu_delta_deg": math.degrees(imu_delta),
                "dt_sec": dt
            }

        return None

    def reset(self):
        odom_reset = self._run_ros2_command(
            "ros2 service call /robotpi/reset_odom std_srvs/srv/Trigger '{}'",
            timeout=5
        )
        odom_reset_output = odom_reset.stdout.lower().replace(" ", "")
        odom_reset_ok = odom_reset.returncode == 0 and (
            "success=true" in odom_reset_output
            or "success:true" in odom_reset_output
        )

        completed = self._run_ros2_command(
            "ros2 service call /slam_toolbox/clear_changes slam_toolbox/srv/Clear '{}'",
            timeout=20
        )

        clear_ok = completed.returncode == 0

        for process in (self._process, self._scan_process, self._slam_process, self._lidar_process, self._virtual_obstacles_process):
            if process is None:
                continue

            self._terminate_process_group(process)

        self._process = None
        self._scan_process = None
        self._slam_process = None
        self._lidar_process = None
        self._virtual_obstacles_process = None

        self._clear_map_outputs()

        self._last_jump_check_pose = None
        self._last_imu_yaw_check = None
        self._slam_imu_yaw_error = 0.0
        self._imu_yaw_stationary_samples = 0
        self._imu_yaw_disturbance_active = False
        self._imu_yaw_disturbance_until = 0.0

        self._restart_stack_after_reset()

        outputs_ready = self._wait_for_map_outputs(timeout_sec=20.0)

        if clear_ok:
            mode = "slam_toolbox_clear_changes_and_stop"
            note = "ok"
        else:
            mode = "slam_cold_restart"
            note = (completed.stderr or completed.stdout or "slam_toolbox clear_changes failed").strip()[:240]

        if not outputs_ready:
            note = f"{note}; map outputs not ready within timeout"

        return {
            "status": "OK",
            "mode": mode,
            "note": note,
            "outputs_ready": outputs_ready,
            "odom_reset": odom_reset_ok
        }

    def _restart_stack_after_reset(self):

        if self._lidar_cmd:
            self._lidar_process = self._spawn_command(self._lidar_cmd)

        if self._slam_cmd:
            self._slam_process = self._spawn_command(self._slam_cmd)

        if self._export_cmd:
            self._process = self._spawn_command(self._export_cmd)

        if self._scan_cmd:
            self._scan_process = self._spawn_command(self._scan_cmd)

        if self._virtual_obstacles_cmd:
            self._virtual_obstacles_process = self._spawn_command(self._virtual_obstacles_cmd)

    def _clear_map_outputs(self):

        for path in (self.output_file, self.pose_file, self.meta_file, self.scan_file, self.virtual_obstacles_file):
            try:
                if path.exists() and path.is_file():
                    path.unlink()
            except Exception:
                pass

    def _wait_for_map_outputs(self, timeout_sec=20.0):

        deadline = time.time() + max(1.0, float(timeout_sec))
        while time.time() < deadline:
            if (
                self.output_file.exists()
                and self.pose_file.exists()
                and self.meta_file.exists()
            ):
                return True

            time.sleep(0.4)

        return (
            self.output_file.exists()
            and self.pose_file.exists()
            and self.meta_file.exists()
        )

    def save_map(self, output_base):

        output_base = Path(output_base)
        output_base.parent.mkdir(parents=True, exist_ok=True)

        completed = self._run_ros2_command(
            "ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap "
            f"\"{{name: {{data: '{str(output_base)}'}}}}\"",
            timeout=60
        )

        generated = [
            output_base.with_suffix(".pgm"),
            output_base.with_suffix(".yaml")
        ]

        existing = [
            str(path) for path in generated
            if path.exists() and path.is_file()
        ]

        output_text = (completed.stdout or "") + "\n" + (completed.stderr or "")
        result_match = re.search(r"result=(\d+)", output_text)
        result_code = int(result_match.group(1)) if result_match else None

        if completed.returncode != 0 or result_code != 0 or len(existing) < 2:
            fallback_saved = self._save_map_fallback(output_base)

            if fallback_saved:
                return {
                    "status": "OK",
                    "mode": "live_map_fallback",
                    "base": str(output_base),
                    "saved": fallback_saved,
                    "source": str(self.output_file),
                    "save_map_result_code": result_code,
                    "save_map_stdout_tail": (completed.stdout or "")[-800:],
                    "save_map_stderr_tail": (completed.stderr or "")[-800:]
                }

            return {
                "status": "ERROR",
                "mode": "slam_toolbox_save_map",
                "base": str(output_base),
                "saved": existing,
                "result_code": result_code,
                "command_stdout": (completed.stdout or "")[-1200:],
                "command_stderr": (completed.stderr or "")[-1200:]
            }

        return {
            "status": "OK",
            "mode": "slam_toolbox_save_map",
            "base": str(output_base),
            "saved": existing
        }

    def _save_map_fallback(self, output_base):

        source = Path(self.output_file)
        if not source.exists() or not source.is_file():
            return []

        target_pgm = output_base.with_suffix(".pgm")
        target_yaml = output_base.with_suffix(".yaml")

        try:
            shutil.copy2(source, target_pgm)
            metadata = self._get_dynamic_map_metadata()
            yaml_text = self._build_map_yaml(
                image_name=target_pgm.name,
                metadata=metadata
            )
            target_yaml.write_text(yaml_text, encoding="utf-8")
        except Exception:
            return []

        saved = []
        if target_pgm.exists() and target_pgm.is_file():
            saved.append(str(target_pgm))
        if target_yaml.exists() and target_yaml.is_file():
            saved.append(str(target_yaml))

        return saved

    def _get_dynamic_map_metadata(self):

        completed = self._run_ros2_command(
            "ros2 service call /slam_toolbox/dynamic_map nav_msgs/srv/GetMap '{}'",
            timeout=20
        )

        text = (completed.stdout or "") + "\n" + (completed.stderr or "")

        def _extract_float(pattern, default):
            matched = re.search(pattern, text)
            if not matched:
                return float(default)
            try:
                return float(matched.group(1))
            except Exception:
                return float(default)

        resolution = _extract_float(r"resolution=([0-9eE+\-.]+)", 0.05)
        origin_x = _extract_float(r"Point\(x=([0-9eE+\-.]+), y=", 0.0)
        origin_y = _extract_float(r"Point\(x=[0-9eE+\-.]+, y=([0-9eE+\-.]+), z=", 0.0)

        return {
            "resolution": resolution,
            "origin_x": origin_x,
            "origin_y": origin_y
        }

    def _build_map_yaml(self, image_name, metadata):

        resolution = float(metadata.get("resolution", 0.05))
        origin_x = float(metadata.get("origin_x", 0.0))
        origin_y = float(metadata.get("origin_y", 0.0))

        lines = [
            f"image: {image_name}",
            "mode: trinary",
            f"resolution: {resolution:.8f}",
            f"origin: [{origin_x:.8f}, {origin_y:.8f}, 0.00000000]",
            "negate: 0",
            "occupied_thresh: 0.65",
            "free_thresh: 0.25",
            ""
        ]

        return "\n".join(lines)

    def close(self):

        for process in (self._process, self._scan_process, self._slam_process, self._lidar_process, self._virtual_obstacles_process):
            if process is None:
                continue

            self._terminate_process_group(process)

        self._slam_process = None
        self._lidar_process = None
        self._scan_process = None
        self._virtual_obstacles_process = None

        self._process = None
