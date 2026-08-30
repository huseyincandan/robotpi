# Motor kontrolu artik Pi GPIO'sundan degil, donanim UART ile bagli ESP32-S3 (MotorEspS3.ino) uzerinden yapiliyor.
MOTOR_SERIAL = {
    "PORT": "/dev/ttyAMA0",
    "PORT_CANDIDATES": ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/serial0"],
    "BAUDRATE": 115200,
    "CONNECT_TIMEOUT_SECONDS": 25.0,
    "PING_RETRY_INTERVAL_SECONDS": 0.5,
    "READ_TIMEOUT_SECONDS": 0.05,
    "WRITE_TIMEOUT_SECONDS": 0.2,
    "KEEPALIVE_INTERVAL_SECONDS": 0.1
}

BOOT_SWITCH = {
    "PIN": 26,
    "SETTLE_SECONDS": 0.25
}

ULTRASONIC = {
    "TRIGGER_PIN": 5,
    "ECHO_PIN": 6,
    "MAX_DISTANCE_METERS": 4,
    "LOG_INTERVAL_SECONDS": 1,
    "SLOW_DISTANCE_CM": 90,
    "STOP_DISTANCE_CM": 20,
    # Ultrasonic is also published as sensor_msgs/Range (/ultrasonic_range) into
    # Nav2's costmap (see config/nav2_params.yaml range_layer, RangeSensorLayer),
    # so autonomous
    # driving already plans/steers around what the ultrasonic sees. This is
    # only a last-resort failsafe for the true blind gap below the lidar's
    # minimum range, so it can be tighter than the manual/joystick threshold.
    "AUTONOMOUS_STOP_DISTANCE_CM": 12,
    "MIN_FORWARD_SPEED_PERCENT": 12,
    "SAFETY_CHECK_INTERVAL_SECONDS": 0.05,
    "FILTER_WINDOW_SIZE": 7,
    "STABLE_MIN_SAMPLES": 5,
    "STABLE_MAX_SPREAD_CM": 3.0,
    "CLUSTER_MIN_SAMPLES": 3,
    "CLUSTER_MAX_SPREAD_CM": 3.0
}

MOTOR = {
    "MIN_EFFECTIVE_LINEAR_PERCENT": 12.0,
    "MIN_EFFECTIVE_TURN_PERCENT": 8.0,
    "LIDAR_VERIFY_ENABLED": True,
    "LIDAR_VERIFY_INTERVAL_SECONDS": 0.45,
    "LIDAR_VERIFY_MIN_DELTA_CM_LINEAR": 0.25,
    "LIDAR_VERIFY_MIN_DELTA_CM_TURN": 0.35,
    "LIDAR_VERIFY_CONSECUTIVE_MISSES_TO_BOOST": 3,
    "LIDAR_VERIFY_BOOST_STEP_PERCENT": 4.0,
    "LIDAR_VERIFY_BOOST_MAX_PERCENT": 25.0,
    # Koridorlarda duvarlar harekete paralel oldugu icin sektor-minimum mesafesi
    # kucuk otelemede neredeyse degismiyor; bu yuzden "verified" pratikte hemen
    # hic True olmuyor. Bu esikte sessizce (IMU sarsintisi olmadan) takilan
    # bir vaka canli gozlemlendi - IMU tetiklenmeden tek guvenlik agi buydu,
    # kapali oldugu icin robot hic kurtarmaya girmeden sonsuza kadar bekledi.
    # Yanlis pozitif riskini azaltmak icin miss esigini de yukselttik.
    "LIDAR_STALL_RECOVERY_ENABLED": True,
    "LIDAR_VERIFY_STALL_MISSES_TO_RECOVER": 12,
    # Ultrasonik engel yuzunden ileri hareket surekli reddedilirse (donus de
    # dahil, ornegin tekerlek bir esikte tutunamiyorsa), bu kadar saniye sonra
    # kurtarma manevrasi (geri cekil + don) tetiklenir.
    "ULTRASONIC_STALL_SECONDS_TO_RECOVER": 6.0,
    # Ultrasonik esik/zemin yansimasini yakin engel sanabilir. Recovery nedeni
    # IMU veya lidar stall ise ve on lidar sektoru bu kadar aciksa, dogrulanmis
    # geri + hizli ileri esik tarifine izin ver. Salt ultrasonic stall'da bypass
    # edilmez.
    "RECOVERY_STRAIGHT_PUSH_MIN_LIDAR_FRONT_CM": 70.0,
    # Alcak esikte ultrasonik zemini gorurken yatay lidar ilerideki acikligi
    # gorur. Iki sensor arasindaki bu fark yoksa nesneyi duvar kabul et.
    "RECOVERY_THRESHOLD_MIN_LIDAR_FRONT_CM": 45.0,
    "RECOVERY_THRESHOLD_SENSOR_GAP_CM": 10.0,
    "RECOVERY_THRESHOLD_MIN_ULTRASONIC_CM": 50.0,
    # An IMU stuck event with both the lidar front sector AND the ultrasonic
    # reading this clear means neither sensor can see whatever is holding the
    # robot back (e.g. a low table leg below both beams). Nav2's costmap has
    # no idea it's there either, so its own BT recovery can't route around it
    # - our own recovery must run regardless of drive source, and the spot
    # gets marked as a virtual obstacle (see ROS2_VIRTUAL_OBSTACLES_* above).
    "INVISIBLE_OBSTACLE_MIN_LIDAR_FRONT_CM": 45.0,
    "INVISIBLE_OBSTACLE_MIN_ULTRASONIC_CM": 30.0,
    "RECOVERY_LATCH_CLEAR_ULTRASONIC_CM": 50.0,
    "RECOVERY_LATCH_CLEAR_CONSECUTIVE_SAMPLES": 5,
    # Ultrasonik engelde ileri bileseni kesilirken Nav2'nin kacis donusunu
    # surdurmesine izin ver, ancak lidar taramasini bozan yuksek tork darbesi
    # uretme.
    # Sag arka tekerin daha zayif kaldigi yonu kucuk ve surekli bir taban tork
    # farkiyla telafi et. Darbeli kick SLAM yaw sicramalarina neden oldugu icin
    # tamamen kaldirildi.
    "RIGHT_TURN_EXTRA_MIN_TURN_PERCENT": 4.0
}

LIDAR = {
    "ENABLED": True,
    "PORT": "/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_da358bbe261ef111960cc3e40f0f12f8-if00-port0",
    "BAUDRATE": 460800,
    "DISABLE_PWM_START": True,
    "AUTO_CALIBRATE_ON_STARTUP": False,
    "AUTO_CALIBRATE_WAIT_SECONDS": 18,
    "AUTO_CALIBRATE_ATTEMPTS": 3,
    "AUTO_CALIBRATE_RETRY_SECONDS": 2.0,
    "OFFSET_STATE_FILE": "output/lidar/offset.json",
    "ANGLE_OFFSET_DEGREES": 0,
    "SCAN_SECTOR_DEGREES": 30,
    "MIN_VALID_CM": 12,
    "MAX_VALID_CM": 550,
    "FRONT_STOP_CM": 40,
    "FRONT_OPEN_CM": 70,
    "CENTERING_GAIN": 0.22,
    "CENTERING_DEADBAND_CM": 12,
    "CENTERING_MAX_TURN": 30,
    "RECONNECT_SECONDS": 2.0
}

POWER_MONITOR = {
    "ENABLED": False,
    "BUS": 1,
    "ADDRESS": 0x40,
    "SHUNT_OHMS": 0.1,
    "MIN_VOLTAGE": 9.9,
    "MAX_VOLTAGE": 12.6,
    "LOW_VOLTAGE_WARNING": 10.5,
    "DRIVE_SAFETY_ENABLED": True,
    "DRIVE_SAFETY_INTERVAL_SECONDS": 0.05,
    "DRIVE_READ_TIMEOUT_SECONDS": 0.35,
    "DRIVE_READ_ERROR_SAMPLES": 1,
    "DRIVE_CRITICAL_VOLTAGE": 10.8,
    "DRIVE_CRITICAL_SAMPLES": 2,
    "DRIVE_LOG_INTERVAL_SECONDS": 0.25
}

IMU = {
    "ENABLED": True,
    "BUS": 1,
    "ADDRESS": 0x68,
    # Acilista ve /imu/calibrate cagrisinda robot sabitken gyro sapmasini
    # (bias) olcup sonraki okumalardan cikarmak icin kullanilir; aksi halde
    # odom yaw robot tamamen dururken bile surekli driftler.
    "GYRO_BIAS_CALIBRATION_SAMPLES": 60,
    "GYRO_BIAS_CALIBRATION_INTERVAL_SECONDS": 0.02,
    "TILT_ACCEL_G": 1.15,
    "IMPACT_ACCEL_DELTA_G": 0.45,
    "UNEXPECTED_GYRO_DPS": 260,
    "STUCK_COOLDOWN_SECONDS": 1.5,
    # Motor PWM gurultusuyle olusan tekil I2C glitch'leri read_motion() bu kadar
    # deneme icinde kendiliginden atlatirsa BUS_RETRY_FAULT_COUNT'a eklenmez -
    # sadece TUM denemeler tukenirse gercek/kalici hata sayilir.
    "I2C_READ_MAX_ATTEMPTS": 3,
    "BUS_RETRY_FAULT_COUNT": 2,
    "BUS_RETRY_FAULT_WINDOW_SECONDS": 3.0,
    # 2026-08-21: elle test edilip esikte basarili oldugu dogrulanan tarif -
    # ~20cm geri (40% / 1.2s) + ~3s tam guclu duz itis. Degerler bu tarife
    # gore ayarlandi, degistirmeden once tekrar elle test et.
    "RECOVERY_BACKUP_SPEED": 40,
    "RECOVERY_BACKUP_SPEED_MAX": 80,
    # LIDAR_VERIFY_INTERVAL_SECONDS (0.45s) icin en az bir periyot birakir,
    # yoksa geri cekilme dogrulanamadan donus/ileri asamasina gecilir.
    "RECOVERY_BACKUP_SECONDS": 1.2,
    "RECOVERY_BACKUP_MAX_TRIES": 3,
    "RECOVERY_BACKUP_MAX_SECONDS": 1.6,
    # Was 45.0, lowered to 20.0 earlier - but 2026-08-30 that let an escalating
    # multi-try backup (up to 80%/1.6s x3, no nav2-style collision-checking of
    # its own) run for ~2m into a low window sill the lidar's current mount
    # height doesn't see (a real blind spot, not a false alarm) - robot hit the
    # window and wedged itself. Raised back to 40.0 as a safety margin until
    # the lidar mount is physically redesigned/lowered and the rear blind spot
    # is verified fixed. DO NOT re-lower without re-verifying rear FOV first.
    "RECOVERY_BACKUP_MIN_LIDAR_REAR_CM": 40.0,
    # 46% (nav2'nin de kullandigi tavan) yerinde donus icin yetersiz kaliyordu -
    # jiroskop testinde gercek donus olculememisti. Kurtarma kendi tavanini
    # kullandigi icin bagimsiz olarak yukseltiyoruz.
    "RECOVERY_TURN_SPEED": 58,
    "RECOVERY_TURN_HOLD_SPEED": 48,
    "RECOVERY_TURN_BREAKAWAY_SECONDS": 0.20,
    "RECOVERY_TURN_SECONDS": 0.75,
    "RECOVERY_TURN_RAMP_STEP_PERCENT": 5.0,
    "RECOVERY_TURN_RAMP_INTERVAL_SECONDS": 0.08,
    # Geri cekilme sonrasinda hem ultrasonik hem lidar onu acik gorurse esik
    # itisi denenebilir. Itis boyunca ultrasonik stop hicbir zaman bypass edilmez.
    "RECOVERY_STRAIGHT_PUSH_ENABLED": False,
    "RECOVERY_STRAIGHT_PUSH_MAX_ATTEMPTS": 2,
    # Elle test: 0.6s'lik itis esigi sadece kismen aştırıyordu (verified test
    # yaniltici sekilde "temiz" diyordu); esigi gercekten asmak ~3s surekli
    # tam guc gerektirdi.
    "RECOVERY_STRAIGHT_PUSH_SPEED": 95,
    "RECOVERY_STRAIGHT_PUSH_SECONDS": 2.2,
    "RECOVERY_FORWARD_TEST_SPEED": 25,
    # LIDAR_VERIFY_INTERVAL_SECONDS (0.45s) icin en az iki periyot birakir,
    # yoksa lidar hic dogrulama yapamadan test "temiz" sanip biter.
    "RECOVERY_FORWARD_TEST_SECONDS": 1.0,
    "RECOVERY_PAUSE_SECONDS": 0.08,
    "RECOVERY_MAX_SECONDS": 120,
    "VOICE_NOTIFICATIONS": True,
    "VOICE_ATTEMPT_INTERVAL_SECONDS": 8,
    "VOICE_STUCK_TEXT": "Takıldım. Kurtulmayı deniyorum.",
    "VOICE_ATTEMPT_TEXT": "Biraz geri gelip yön değiştirmeyi deniyorum.",
    "VOICE_CLEAR_TEXT": "Kurtuldum, devam ediyorum.",
    "VOICE_GIVE_UP_TEXT": "Kurtulamadım. Güvenlik için duruyorum."
}

CAMERA = {
    "WIDTH": 320,
    "HEIGHT": 240,
    "FPS": 15,
    "BUFFER_SIZE": 1,
    "FOURCC": "YUYV"
}

APP = {
    "HOST": "0.0.0.0",
    "PORT": 5000
}

MAP = {
    "PROVIDER": "ros2",
    "DIR": "output/maps",
    "SAVE_BASENAME": "robot_map",
    "LIVE_IMAGE_NAME": "live_map.pgm",
    "CLEAN_OUTPUT_ON_START": False,
    "ROS2_SETUP_BASH": "~/ros2_nav_ws/install/setup.bash",
    "ROS2_MAP_TOPIC": "/map",
    "ROS2_TF_TOPIC": "/tf",
    "ROS2_MAP_FRAME": "map",
    "ROS2_BASE_FRAME": "base_link",
    "ROS2_EXPORT_RATE_HZ": 1.0,
    "ROS2_EXPORT_POSE_FILE": "live_pose.json",
    "ROS2_POSE_STALE_SECONDS": 3.0,
    "ROS2_EXPORT_META_FILE": "live_map_meta.json",
    "ROS2_EXPORT_SCAN_FILE": "live_scan.json",
    "ROS2_EXPORT_SCAN_RATE_HZ": 4.0,
    "ROS2_SCAN_STALE_SECONDS": 15.0,
    # Low obstacles (table/couch legs) sit below the lidar's scan plane and
    # the ultrasonic's beam, so neither can ever route around them. When
    # services/motor.py's IMU stuck-detector fires with no corroborating
    # lidar/ultrasonic reading, it appends the robot's current map-frame pose
    # here; this file is republished as a PointCloud2 (see
    # scripts/ros2_virtual_obstacles.py) into Nav2's costmaps as a
    # mark-only, non-clearing source, so the planner keeps avoiding that
    # exact spot even across normal costmap clears.
    "ROS2_VIRTUAL_OBSTACLES_FILE": "virtual_obstacles.json",
    "ROS2_VIRTUAL_OBSTACLES_TOPIC": "/virtual_obstacles",
    "ROS2_VIRTUAL_OBSTACLES_RATE_HZ": 2.0,
    "ROS2_VIRTUAL_OBSTACLES_RING_RADIUS_M": 0.06,
    "ROS2_VIRTUAL_OBSTACLES_RING_POINTS": 10,
    # New marks within this radius of an existing one are treated as the same
    # obstacle (refreshes its timestamp instead of growing the file forever).
    "ROS2_VIRTUAL_OBSTACLES_DEDUPE_RADIUS_M": 0.20,
    "ROS2_VIRTUAL_OBSTACLES_MAX_ENTRIES": 200,
    # A single IMU stuck event can be a false positive (e.g. a momentary
    # sensor-reading gap during a real, visible wedge). Require the SAME spot
    # to be hit this many times before it's actually published into Nav2's
    # costmap, so one borderline detection can't permanently wall off a path
    # (marks are non-clearing/permanent, so a false positive here is costly).
    "ROS2_VIRTUAL_OBSTACLES_MIN_HIT_COUNT": 2,
    "ROS2_MOVEMENT_SCAN_MAX_AGE_SECONDS": 2.5,
    "ROS2_AUTOSTART_STACK": True,
    "ROS2_LIDAR_PORT": "/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_da358bbe261ef111960cc3e40f0f12f8-if00-port0",
    "ROS2_LIDAR_BAUDRATE": 460800,
    "ROS2_LIDAR_FRAME_ID": "laser",
    # LIDAR is mounted 8.5 cm behind the robot's geometric center.
    "ROS2_LIDAR_X_OFFSET_M": -0.085,
    "ROS2_LIDAR_DRIVER": "python_bridge",
    "ROS2_LIDAR_REVERSE_ANGLE": True,
    # 2026-08-30: lidar fiziksel olarak yeniden yerlestirildi (~90 derece donuk).
    # /lidar/calibrate ile olculdu: eski 180.0 offset'te gercek on, yayinlanan
    # /scan aci=234 derecede cikiyordu (0 derece = base_link ileri varsayimiyla
    # hizasiz, TF donusu sifir oldugu icin). Ilk duzeltme 306.0 uygulandi, ama
    # sonraki tek-seferlik olcum gurultuluydu (muhtemelen restart sonrasi
    # ultrasonik henuz stabil degilken alinan kirli veri) - 358.68 degerine
    # atlandi. Iki TEMIZ/bagimsiz restart sonrasi olcum (66.0 ve 67.79, ayni
    # bridge tabaninda) birbiriyle tutarli cikti - bu ikisinin ortalamasi
    # (66.9) guvenilir kabul edildi. Ara deger: 358.68 - 66.9 = 291.78.
    # Bu degerle harita/pose testinde (live_map.pgm'deki duvar/koltuk
    # noktalarinin PCA ile olculen dogrultusu vs yaw_rad) kalinti ~22-26 derece
    # sapma bulundu (3 bagimsiz olcum: koltuk 22.4/23.2, kapiya tam paralel/
    # tekerlek temasli 25.8 derece - hepsi ayni yonde ve tutarli). Ilk denemede
    # +24 eklendi (315.78) ama sapma 25.8 -> 49.6 dereceye CIKTI (yon ters
    # cikti, +24 dogruluyor: 25.8+24=49.8). Dogru yon cikarma: 291.78 - 25.8 =
    # 265.98. DOGRULANDI: bu degerle kapiya tam paralel (iki tekerlek de
    # temasli) referansta yakin mesafe olcumu 0.1 derece sapma verdi (mukemmel
    # eslesme). 2026-08-30 itibariyla nihai/guvenilir deger.
    "ROS2_LIDAR_ANGLE_OFFSET_DEG": 265.98,
    "ROS2_SLAM_LAUNCH": "online_async_launch.py",
    "ROS2_SLAM_PARAMS_FILE": "config/slam_toolbox_online_async.yaml",
    "ROS2_USE_SIM_TIME": False,
    "ROS2_MOVEMENT_LOCAL_SCAN_OFFSET_DEG": 0.0,
    "ROS2_NAV2_ENABLED": True,
    "ROS2_NAV2_AUTOSTART": True,
    "ROS2_NAV2_PARAMS_FILE": "config/nav2_params.yaml",
    "ROS2_NAV2_LAUNCH_PACKAGE": "nav2_bringup",
    "ROS2_NAV2_LAUNCH_FILE": "navigation_launch.py",
    "ROS2_EXPLORE_LAUNCH_PACKAGE": "explore_lite",
    "ROS2_EXPLORE_LAUNCH_FILE": "explore.launch.py",
    "ROS2_EXPLORE_PARAMS_FILE": "config/explore_lite_params.yaml",
    "ROS2_EXPLORE_LIVENESS_WATCHDOG_ENABLED": True,
    "ROS2_EXPLORE_IDLE_RECOVERY_SECONDS": 8.0,
    "ROS2_EXPLORE_RECOVERY_COOLDOWN_SECONDS": 20.0,
    "ROS2_CMDVEL_BRIDGE_APP_BASE_URL": "http://127.0.0.1:5000",
    "ROS2_PYTHON_BIN": "~/.micromamba/envs/ros2_jazzy/bin/python3",
    "ROS2_CMDVEL_TOPIC": "/cmd_vel",
    "ROS2_ODOM_TOPIC": "/odom",
    "ROS2_ODOM_FRAME": "odom",
    "ROS2_NAV2_MAX_LINEAR_X": 0.192,
    "ROS2_NAV2_MAX_ANGULAR_Z": 0.45,
    "ROS2_NAV2_MAX_DRIVE_PERCENT": 30.4,
    "ROS2_NAV2_MAX_TURN_PERCENT": 58.0,
    "ROS2_NAV2_TURN_HOLD_PERCENT": 58.0,
    "ROS2_NAV2_TURN_BREAKAWAY_SECONDS": 0.20,
    "ROS2_NAV2_ANGULAR_SLEW_RATE": 0.45,
    "ROS2_NAV2_MIN_LINEAR_SCALE_AT_MAX_TURN": 0.25,
    "ROS2_CMDVEL_ODOM_RATE_HZ": 50.0,
    # Fuse the real MPU6050 gyro_z (via GET /imu/motion) into odom yaw instead
    # of purely integrating commanded angular velocity, since the robot has no
    # wheel encoders. Falls back to commanded angular velocity automatically
    # if the IMU endpoint is unreachable/stale. Flip the sign if the robot's
    # IMU mounting reports positive gyro_z for clockwise (right) turns instead
    # of the REP103 convention (positive = counter-clockwise/left turn).
    "ROS2_CMDVEL_IMU_FUSION_ENABLED": True,
    "ROS2_CMDVEL_IMU_GYRO_SIGN": 1.0,
    "ROS2_CMDVEL_IMU_STATIONARY_DEADBAND_DPS": 0.5,
    # There are no wheel encoders, so commanded linear velocity is blindly
    # integrated into odom translation by default. On a slippery floor the
    # wheels can spin while the robot barely moves, which makes Nav2 think
    # it reached a waypoint it never actually reached. When the lidar's
    # omnidirectional motion signature (see MOTOR.LIDAR_VERIFY_*) reports
    # insufficient motion for the commanded drive, scale down the linear
    # velocity used for odom integration so Nav2's own costmap/planner sees
    # the shortfall and naturally keeps commanding the robot forward instead
    # of prematurely considering the move complete.
    "ROS2_CMDVEL_LIDAR_ODOM_CORRECTION_ENABLED": True,
    "ROS2_CMDVEL_LIDAR_ODOM_SLIP_SCALE": 0.35,
    # Joystick/sesli surus gibi Nav2 disi surus /cmd_vel'e hic mesaj yayinlamaz,
    # bu yuzden sadece cmd_vel'e bakarsak odom bu hareketleri kacirir ve harita
    # guncellenmez. Bunun yerine motorun o an gercekten uyguladigi y-yuzdesini
    # (kaynak fark etmeksizin, GET /imu/motion uzerinden) kullanarak odom
    # cevirisini hesapliyoruz.
    "ROS2_CMDVEL_MOTOR_ODOM_SOURCE_ENABLED": True,
    # Watchdog for slam_toolbox scan-matching failures: a real robot can't
    # move faster than ROS2_NAV2_MAX_LINEAR_X, so a much larger implied
    # speed between two pose samples means the map->odom TF jumped (a
    # disconnected/duplicated map region). Auto-recovers by resetting SLAM.
    "MAP_JUMP_WATCHDOG_ENABLED": True,
    "MAP_JUMP_MAX_SPEED_MPS": 1.0,
    "MAP_JUMP_MIN_DISTANCE_M": 0.8,
    "MAP_JUMP_MAX_YAW_RATE_RAD_S": 2.0,
    "MAP_JUMP_MIN_YAW_DEG": 30.0,
    "MAP_JUMP_CHECK_INTERVAL_SECONDS": 0.5,
    "MAP_IMU_YAW_WATCHDOG_ENABLED": True,
    "MAP_IMU_YAW_MAX_ERROR_DEG": 40.0,
    "MAP_IMU_YAW_DISTURBANCE_DELTA_DEG": 8.0,
    "MAP_IMU_YAW_DISTURBANCE_GRACE_SECONDS": 3.0
}

LOGGING = {
    "DIR": "logs",
    "KEEP_RUNS": 1,
    "RESET_ON_START": True,
    "APP_LOG_FILE": "app.log"
}

MOVEMENT = {
    "DRIVE_SPEED": 36,
    "TURN_SPEED": 48,
    "SECONDS_PER_METER": 10.5,
    "DEFAULT_MOVE_SECONDS": 0.8,
    "NUDGE_SECONDS": 0.35,
    "MIN_MOVE_SECONDS": 0.2,
    "MAX_MOVE_SECONDS": 15.0,
    "SAFETY_CHECK_INTERVAL_SECONDS": 0.08,
    "LIDAR_CALIBRATION_SETTLE_SECONDS": 0.35,
    "LIDAR_CALIBRATION_SAMPLES": 6,
    "LIDAR_CALIBRATION_SAMPLE_GAP_SECONDS": 0.07,
    "LIDAR_CALIBRATION_BIN_DEGREES": 12,
    "LIDAR_CALIBRATION_FORWARD_SPEED": 26,
    "LIDAR_CALIBRATION_FORWARD_SECONDS": 0.65,
    "LIDAR_CALIBRATION_BACK_SECONDS": 0.7,
    "LIDAR_CALIBRATION_MIN_DELTA_CM": 3.0,
    "LIDAR_CALIBRATION_MAX_DELTA_CM": 60.0,
    "LIDAR_CALIBRATION_CYCLES": 4,
    "LIDAR_CALIBRATION_MIN_VALID_CYCLES": 2,
    "LIDAR_CALIBRATION_TRIM_DEGREES": 22.0,
    "LIDAR_CALIBRATION_MIN_STRONG_DELTA_CM": 8.0,
    "LIDAR_CALIBRATION_MAX_ANGLE_SPREAD_DEG": 28.0,
    "TURN_90_SECONDS": 1.8,
    "MIN_TURN_SECONDS": 0.2,
    "MAX_TURN_SECONDS": 6.0
}

AUDIO = {
    "MICROPHONE_CARD": "U0x46d0x825",
    "MICROPHONE_DEVICE": "dsnoop:CARD=U0x46d0x825,DEV=0",
    "MICROPHONE_FORMAT": "alsa",
    "MICROPHONE_BUFFER_SIZE": "9600",
    "MICROPHONE_PERIOD_SIZE": "960",
    "MICROPHONE_FRAME_SAMPLES": 960,
    "MICROPHONE_STARTUP_VOLUME": 70,
    "SPEAKER_CARD": "UACDemoV10",
    "SPEAKER_DEVICE": "default:CARD=UACDemoV10",
    "SPEAKER_FALLBACK_DEVICES": [
        "plughw:CARD=UACDemoV10,DEV=0"
    ],
    "SPEAKER_FORMAT": "alsa",
    "SPEAKER_STARTUP_VOLUME": 70,
    "SPEAKER_MIN_VOLUME": 50,
    "SPEAKER_MAX_VOLUME": 80,
    "SAMPLE_RATE": "48000",
    "CHANNELS": "1",
    "PLAY_BROWSER_AUDIO_ON_ROBOT": True,
    "MUTE_ROBOT_MIC_WHILE_SPEAKER_ACTIVE": True,
    "REMOTE_AUDIO_ECHO_GUARD_LEVEL": 300,
    "REMOTE_AUDIO_ECHO_GUARD_HOLD_SECONDS": 0.25,
    "SPEAKER_BUFFER_SIZE": "16384",
    "SPEAKER_PERIOD_SIZE": "1024",
    "SPEAKER_OPTIONAL": True
}

SPEECH = {
    "PROVIDER": "piper",
    "PIPER_BIN": "tools/piper/piper",
    "PIPER_MODEL": "models/piper/tr_TR-dfki-medium.onnx",
    "OUTPUT_FILE": "/tmp/hamsibot-speech.wav",
    "OPENAI_MODEL": "gpt-4o-mini-tts",
    "OPENAI_VOICE": "onyx",
    "OPENAI_INSTRUCTIONS": "Türkçe konuş. Enerjik, sıcak ve net bir kadın sesi gibi oku. Diksiyonun temiz olsun, robotik veya monoton okuma yapma.",
    "OPENAI_OUTPUT_FILE": "/tmp/hamsibot-openai-speech.wav",
    "LOCAL_CACHE_DIR": "/tmp/hamsibot-tts-cache",
    "LOCAL_CACHE_MAX_CHARS": 80,
    "CHUNK_LONG_TEXT": True,
    "CHUNK_MIN_CHARS": 140,
    "WAKE_RESPONSE": "Efendim Hüseyin?",
    "WAKE_RESPONSE_PAUSE": 0.1,
    "ASSISTANT_RESPONSE_PAUSE": 1.0,
    "BEEP_FILE": "/tmp/hamsibot-beep.wav",
    "BEEP_FREQUENCY": 880,
    "BEEP_DURATION": 0.12,
    "BEEP_VOLUME": 0.25,
    "END_BEEP_FILE": "/tmp/hamsibot-end-beep.wav",
    "END_BEEP_FREQUENCY": 660,
    "END_BEEP_DURATION": 0.45,
    "END_BEEP_VOLUME": 0.25,
    "READY_BEEP_FILE": "/tmp/hamsibot-ready-beep.wav",
    "READY_BEEP_FREQUENCY": 1040,
    "READY_BEEP_DURATION": 0.8,
    "READY_BEEP_VOLUME": 0.22
}

STT = {
    "PROVIDER": "openai",
    "MODEL": "base",
    "OPENAI_MODEL": "gpt-4o-transcribe",
    "OPENAI_PROMPT": "Konuşma Türkçe. Kullanıcı HamsiBot adlı robot asistanla konuşuyor. Kaydın başında kısa bir bip sesi olabilir, bunu yok say. Eğer kayıtta anlaşılır insan konuşması yoksa hiçbir şey yazma. Kısa günlük soruları, robot komutlarını ve Türkçe özel isimleri doğru yaz.",
    "DEVICE": "cpu",
    "COMPUTE_TYPE": "int8",
    "LANGUAGE": "tr",
    # ReSpeaker 4 Mic Array donanimi sadece 16000Hz/6 kanal formatinda kayit
    # veriyor (kart adi = ArrayUAC10); kanal 0 islenmis/kazanc uygulanmis
    # cikis, digerleri ham mikrofon kanallari (~10x daha zayif) oldugu icin
    # kayittan sonra sadece kanal 0 cikarilip mono dosya olarak kaydediliyor.
    "MICROPHONE_DEVICE": "dsnoop:CARD=ArrayUAC10,DEV=0",
    "MICROPHONE_NATIVE_CHANNELS": 6,
    "MICROPHONE_SELECT_CHANNEL": 0,
    "SAMPLE_RATE": 16000,
    "CHANNELS": 6,
    "RECORD_SECONDS": 5,
    "RECORD_AFTER_CUE_DELAY": 0.15,
    "RECORD_FILE": "/tmp/hamsibot-question.wav",
    "TRIM_FILE": "/tmp/hamsibot-question-trimmed.wav",
    "TRIM_SILENCE": True,
    "TRIM_PADDING_SECONDS": 0.2,
    "TRIM_FRAME_MS": 30,
    "TRIM_MIN_RMS": 700,
    "SILENCE_SKIP_SECONDS": 0.25,
    "MIN_AUDIO_RMS": 700,
    "ACTIVE_SAMPLE_THRESHOLD": 1000,
    "MIN_ACTIVE_RATIO": 0.04,
    "POSSIBLE_AUDIO_RMS": 400,
    "POSSIBLE_ACTIVE_RATIO": 0.015,
    "MIN_TEXT_LENGTH": 3,
    "IGNORE_TEXTS": [
        "abone ol",
        "altyazı",
        "izlediğiniz için teşekkürler",
        "teşekkürler",
        "thanks for watching"
    ],
    "VAD_FILTER": True,
    "EMPTY_TURNS_TO_SLEEP": 2,
    "END_SESSION_COMMANDS": [
        "sohbeti bitir",
        "konuşmayı bitir",
        "oturumu kapat",
        "oturumu bitir",
        "görüşürüz",
        "tamam yeter",
        "tamam bitti",
        "kapat"
    ]
}

ASSISTANT = {
    "MODEL": "gpt-4o",
    "TEMPERATURE": 0.2,
    "USE_HISTORY": True,
    "MAX_HISTORY_MESSAGES": 8,
    "SYSTEM_PROMPT": "Sen HamsiBot adında Türkçe konuşan bir robot asistansın. Güncel tarih veya saat sorulursa sana verilen çalışma zamanı tarih bilgisini kullan; gerçek zamanlı internet, hava durumu, haber veya takvim erişimin yoksa bunu açıkça söyle ve uydurma. Kullanıcının söylediğini yanlış anlamış olabileceğini fark edersen tahmin yürütmeden kısa bir açıklama iste. Cevapların doğal, yardımsever, sıcak ve enerjik konuşma dilinde olsun. Sesli okunacağını düşünerek kısa konuş: genelde 1-3 cümle cevap ver. Emoji, markdown, yıldız, madde işareti, başlık ve liste kullanma."
}

INTENT = {
    "MODEL": "gpt-4o-mini",
    "TEMPERATURE": 0,
    "SYSTEM_PROMPT": "Kullanıcının Türkçe cümlesinden robot komut niyetini çıkar. Sadece JSON döndür. Desteklenen type değerleri: chat, local.time, system.shutdown, robot.move, audio.volume, web.search, music.play, music.stop, music.pause, music.resume, music.next, music.previous, music.genres. Saat kaç, bugünün tarihi nedir, günlerden ne gibi yerel sistem saati/tarihi sorularında local.time döndür ve query boş string olsun. Robotu, Raspberry Pi'yi veya sistemi tamamen kapatma isteklerinde system.shutdown döndür ve query boş string olsun. İleri git, geri git, sağa dön, sola dön, biraz geri git, yarım metre ileri git gibi robot hareket isteklerinde robot.move döndür ve query alanına kullanıcının hareket cümlesini aynen yaz. Sesi aç, sesi kıs, sesi yüzde elli yap gibi hoparlör ses seviyesi komutlarında audio.volume döndür ve query alanına cümleyi aynen yaz. Güncel hava durumu, maç sonucu, haber, son dakika, borsa, döviz veya internette aranması gereken güncel bilgi isteklerinde web.search döndür ve query alanına kısa arama metni yaz. Müzik/radyo çalma isteklerinde music.play döndür; query alanına yalnızca istenen müzik türünü yaz (örnek: caz, klasik, karadeniz, ankara), tür belirtilmemişse query boş string olsun. Hangi radyo kanalları/türleri var, kanalları listele, neler çalabilirsin gibi mevcut müzik türlerini sorma isteklerinde music.genres döndür ve query boş string olsun. Sonraki şarkı/kanal, kanalı değiştir, başka kanal/istasyon isteklerinde music.next, önceki şarkı/kanal isteklerinde music.previous, müzik duraklatma/bekletme komutlarında music.pause, müziğe devam etme/sürdürme/oynatma komutlarında music.resume, müzik durdurma/kapatma komutlarında music.stop döndür ve query boş string olsun. Emin değilsen chat döndür."
}

SYSTEM = {
    "SHUTDOWN_RESPONSE": "Tamam, kendimi kapatıyorum."
}

WEB = {
    "PLAN_MODEL": "gpt-4o-mini",
    "SEARCH_RESULT_LIMIT": 5,
    "WEATHER_DEFAULT_CITY": "Ankara",
    "PLAN_SYSTEM_PROMPT": "Kullanıcının Türkçe güncel bilgi sorusu için internetten nasıl veri aranacağını planla. Sadece JSON döndür. source değerleri: weather, news, web. Hava durumu, sıcaklık, yağmur gibi meteoroloji sorularında weather seç. Güncel olay, haber, maç sonucu, toplantı, zirve, tarih, son dakika, borsa/döviz gibi hızlı değişen konularda news seç. Genel ansiklopedik veya daha durağan internet bilgisi için web seç. query alanına Türkçe, kısa ve net arama sorgusu yaz. weather için city alanına sadece kullanıcı cümlesinde açıkça geçen şehri yaz; şehir açıkça geçmiyorsa city boş string olsun. day alanı today, tomorrow veya day_after_tomorrow olsun."
}

MUSIC = {
    "PLAYER": "mpv",
    "AUDIO_DEVICE": "alsa/default:CARD=UACDemoV10",
    "VOLUME": 66,
    "LOG_FILE": "/tmp/hamsibot-mpv.log",
    "STOP_RESPONSE": "Müziği durdurdum.",
    "PAUSE_RESPONSE": "Müziği duraklattım.",
    "RESUME_RESPONSE": "Müziğe devam ediyorum.",
    "NEXT_RESPONSE": "Sonraki kanala geçiyorum.",
    "PREVIOUS_RESPONSE": "Önceki kanala dönüyorum.",
    "NOT_PLAYING_RESPONSE": "Şu anda çalan bir müzik yok."
}

# YouTube uzerinden muzik calma, CDN'in bot korumasi (HTTP 403) yuzunden
# guvenilir calismadigi icin terk edildi. Bunun yerine kimlik dogrulama
# gerektirmeyen, dogrudan HTTP/Icecast akislari sunan Radio Browser API
# (https://api.radio-browser.info) uzerinden internet radyosu calinir.
RADIO = {
    "API_BASE": "https://de1.api.radio-browser.info",
    "USER_AGENT": "HamsiBot/1.0",
    "SEARCH_LIMIT": 10,
    "REQUEST_TIMEOUT_SECONDS": 8,
    "CONNECT_CHECK_SECONDS": 2.5,
    "MAX_STATION_ATTEMPTS": 3,
    "GENRES": [
        {
            "KEY": "jazz",
            "LABEL": "Caz müziği",
            "KEYWORDS": ["caz", "jazz"],
            "PARAMS": {"tag": "jazz"}
        },
        {
            "KEY": "classical",
            "LABEL": "Klasik müzik",
            "KEYWORDS": ["klasik"],
            "PARAMS": {"tag": "classical"}
        },
        {
            "KEY": "karadeniz",
            "LABEL": "Karadeniz müziği",
            "KEYWORDS": ["karadeniz"],
            "PARAMS": {"name": "karadeniz", "countrycode": "TR"}
        },
        {
            "KEY": "ankara",
            "LABEL": "Ankara müziği",
            "KEYWORDS": ["ankara"],
            "PARAMS": {"name": "ankara", "countrycode": "TR"}
        }
    ],
    "ERROR_RESPONSE": "Üzgünüm, radyo kanalına bağlanamadım. Başka bir komut verebilirsin.",
    "GENRES_LIST_RESPONSE_PREFIX": "Şu radyo türlerini çalabilirim: ",
    "PLAYING_RESPONSE_PREFIX": "Şu radyo kanalını açıyorum: "
}

WAKE = {
    "ENABLED": True,
    # ReSpeaker 4 Mic Array (native 16000Hz/6 kanal); kanal 0 islenmis/kazancli
    # cikis, wake-word modeli de zaten 16000Hz bekledigi icin capture orani
    # 1:1, ekstra downsample gerekmiyor.
    "MICROPHONE_DEVICE": "dsnoop:CARD=ArrayUAC10,DEV=0",
    "MICROPHONE_CHANNELS": 6,
    "MICROPHONE_SELECT_CHANNEL": 0,
    "CAPTURE_SAMPLE_RATE": 16000,
    "MODEL_NAME": "hey_jarvis",
    "THRESHOLD": 0.45,
    "CONSECUTIVE_DETECTIONS": 1,
    "LISTEN_DURING_MUSIC": True,
    "MUSIC_THRESHOLD": 0.38,
    "MUSIC_CONSECUTIVE_DETECTIONS": 2,
    "MUSIC_COMMAND_PAUSE_SECONDS": 0.6,
    "MUSIC_COMMAND_RECORD_SECONDS": 3,
    "STARTUP_DISCARD_CHUNKS": 10,
    "COOLDOWN_SECONDS": 4,
    "REARM_DELAY_SECONDS": 2,
    "MUSIC_REARM_DELAY_SECONDS": 1
}