# Motor kontrolu artik Pi GPIO'sundan degil, donanim UART ile bagli ESP32-S3 (MotorEspS3.ino) uzerinden yapiliyor.
# 2026-09-07: joystick (manuel) ve nav2 donuslerinin ikisi de ayri ayri
# ayarlaniyordu - canli testte manuel x=40 (~%40) 0.6s'de ~150 derece donmesi
# asiri agresif bulundu. Tek bir paylasilan tavan ile ikisi de ayni
# yumusaklikta tutuluyor (bkz. MOTOR.MAX_TURN_PERCENT ve
# MAP.ROS2_NAV2_MAX_TURN_PERCENT/ROS2_NAV2_TURN_HOLD_PERCENT).
# Ilk denemede 30.0 verildi, ama canli testte (farkli sure ile karsilastirilmis
# olsa da) beklenenden cok daha yavas donduk - dusuk yuzdede patinaj/tutunamama
# riski de var. 36.0'a yukseltildi, ayni sure (0.6s) ile adil karsilastirma
# yapilarak dogrulandi.
SHARED_MAX_TURN_PERCENT = 36.0

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
    # Manuel/joystick donusler icin ust sinir - nav2 ile ortak, bkz. yukaridaki
    # SHARED_MAX_TURN_PERCENT notu.
    "MAX_TURN_PERCENT": SHARED_MAX_TURN_PERCENT,
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
    "ENABLED": True,
    # 2026-09-06: INA219 artik Pi'nin I2C hattinda degil, ESP32-S3'un kendi
    # I2C hattinda (SDA=41, SCL=42) - BUS/ADDRESS artik kullanilmiyor (sadece
    # donanim tekrar Pi'ye baglanirsa diye Ina219Service'de saklaniyor).
    # Veriler S3'ten UART "TELEM" satirlari ile gelir (bkz. EspPowerBridge).
    "BUS": 1,
    "ADDRESS": 0x40,
    "SHUNT_OHMS": 0.1,
    # S3'ten bu sureden daha eski TELEM verisi "okuma hatasi" (TimeoutError) sayilir.
    "ESP_TELEM_MAX_AGE_SECONDS": 1.0,
    "MIN_VOLTAGE": 9.9,
    "MAX_VOLTAGE": 12.6,
    "LOW_VOLTAGE_WARNING": 10.5,
    "DRIVE_SAFETY_ENABLED": True,
    "DRIVE_SAFETY_INTERVAL_SECONDS": 0.05,
    "DRIVE_READ_TIMEOUT_SECONDS": 0.35,
    # 2026-09-14: was 1 - a SINGLE transient TELEM read timeout (e.g. one late
    # ESP UART line during heavy traffic) instantly latched power_fault=True
    # forever (see app.py _run_power_safety_watchdog comment) with no way to
    # recover except a full app restart. This silently blocked ALL /drive
    # commands (both manual and nav2) for the rest of the process lifetime
    # while still returning HTTP 200 - found to be the actual root cause of a
    # "robot completely refuses to move" incident that looked like a
    # mechanical/rotation problem from the outside. Raised to 3 so a lone
    # blip doesn't trip it; a real sustained comms failure still trips within
    # ~3 read cycles.
    "DRIVE_READ_ERROR_SAMPLES": 3,
    "DRIVE_CRITICAL_VOLTAGE": 10.8,
    "DRIVE_CRITICAL_SAMPLES": 2,
    "DRIVE_LOG_INTERVAL_SECONDS": 0.25,
    # 2026-09-14: number of consecutive healthy reads required to
    # self-clear a power_fault that was caused by reason="power_monitor_read"
    # (a comms/telemetry glitch, not a real low-voltage trip). A genuine
    # low-voltage trip (reason absent, real bus_voltage sample recorded)
    # NEVER auto-clears - that stays latched on purpose, requiring an
    # operator to notice/restart, since driving on a truly critical battery
    # is a real hazard.
    "DRIVE_FAULT_CLEAR_SAMPLES": 5
}

IMU = {
    "ENABLED": True,
    # 2026-09-06: MPU6050 artik Pi'nin I2C hattinda degil, ESP32-S3'un kendi
    # I2C hattinda (SDA=41, SCL=42) - BUS/ADDRESS artik kullanilmiyor (sadece
    # donanim tekrar Pi'ye baglanirsa diye Mpu6050Service'de saklaniyor).
    # Veriler S3'ten UART "TELEM" satirlari ile gelir (bkz. EspImuBridge).
    "BUS": 1,
    "ADDRESS": 0x68,
    # S3'ten bu sureden daha eski TELEM verisi "okuma hatasi" (TimeoutError) sayilir.
    "ESP_TELEM_MAX_AGE_SECONDS": 1.0,
    # Acilista ve /imu/calibrate cagrisinda robot sabitken gyro sapmasini
    # (bias) olcup sonraki okumalardan cikarmak icin kullanilir; aksi halde
    # odom yaw robot tamamen dururken bile surekli driftler.
    "GYRO_BIAS_CALIBRATION_SAMPLES": 60,
    "GYRO_BIAS_CALIBRATION_INTERVAL_SECONDS": 0.02,
    "TILT_ACCEL_G": 1.15,
    # Was 0.45 - live-captured a false-positive IMU-stuck trip during an
    # entirely benign small controlled forward move (accel_delta=0.58,
    # horizontal_accel=0.03 so clearly not a tilt/impact, just ordinary
    # drive/stop vibration). Raised with margin above that observed value;
    # re-verify against a real impact if this ever misses a genuine hit.
    # 2026-09-07: was 0.70, still false-tripped repeatedly during ordinary
    # controlled driving (observed benign values: 0.58, 0.72, 0.77, 0.80,
    # 0.88, 0.90, 0.92 - all confirmed no real obstacle/collision). Added
    # IMPACT_STARTUP_GRACE_SECONDS (see below) to rule out the "start of
    # motion" jolt specifically, but false trips kept happening even mid-burst
    # and once during ordinary nav2-commanded turning (gyro_total=76 legitimately
    # elevated from a real turn, not impact) - so requiring gyro/tilt
    # corroboration doesn't work either, since real turning also elevates
    # gyro. This chassis's ordinary driving vibration alone regularly produces
    # accel_delta up to ~0.9g - raised with real margin above the highest
    # confirmed-benign observation (0.92) so ordinary driving stops tripping
    # this. If this ever misses a genuine impact, re-verify against a real
    # hit before lowering again.
    "IMPACT_ACCEL_DELTA_G": 1.15,
    # Suppresses ONLY the "impact" reason for this short window right after a
    # stop->drive transition (the single moment most likely to be a pure
    # mechanical jolt, not a real hit) - tilt/rotation stay fully active the
    # whole time. Kept as a secondary safeguard alongside the higher
    # threshold above; see services/imu.py detect_stuck().
    "IMPACT_STARTUP_GRACE_SECONDS": 0.6,
    "UNEXPECTED_GYRO_DPS": 260,
    "STUCK_COOLDOWN_SECONDS": 1.5,
    # Motor PWM gurultusuyle olusan tekil I2C glitch'leri read_motion() bu kadar
    # deneme icinde kendiliginden atlatirsa BUS_RETRY_FAULT_COUNT'a eklenmez -
    # sadece TUM denemeler tukenirse gercek/kalici hata sayilir.
    "I2C_READ_MAX_ATTEMPTS": 3,
    "BUS_RETRY_FAULT_COUNT": 2,
    "BUS_RETRY_FAULT_WINDOW_SECONDS": 3.0,
    # Was 45.0, lowered to 20.0 earlier - but 2026-08-30 that let an escalating
    # multi-try backup (up to 80%/1.6s x3, no nav2-style collision-checking of
    # its own) run for ~2m into a low window sill the lidar's current mount
    # height doesn't see (a real blind spot, not a false alarm) - robot hit the
    # window and wedged itself. Raised back to 40.0 as a safety margin until
    # the lidar mount is physically redesigned/lowered and the rear blind spot
    # is verified fixed. DO NOT re-lower without re-verifying rear FOV first.
    "RECOVERY_BACKUP_MIN_LIDAR_REAR_CM": 40.0
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
    "ROS2_MOVEMENT_SCAN_MAX_AGE_SECONDS": 2.5,
    "ROS2_AUTOSTART_STACK": True,
    "ROS2_LIDAR_PORT": "/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_da358bbe261ef111960cc3e40f0f12f8-if00-port0",
    "ROS2_LIDAR_BAUDRATE": 460800,
    "ROS2_LIDAR_FRAME_ID": "laser",
    # LIDAR is mounted 8.5 cm behind the robot's geometric center.
    "ROS2_LIDAR_X_OFFSET_M": -0.085,
    "ROS2_LIDAR_DRIVER": "python_bridge",
    "ROS2_LIDAR_REVERSE_ANGLE": True,
    # TEK lidar montaj-acisi offset'i (obstacle-avoidance proxy'sindeki eski
    # ayri ROS2_MOVEMENT_LOCAL_SCAN_OFFSET_DEG kaldirildi, artik yalnizca bu
    # deger var; /scan zaten dogru yayinlaniyorsa proxy ek ofsete ihtiyac
    # duymaz). 2026-08-30: lidar fiziksel olarak yeniden yerlestirildi (~90
    # derece donuk). /lidar/calibrate ile olculdu: eski 180.0 offset'te gercek
    # on, yayinlanan /scan aci=234 derecede cikiyordu. Ilk duzeltme 306.0
    # uygulandi, ama sonraki tek-seferlik olcum gurultuluydu - 358.68 degerine
    # atlandi. Iki TEMIZ/bagimsiz restart sonrasi olcum (66.0 ve 67.79)
    # birbiriyle tutarli cikti - ortalamasi (66.9) guvenilir kabul edildi. Ara
    # deger: 358.68 - 66.9 = 291.78. Harita/pose testinde (PCA ile duvar
    # dogrultusu vs yaw_rad) kalinti ~22-26 derece sapma bulundu, dogru yon
    # cikarma ile 291.78 - 25.8 = 265.98 bulundu, kapiya paralel referansta
    # 0.1 derece sapma verdi (2026-08-30 degeri).
    # 2026-09-17: lidar tekrar farkli monte edildi. /lidar/calibrate ile
    # (motion-probe yontemi, cycles_used=2/4, spread=12.0deg, guclu delta
    # -21.35/-31.35cm) gercek on'un o anki /scan uzayinda 142.86 derecede
    # oldugu olculdu -> ilk kaba deger = 265.98 - 142.86 = 123.12 (bu KABA
    # tahmin, motion-probe yontemi hassas kalibrasyon icin guvenilmez).
    # Titiz dogrulama: robot bir kanepenin duz yuzeyine gozle paralel
    # park edildi (kanepe solda ~12cm). Ham /scan verisinde (angle_deg,
    # distance_cm) kanepeye ait 82 nokta (aci 56-193 derece araligi,
    # PCA elongation ratio ~6000-6800 = neredeyse mukemmel duz cizgi)
    # PCA ile duz cizgi olarak fit edildi: cizginin yerel /scan
    # acisi (mod 180) = ~34.3 derece bulundu (3 bagimsiz olcum: 34.33,
    # 34.31, 34.28 - tutarli). Robot fiziksel olarak kanepeye paralel
    # oldugundan bu cizginin 0/180 derecede olcumu beklenirdi; 34.3
    # derecelik sapma net bir kalibrasyon hatasi. Ayni anda harita+pose
    # tabanli eski yontemle de capraz dogrulama yapildi (~33.7-33.8
    # derece, ters isaretli ama ayni buyuklukte - iki bagimsiz yontem
    # birbirini dogruluyor). Duzeltme: yeni_offset = eski_offset -
    # olculen_sapma (2026-08-30'daki isaret dersine gore, once kucuk
    # bir test ile dogrulanip sonra netlestirildi): 123.12 - 34.3 =
    # 88.82. Restart sonrasi ayni yontemle tekrar olculup teyit edildi.
    # 88.82 - 34.3 duzeltmesi 88.82 -> restart sonrasi ayni yontemle tekrar
    # olculdu: sapma 34.3 -> 0.45 dereceye dustu (dogru yon dogrulandi).
    # Son ince ayar: 88.82 - 0.45 = 88.37 -> restart + tekrar olcum: sapma
    # -0.42 derece (ratio ~6763, cok temiz cizgi). NIHAI DOGRULANMIS DEGER.
    "ROS2_LIDAR_ANGLE_OFFSET_DEG": 88.37,
    "ROS2_SLAM_LAUNCH": "online_async_launch.py",
    "ROS2_SLAM_PARAMS_FILE": "config/slam_toolbox_online_async.yaml",
    "ROS2_USE_SIM_TIME": False,
    "ROS2_NAV2_ENABLED": True,
    "ROS2_NAV2_AUTOSTART": True,
    "ROS2_NAV2_PARAMS_FILE": "config/nav2_params.yaml",
    "ROS2_NAV2_LAUNCH_PACKAGE": "nav2_bringup",
    "ROS2_NAV2_LAUNCH_FILE": "navigation_launch.py",
    "ROS2_EXPLORE_LAUNCH_PACKAGE": "explore_lite",
    "ROS2_EXPLORE_LAUNCH_FILE": "explore.launch.py",
    "ROS2_EXPLORE_PARAMS_FILE": "config/explore_lite_params.yaml",
    "ROS2_CMDVEL_BRIDGE_APP_BASE_URL": "http://127.0.0.1:5000",
    "ROS2_PYTHON_BIN": "~/.micromamba/envs/ros2_jazzy/bin/python3",
    "ROS2_CMDVEL_TOPIC": "/cmd_vel",
    # Final fused odom topic (published by robot_localization's EKF, see
    # ROS2_EKF_PARAMS_FILE) - this is what nav2_params.yaml/collision_monitor
    # consume. ROS2_ODOM_RAW_TOPIC is the EKF's own unfused input from
    # ros2_cmdvel_bridge.py - since 2026-09-13 this can be real encoder-tick-
    # derived wheel odometry (see ROS2_CMDVEL_ENCODER_ODOM_SOURCE_ENABLED
    # below) instead of the older commanded-velocity estimate.
    "ROS2_ODOM_TOPIC": "/odom",
    "ROS2_ODOM_RAW_TOPIC": "/odom_raw",
    "ROS2_ODOM_FRAME": "odom",
    "ROS2_EKF_PARAMS_FILE": "config/ekf.yaml",
    # Twist covariances (variance, m/s^2 and rad/s^2) for the raw odom
    # source's linear.x/angular.z fields - only linear.x is actually fused
    # (config/ekf.yaml's odom0_config), angular.z is published for
    # debug/consistency only.
    "ROS2_ODOM_VX_VARIANCE": 0.01,
    "ROS2_ODOM_VYAW_VARIANCE": 0.05,
    # 2026-09-06: kullanici manevralarin (ozellikle donuslerin) cok hizli/
    # sert oldugunu bildirdi - kurtarma manevrasi (MOTOR.RECOVERY_*) ayri bir
    # config oldugu icin bundan etkilenmez, sadece nav2/explore'un normal
    # surusu ~%25 yavaslatildi.
    "ROS2_NAV2_MAX_LINEAR_X": 0.144,
    "ROS2_NAV2_MAX_ANGULAR_Z": 0.34,
    "ROS2_NAV2_MAX_DRIVE_PERCENT": 22.8,
    "ROS2_NAV2_MAX_TURN_PERCENT": SHARED_MAX_TURN_PERCENT,
    "ROS2_NAV2_TURN_HOLD_PERCENT": SHARED_MAX_TURN_PERCENT,
    "ROS2_NAV2_TURN_BREAKAWAY_SECONDS": 0.20,
    "ROS2_NAV2_ANGULAR_SLEW_RATE": 0.45,
    "ROS2_NAV2_MIN_LINEAR_SCALE_AT_MAX_TURN": 0.25,
    "ROS2_CMDVEL_ODOM_RATE_HZ": 50.0,
    # Real MPU6050 gyro_z (via GET /imu/motion, polled independently by
    # scripts/ros2_imu_bridge.py) is fused into yaw by robot_localization's
    # EKF (config/ekf.yaml) instead of hand-rolled integration here. Flip
    # ROS2_IMU_GYRO_SIGN if the robot's IMU mounting reports positive gyro_z
    # for clockwise (right) turns instead of the REP103 convention (positive
    # = counter-clockwise/left turn).
    "ROS2_IMU_TOPIC": "/imu/data",
    "ROS2_IMU_FRAME": "base_link",
    "ROS2_IMU_RATE_HZ": 50.0,
    "ROS2_IMU_GYRO_SIGN": 1.0,
    "ROS2_IMU_STATIONARY_DEADBAND_DPS": 0.5,
    "ROS2_IMU_GYRO_Z_VARIANCE": 0.02,
    # Real wheel encoders (MotorEspS3.ino ENC_RL_A/B, ENC_RR_A/B, last two
    # TELEM fields) are the odom translation source, fused by robot_localization's
    # EKF (config/ekf.yaml). Calibrated 2026-09-14 via SLAM-pose-vs-tick-delta
    # measurement (see /memories/repo/robotpi_slam_notes.md for method).
    "ROS2_CMDVEL_ENCODER_ODOM_SOURCE_ENABLED": True,
    "ROS2_ENCODER_TICKS_PER_METER": 21786.0,
    "ROS2_ENCODER_TRACK_WIDTH_M": 0.243,
    "ROS2_ENCODER_MAX_AGE_SECONDS": 0.5,
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
    # 2026-09-18: koridorda (hicbir engel yokken) surekli donup durma
    # olayinin kok nedeni - scan matcher uzun/simetrik gorunumlu koridorda
    # ~180 derece ters yonlu bir eslesmeyi dogru sanip kilitleniyor (bkz.
    # config/slam_toolbox_online_async.yaml 2026-09-14 notu), bu da haritayi
    # bozuyor (starburst) ve nav2'ye koridorda hayali engel gosteriyor -> Spin
    # recovery -> tekrar hizli donus -> tekrar yanlis eslesme riski (kisir
    # dongu). Bu tek-ornekli jiroskop/SLAM uyusmazligi ESKIDEN sadece robot
    # HIZLI DONMUYORKEN kontrol ediliyordu (asagidaki FAST_TURN_DPS penceresi
    # ve recovery sirasinda tamamen atlaniyordu) - yani tam da bu hatanin en
    # sik olustugu anda (Spin recovery / hizli donus) izlenmiyordu. Bu esik,
    # gercek donus hizinin (max_rotational_vel=0.45 rad/s) tek bir lidar
    # taramasinda (~150-200ms) yol acabilecegi motion-smear farkindan (~5
    # derece) kat kat buyuk oldugu icin, donus sirasinda bile guvenle "gercek
    # bir ters-yon atlamasi" olarak sayilabilir - asagidaki FAST_TURN/grace
    # penceresini BEKLEMEDEN hemen tetiklenir.
    "MAP_IMU_YAW_GROSS_ERROR_DEG": 45.0,
    "MAP_IMU_YAW_DISTURBANCE_DELTA_DEG": 8.0,
    "MAP_IMU_YAW_DISTURBANCE_GRACE_SECONDS": 3.0,
    # 2026-09-13: lidar tek bir 360 taramayi ~150-200ms'de bitiriyor, hizli
    # yerinde donuslerde (nav2 frontier'a bakma, manuel pivot, recovery)
    # taramanin ici farkli gercek baslıklara denk gelir (motion smear) ve
    # slam_toolbox bunu telafi etmiyor (deskew yok) - SLAM/IMU uyusmazligi
    # bu durumda beklenen bir yan etki, harita bozulmasi degil. Jiroskop
    # kendisi bu esigin uzerindeyken hatayi biriktirme, sadece donus
    # yavaslayip/durduktan sonraki gercek uyusmazligi say.
    "MAP_IMU_YAW_FAST_TURN_DPS": 25.0,
    # Reset sonrasi exploration'i otomatik devam ettir (motor zaten durdu,
    # robot hareketsizken hata sifirlaniyor - insan mudahalesi olmadan devam
    # edebilmesi lazim). Kisa surede tekrar tekrar tetiklenirse (gercek/
    # kalici bir sorun ihtimali) otomatik devami durdurup manuel incelemeye birak.
    "MAP_JUMP_AUTO_RESUME_ENABLED": True,
    "MAP_JUMP_AUTO_RESUME_SETTLE_SECONDS": 2.0,
    "MAP_JUMP_AUTO_RESUME_MAX_RETRIES": 3,
    "MAP_JUMP_AUTO_RESUME_WINDOW_SECONDS": 300.0,
    # 2026-09-05: guc/I2C glitch (bkz. repo notlari) sirasinda lidar'in
    # USB-seri baglantisi donup /scan yayinini tamamen durdurabiliyor, ve
    # kendi kendine toparlanmiyor (glitch bitmesine ragmen dakikalarca
    # lidar_status="error" kaliyor). Bu watchdog bu durumu tespit edip
    # sadece lidar/SLAM surecini (map/reset ile ayni islem) yeniden baslatir
    # - tum uygulamayi yeniden baslatmaktan cok daha hafif bir mudahale.
    "LIDAR_FREEZE_WATCHDOG_ENABLED": True,
    "LIDAR_FREEZE_CHECK_INTERVAL_SECONDS": 3.0,
    "LIDAR_FREEZE_MAX_ERROR_SECONDS": 10.0,
    "LIDAR_FREEZE_RESET_COOLDOWN_SECONDS": 60.0,
    # 2026-09-05: robot bir temizlik robotu degil, genel gezinme yapacak -
    # explore_lite ilk frontier hedefini gondermeden once SLAM'in birkac
    # scan-match dongusu tamamlayip ilk yerel haritayi olusturmasina zaman
    # tanimak icin kisa bir bekleme (robot bu surede zaten hareketsiz,
    # nav2 costmap hazir olduktan hemen sonra).
    "EXPLORE_STARTUP_SETTLE_SECONDS": 4.0
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
    # 2026-09-18: sarj sirasinda guc tuketimini dusurmek icin mikrofon/hoparlor
    # fonksiyonlari (wake-word dinleme, TTS cikisi, webrtc mikrofon/hoparlor)
    # gecici olarak kapatildi - ileride tekrar True yapilacak.
    "ENABLED": False,
    "MICROPHONE_CARD": "ArrayUAC10",
    "MICROPHONE_DEVICE": "dsnoop:CARD=ArrayUAC10,DEV=0",
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
    "SYSTEM_PROMPT": "Kullanıcının Türkçe cümlesinden robot komut niyetini çıkar. Sadece JSON döndür. Desteklenen type değerleri: chat, local.time, system.shutdown, robot.move, audio.volume, device.status, web.search, music.play, music.stop, music.pause, music.resume, music.next, music.previous, music.genres. Saat kaç, bugünün tarihi nedir, günlerden ne gibi yerel sistem saati/tarihi sorularında local.time döndür ve query boş string olsun. Robotu, Raspberry Pi'yi veya sistemi tamamen kapatma isteklerinde system.shutdown döndür ve query boş string olsun. İleri git, geri git, sağa dön, sola dön, biraz geri git, yarım metre ileri git gibi robot hareket isteklerinde robot.move döndür ve query alanına kullanıcının hareket cümlesini aynen yaz. Sesi aç, sesi kıs, sesi yüzde elli yap, ses seviyesi kaçta/nedir gibi hoparlör ses seviyesini değiştiren veya soran isteklerde audio.volume döndür ve query alanına cümleyi aynen yaz. Batarya durumu, pil yüzdesi, şarj durumu, anlık akım/amper veya voltaj/gerilim sorularında device.status döndür ve query boş string olsun. Güncel hava durumu, maç sonucu, haber, son dakika, borsa, döviz veya internette aranması gereken güncel bilgi isteklerinde web.search döndür ve query alanına kısa arama metni yaz. Müzik/radyo çalma isteklerinde music.play döndür; query alanına yalnızca istenen müzik türünü yaz (örnek: caz, klasik, karadeniz, ankara), tür belirtilmemişse query boş string olsun. Hangi radyo kanalları/türleri var, kanalları listele, neler çalabilirsin gibi mevcut müzik türlerini sorma isteklerinde music.genres döndür ve query boş string olsun. Sonraki şarkı/kanal, kanalı değiştir, başka kanal/istasyon isteklerinde music.next, önceki şarkı/kanal isteklerinde music.previous, müzik duraklatma/bekletme komutlarında music.pause, müziğe devam etme/sürdürme/oynatma komutlarında music.resume, müzik durdurma/kapatma komutlarında music.stop döndür ve query boş string olsun. Emin değilsen chat döndür."
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