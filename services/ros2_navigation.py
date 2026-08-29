import os
import shlex
import signal
import subprocess
import threading
import time
from pathlib import Path

from config import MAP


class Ros2NavigationService:

    def __init__(self):

        self.enabled = bool(MAP.get("ROS2_NAV2_ENABLED", True))
        self._nav2_process = None
        self._explore_process = None
        self._cmdvel_bridge_process = None
        self.recovery_cancel_event = threading.Event()
        self._setup_bash = str(Path(str(MAP.get("ROS2_SETUP_BASH", "~/ros2_ws/install/setup.bash"))).expanduser())
        self._ros_python_bin = str(Path(str(MAP.get("ROS2_PYTHON_BIN", "~/.micromamba/envs/ros2_jazzy/bin/python3"))).expanduser())
        self._ros_bin_dir = str(Path(self._ros_python_bin).resolve().parent)
        self._ros_lib_dir = str(Path(self._ros_python_bin).resolve().parent.parent / "lib")
        self._rmw_implementation = str(MAP.get("ROS2_RMW_IMPLEMENTATION", "rmw_cyclonedds_cpp"))

        params_file = Path(str(MAP.get("ROS2_NAV2_PARAMS_FILE", "config/nav2_params.yaml")))
        if not params_file.is_absolute():
            params_file = Path.cwd() / params_file
        self._nav2_params_file = params_file

        self._nav2_launch_package = str(MAP.get("ROS2_NAV2_LAUNCH_PACKAGE", "nav2_bringup"))
        self._nav2_launch_file = str(MAP.get("ROS2_NAV2_LAUNCH_FILE", "navigation_launch.py"))
        self._explore_launch_package = str(MAP.get("ROS2_EXPLORE_LAUNCH_PACKAGE", "explore_lite"))
        self._explore_launch_file = str(MAP.get("ROS2_EXPLORE_LAUNCH_FILE", "explore.launch.py"))

        explore_params_file = Path(str(MAP.get("ROS2_EXPLORE_PARAMS_FILE", "config/explore_lite_params.yaml")))
        if not explore_params_file.is_absolute():
            explore_params_file = Path.cwd() / explore_params_file
        self._explore_params_file = explore_params_file
        self._cmdvel_bridge_script = Path(__file__).resolve().parents[1] / "scripts" / "ros2_cmdvel_bridge.py"
        self._cmdvel_bridge_log = Path("/tmp/robotpi_cmdvel_bridge.log")
        self._nav2_log = Path("/tmp/robotpi_nav2.log")
        self._explore_log = Path("/tmp/robotpi_explore.log")

        if not self.enabled:
            return

        if not Path(self._setup_bash).exists():
            raise RuntimeError(f"ROS2 setup file not found: {self._setup_bash}")

        self._cleanup_stale_processes()

    def _spawn_command(self, shell_cmd):

        return subprocess.Popen(
            ["bash", "-lc", shell_cmd],
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

        names = [
            "lifecycle_manager",
            "controller_server",
            "planner_server",
            "bt_navigator",
            "behavior_server",
            "waypoint_follower",
            "smoother_server",
            "route_server",
            "velocity_smoother",
            "collision_monitor",
            "opennav_docking",
            "explore"
        ]

        for name in names:
            try:
                subprocess.run(
                    ["pkill", "-9", name],
                    cwd=str(Path.cwd()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2
                )
            except Exception:
                pass

        patterns = [
            "ros2 launch nav2_bringup",
            "lifecycle_manager_navigation",
            "ros2 launch explore_lite",
            "explore_node",
            "ros2_cmdvel_bridge.py"
        ]

        for pattern in patterns:
            try:
                subprocess.run(
                    ["pkill", "-9", "-f", pattern],
                    cwd=str(Path.cwd()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2
                )
            except Exception:
                pass

    def _run_ros2_command(self, command, timeout=20):

        shell_cmd = (
            f"export PATH={shlex.quote(self._ros_bin_dir)}:$PATH && "
            f"export LD_LIBRARY_PATH={shlex.quote(self._ros_lib_dir)}:$LD_LIBRARY_PATH && "
            f"export RMW_IMPLEMENTATION={shlex.quote(self._rmw_implementation)} && "
            f"source {shlex.quote(self._setup_bash)} >/dev/null 2>&1 && {command}"
        )

        return subprocess.run(
            ["bash", "-lc", shell_cmd],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=timeout
        )

    def _ensure_package_available(self, package_name):

        completed = self._run_ros2_command(
            f"ros2 pkg prefix {shlex.quote(package_name)}",
            timeout=8
        )

        if completed.returncode == 0:
            return {
                "status": "OK"
            }

        details = (completed.stderr or completed.stdout or "").strip()

        if not details:
            details = f"package '{package_name}' not found"

        return {
            "status": "ERROR",
            "message": details
        }

    def _status_text(self, process):

        if process is None:
            return "stopped"

        code = process.poll()
        if code is None:
            return "running"

        return f"stopped({code})"

    def _exploration_activity(self):

        if self._status_text(self._explore_process) != "running":
            return False, "process_stopped"

        try:
            with self._explore_log.open("rb") as log_file:
                log_file.seek(0, os.SEEK_END)
                size = log_file.tell()
                log_file.seek(max(0, size - 65536))
                text = log_file.read().decode("utf-8", "replace")
        except OSError:
            return False, "starting"

        no_frontiers_at = text.rfind("No frontiers found, stopping")
        goal_at = max(
            text.rfind("Sending goal to move base nav2"),
            text.rfind("Goal ACCEPTED")
        )
        if no_frontiers_at > goal_at:
            return False, "no_frontiers"

        if goal_at >= 0:
            return True, "goal_active"

        return False, "starting"

    def _start_cmdvel_bridge(self):

        if self._cmdvel_bridge_process is not None and self._cmdvel_bridge_process.poll() is None:
            return {
                "status": "OK",
                "message": "cmd_vel bridge already running"
            }

        if not self._cmdvel_bridge_script.exists():
            return {
                "status": "ERROR",
                "message": f"cmd_vel bridge script not found: {self._cmdvel_bridge_script}"
            }

        app_base_url = str(MAP.get("ROS2_CMDVEL_BRIDGE_APP_BASE_URL", "http://127.0.0.1:5000"))
        cmd_vel_topic = str(MAP.get("ROS2_CMDVEL_TOPIC", "/cmd_vel"))
        odom_topic = str(MAP.get("ROS2_ODOM_TOPIC", "/odom"))
        odom_frame = str(MAP.get("ROS2_ODOM_FRAME", "odom"))
        base_frame = str(MAP.get("ROS2_BASE_FRAME", "base_link"))
        laser_frame = str(MAP.get("ROS2_LIDAR_FRAME_ID", "laser"))
        laser_x_offset = float(MAP.get("ROS2_LIDAR_X_OFFSET_M", -0.085))
        ros_python_bin = self._ros_python_bin
        max_linear_x = float(MAP.get("ROS2_NAV2_MAX_LINEAR_X", 0.24))
        max_angular_z = float(MAP.get("ROS2_NAV2_MAX_ANGULAR_Z", 1.0))
        max_drive_percent = float(MAP.get("ROS2_NAV2_MAX_DRIVE_PERCENT", 38.0))
        max_turn_percent = float(MAP.get("ROS2_NAV2_MAX_TURN_PERCENT", 46.0))
        turn_hold_percent = float(MAP.get("ROS2_NAV2_TURN_HOLD_PERCENT", 52.0))
        turn_breakaway_seconds = float(
            MAP.get("ROS2_NAV2_TURN_BREAKAWAY_SECONDS", 0.30)
        )
        angular_slew_rate = float(MAP.get("ROS2_NAV2_ANGULAR_SLEW_RATE", 0.45))
        min_linear_scale_at_max_turn = float(
            MAP.get("ROS2_NAV2_MIN_LINEAR_SCALE_AT_MAX_TURN", 0.25)
        )
        odom_rate_hz = float(MAP.get("ROS2_CMDVEL_ODOM_RATE_HZ", 50.0))
        imu_fusion_enabled = bool(MAP.get("ROS2_CMDVEL_IMU_FUSION_ENABLED", True))
        imu_gyro_sign = float(MAP.get("ROS2_CMDVEL_IMU_GYRO_SIGN", 1.0))
        imu_stationary_deadband_dps = float(MAP.get("ROS2_CMDVEL_IMU_STATIONARY_DEADBAND_DPS", 0.5))
        lidar_odom_correction_enabled = bool(MAP.get("ROS2_CMDVEL_LIDAR_ODOM_CORRECTION_ENABLED", True))
        lidar_odom_slip_scale = float(MAP.get("ROS2_CMDVEL_LIDAR_ODOM_SLIP_SCALE", 0.35))
        motor_odom_source_enabled = bool(MAP.get("ROS2_CMDVEL_MOTOR_ODOM_SOURCE_ENABLED", True))

        if not Path(ros_python_bin).exists():
            return {
                "status": "ERROR",
                "message": f"ROS2 python not found: {ros_python_bin}"
            }

        shell_cmd = (
            f"rm -f {shlex.quote(str(self._cmdvel_bridge_log))} && "
            f"export PATH={shlex.quote(self._ros_bin_dir)}:$PATH && "
            f"export LD_LIBRARY_PATH={shlex.quote(self._ros_lib_dir)}:$LD_LIBRARY_PATH && "
            f"export RMW_IMPLEMENTATION={shlex.quote(self._rmw_implementation)} && "
            f"source {shlex.quote(self._setup_bash)} && "
            f"{shlex.quote(ros_python_bin)} {shlex.quote(str(self._cmdvel_bridge_script))} "
            f"--app-base-url {shlex.quote(app_base_url)} "
            f"--cmd-vel-topic {shlex.quote(cmd_vel_topic)} "
            f"--odom-topic {shlex.quote(odom_topic)} "
            f"--odom-frame {shlex.quote(odom_frame)} "
            f"--base-frame {shlex.quote(base_frame)} "
            f"--laser-frame {shlex.quote(laser_frame)} "
            f"--laser-x-offset {shlex.quote(str(laser_x_offset))} "
            f"--max-linear-x {shlex.quote(str(max_linear_x))} "
            f"--max-angular-z {shlex.quote(str(max_angular_z))} "
            f"--max-drive-percent {shlex.quote(str(max_drive_percent))} "
            f"--max-turn-percent {shlex.quote(str(max_turn_percent))} "
            f"--turn-hold-percent {shlex.quote(str(turn_hold_percent))} "
            f"--turn-breakaway-seconds {shlex.quote(str(turn_breakaway_seconds))} "
            f"--angular-slew-rate {shlex.quote(str(angular_slew_rate))} "
            f"--min-linear-scale-at-max-turn {shlex.quote(str(min_linear_scale_at_max_turn))} "
            f"--odom-rate-hz {shlex.quote(str(odom_rate_hz))} "
            f"--imu-fusion-enabled {shlex.quote(str(imu_fusion_enabled))} "
            f"--imu-gyro-sign {shlex.quote(str(imu_gyro_sign))} "
            f"--imu-stationary-deadband-dps {shlex.quote(str(imu_stationary_deadband_dps))} "
            f"--lidar-odom-correction-enabled {shlex.quote(str(lidar_odom_correction_enabled))} "
            f"--lidar-odom-slip-scale {shlex.quote(str(lidar_odom_slip_scale))} "
            f"--motor-odom-source-enabled {shlex.quote(str(motor_odom_source_enabled))} "
            f">> {shlex.quote(str(self._cmdvel_bridge_log))} 2>&1"
        )

        self._cmdvel_bridge_process = self._spawn_command(shell_cmd)
        time.sleep(0.5)

        return {
            "status": "OK",
            "message": "cmd_vel bridge started"
        }

    def _stop_cmdvel_bridge(self):

        self._terminate_process_group(self._cmdvel_bridge_process)
        self._cmdvel_bridge_process = None

    def _wait_for_cmdvel_bridge_ready(self, timeout_sec=8):

        odom_topic = str(MAP.get("ROS2_ODOM_TOPIC", "/odom"))
        command = (
            f"timeout {int(max(1, timeout_sec))} "
            f"ros2 topic echo {shlex.quote(odom_topic)} --once >/dev/null"
        )
        completed = self._run_ros2_command(command, timeout=int(timeout_sec) + 3)
        return completed.returncode == 0

    def _wait_for_tf_pair(self, parent_frame, child_frame, timeout_sec=20):

        tf_topic = str(MAP.get("ROS2_TF_TOPIC", "/tf"))
        deadline = time.time() + max(1.0, float(timeout_sec))

        while time.time() < deadline:
            command = f"timeout 2 ros2 topic echo {shlex.quote(tf_topic)} --once"
            completed = self._run_ros2_command(command, timeout=5)
            output = f"{completed.stdout}\n{completed.stderr}"

            if (
                f"frame_id: {parent_frame}" in output
                and f"child_frame_id: {child_frame}" in output
            ):
                return True

            time.sleep(0.25)

        return False

    def _wait_for_nav2_tf_readiness(self, timeout_sec=20):

        map_frame = str(MAP.get("ROS2_MAP_FRAME", "map"))
        odom_frame = str(MAP.get("ROS2_ODOM_FRAME", "odom"))
        base_frame = str(MAP.get("ROS2_BASE_FRAME", "base_link"))

        if not map_frame:
            return True

        if odom_frame and map_frame != odom_frame:
            if self._wait_for_tf_pair(map_frame, odom_frame, timeout_sec=timeout_sec):
                return True

        if base_frame and map_frame != base_frame:
            if self._wait_for_tf_pair(map_frame, base_frame, timeout_sec=timeout_sec):
                print(
                    f"NAV2 TF CHECK: proceeding with fallback TF {map_frame}->{base_frame}",
                    flush=True
                )
                return True

        return False

    def _wait_for_global_costmap_ready(self, timeout_sec=15):

        costmap_topic = str(MAP.get("ROS2_EXPLORE_COSTMAP_TOPIC", "/global_costmap/costmap"))
        command = (
            f"timeout {int(max(1, timeout_sec))} "
            f"ros2 topic echo {shlex.quote(costmap_topic)} --once >/dev/null"
        )
        completed = self._run_ros2_command(command, timeout=int(timeout_sec) + 3)
        return completed.returncode == 0

    def start_nav2(self):

        if not self.enabled:
            return {
                "status": "ERROR",
                "message": "Navigation service disabled"
            }

        if self._nav2_process is not None and self._nav2_process.poll() is None:
            return {
                "status": "OK",
                "message": "Navigation2 already running"
            }

        if not self._nav2_params_file.exists():
            return {
                "status": "ERROR",
                "message": f"Nav2 params file not found: {self._nav2_params_file}"
            }

        package_check = self._ensure_package_available(self._nav2_launch_package)
        if package_check.get("status") != "OK":
            return {
                "status": "ERROR",
                "message": f"Nav2 package check failed: {package_check.get('message', 'unknown error')}"
            }

        # Ensure stale Nav2/explore processes from previous runs do not poison lifecycle bringup.
        self._cleanup_stale_processes()
        self._nav2_process = None
        self._explore_process = None
        self._cmdvel_bridge_process = None

        bridge_result = self._start_cmdvel_bridge()
        if bridge_result.get("status") != "OK":
            return bridge_result

        # Avoid Nav2 lifecycle activation races by waiting for odom/TF publication.
        if not self._wait_for_cmdvel_bridge_ready(timeout_sec=8):
            self._stop_cmdvel_bridge()
            return {
                "status": "ERROR",
                "message": "cmd_vel bridge did not publish odom in time"
            }

        if not self._wait_for_nav2_tf_readiness(timeout_sec=20):
            map_frame = str(MAP.get("ROS2_MAP_FRAME", "map"))
            odom_frame = str(MAP.get("ROS2_ODOM_FRAME", "odom"))
            base_frame = str(MAP.get("ROS2_BASE_FRAME", "base_link"))
            self._stop_cmdvel_bridge()
            return {
                "status": "ERROR",
                "message": (
                    f"TF readiness failed before Nav2 bringup; checked "
                    f"{map_frame}->{odom_frame} and fallback {map_frame}->{base_frame}"
                )
            }

        use_sim_time = "true" if bool(MAP.get("ROS2_USE_SIM_TIME", False)) else "false"
        autostart = "true" if bool(MAP.get("ROS2_NAV2_AUTOSTART", True)) else "false"

        shell_cmd = (
            f"rm -f {shlex.quote(str(self._nav2_log))} && "
            f"export PATH={shlex.quote(self._ros_bin_dir)}:$PATH && "
            f"export LD_LIBRARY_PATH={shlex.quote(self._ros_lib_dir)}:$LD_LIBRARY_PATH && "
            f"export RMW_IMPLEMENTATION={shlex.quote(self._rmw_implementation)} && "
            f"source {shlex.quote(self._setup_bash)} && "
            f"ros2 launch {shlex.quote(self._nav2_launch_package)} {shlex.quote(self._nav2_launch_file)} "
            f"use_sim_time:={use_sim_time} "
            f"autostart:={autostart} "
            f"params_file:={shlex.quote(str(self._nav2_params_file))} "
            f">> {shlex.quote(str(self._nav2_log))} 2>&1"
        )

        self._nav2_process = self._spawn_command(shell_cmd)
        time.sleep(0.8)

        return {
            "status": "OK",
            "message": "Navigation2 launch started",
            "nav2_status": self._status_text(self._nav2_process)
        }

    def stop_nav2(self):

        self.stop_exploration()
        self._terminate_process_group(self._nav2_process)
        self._nav2_process = None
        self._stop_cmdvel_bridge()

        return {
            "status": "OK",
            "message": "Navigation2 stopped"
        }

    def start_exploration(self):

        if not self.enabled:
            return {
                "status": "ERROR",
                "message": "Navigation service disabled"
            }

        nav2_result = self.start_nav2()
        if nav2_result.get("status") != "OK":
            return nav2_result

        if self._explore_process is not None and self._explore_process.poll() is None:
            explore_active, explore_reason = self._exploration_activity()
            if explore_active or explore_reason == "starting":
                self.recovery_cancel_event.clear()
                return {
                    "status": "OK",
                    "message": "explore_lite already running",
                    "nav2_status": self._status_text(self._nav2_process),
                    "explore_status": self._status_text(self._explore_process)
                }
            self._terminate_process_group(self._explore_process)
            self._explore_process = None

        package_check = self._ensure_package_available(self._explore_launch_package)
        if package_check.get("status") != "OK":
            return {
                "status": "ERROR",
                "message": f"Explore package check failed: {package_check.get('message', 'unknown error')}"
            }

        if not self._explore_params_file.exists():
            return {
                "status": "ERROR",
                "message": f"Explore params file not found: {self._explore_params_file}"
            }

        # Nav2's lifecycle bringup (costmap layers etc.) takes several seconds after
        # the launch process starts. Without this wait, explore_lite's very first
        # frontier search could run before the global costmap was sized to include
        # the robot, logging "Robot out of costmap bounds" -> 0 frontiers found ->
        # explore_lite permanently stops itself (it never retries on its own after
        # that), leaving the robot idle indefinitely.
        if not self._wait_for_global_costmap_ready(timeout_sec=15):
            return {
                "status": "ERROR",
                "message": "global_costmap not ready before explore_lite launch"
            }

        # explore_lite's launch file does not expose a params_file argument. Run the
        # node directly so frontier discovery uses our tuned raw SLAM map settings;
        # Nav2 still validates and executes goals against its inflated costmaps.
        use_sim_time = "true" if bool(MAP.get("ROS2_USE_SIM_TIME", False)) else "false"
        shell_cmd = (
            f"rm -f {shlex.quote(str(self._explore_log))} && "
            f"export PATH={shlex.quote(self._ros_bin_dir)}:$PATH && "
            f"export LD_LIBRARY_PATH={shlex.quote(self._ros_lib_dir)}:$LD_LIBRARY_PATH && "
            f"export RMW_IMPLEMENTATION={shlex.quote(self._rmw_implementation)} && "
            f"source {shlex.quote(self._setup_bash)} && "
            f"ros2 run {shlex.quote(self._explore_launch_package)} explore --ros-args "
            f"-r __node:=explore_node "
            f"--params-file {shlex.quote(str(self._explore_params_file))} "
            f"-p use_sim_time:={use_sim_time} "
            f"--log-level explore_node:=debug "
            f"-r /tf:=tf -r /tf_static:=tf_static "
            f">> {shlex.quote(str(self._explore_log))} 2>&1"
        )

        self._explore_process = self._spawn_command(shell_cmd)
        time.sleep(0.6)
        self.recovery_cancel_event.clear()

        return {
            "status": "OK",
            "message": "explore_lite launch started",
            "nav2_status": self._status_text(self._nav2_process),
            "explore_status": self._status_text(self._explore_process)
        }

    def stop_exploration(self, cancel_recovery=True):

        if cancel_recovery:
            self.recovery_cancel_event.set()
        self._terminate_process_group(self._explore_process)
        self._explore_process = None

        return {
            "status": "OK",
            "message": "explore_lite stopped"
        }

    def status(self):

        if not self.enabled:
            return {
                "enabled": False,
                "nav2_status": "disabled",
                "explore_status": "disabled",
                "nav2_running": False,
                "explore_running": False,
                "explore_process_running": False,
                "explore_active": False,
                "explore_reason": "disabled",
                "autonomous_recovery_allowed": False
            }

        nav2_status = self._status_text(self._nav2_process)
        explore_status = self._status_text(self._explore_process)
        explore_active, explore_reason = self._exploration_activity()

        return {
            "enabled": True,
            "nav2_status": nav2_status,
            "explore_status": explore_status,
            "cmdvel_bridge_status": self._status_text(self._cmdvel_bridge_process),
            "nav2_running": nav2_status == "running",
            "explore_running": explore_status == "running" and explore_active,
            "explore_process_running": explore_status == "running",
            "explore_active": explore_active,
            "explore_reason": explore_reason,
            "autonomous_recovery_allowed": not self.recovery_cancel_event.is_set()
        }

    def close(self):

        self.stop_exploration()
        self.stop_nav2()