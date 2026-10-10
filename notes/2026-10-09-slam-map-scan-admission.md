# 2026-10-09: SLAM map scan admission diagnosis

## Session setup and confirmed observations

- Started the app through the canonical launcher: `scripts/run_app.py --launch-mode manual`.
- App startup left Nav2/EKF stopped while the LIDAR bridge, SLAM Toolbox, and map exporter were running. The `/scan` API remained live at about 10 Hz, but the saved map and pose initially still had Oct 8 timestamps.
- SLAM Toolbox logs repeatedly reported `Message Filter dropping message ... discarding message because the queue is full` while Nav2/EKF was stopped. Starting Nav2 without starting Explore brought up EKF/odometry; map and pose exports then became current, and the filter-queue warnings stopped. This confirms that a live scan endpoint does not mean SLAM can transform and accept that scan.
- Runtime `range_layer.enabled` was false in both local and global costmaps. Ultrasonic was reporting plausible readings during this session; it is not the source of the missing mapped front endpoints observed here.
- Raw scan snapshot: `frame=laser`, 360 bins, 326 valid returns. Stable returns included front about 1.60 m, left about 0.49 m, right about 1.50 m. With Nav2/EKF active, these were compared with the OccupancyGrid.

## Controlled mapping tests

- Active SLAM parameters: `minimum_travel_distance=0.10 m`, `minimum_travel_heading=0.15 rad` (~8.6 degrees), `minimum_time_interval=0.2 s`.
- Stationary bag (50 s): 505 `/scan` messages and 102 `/map` messages, but every map message had identical contents: 47 occupied cells, 1,188 free cells. The map topic was republishing the same grid rather than adding observations.
- A 10-degree left/right pulse pair with Nav2/EKF active showed gyro and LiDAR heading change agreeing closely (~+10 degrees and ~-9 degrees), but the occupied grid remained at 47 cells.
- A 11.5 cm forward/reverse test (Nav2/EKF active) reached about 11.8 cm in odometry, yet all map messages in its 31.7 s bag had identical contents (47 occupied cells). Its motion calibration output measured LiDAR travel of +0.115 m / -0.111 m.
- A 20 cm forward/reverse test (Nav2/EKF active) measured LiDAR travel +0.202 m / -0.204 m; odometry reached about 0.213 m. During that bag the map changed from 47 occupied cells to 220, then 317; grid dimensions changed from 367x124 to 368x135. The resulting occupied cells covered all four robot-relative sectors: front 38 (nearest ~1.52 m), left 11 (~0.50 m), back 17 (~1.30 m), right 34 (~1.37 m). The live scan still showed front ~1.59 m, left ~0.48 m, back ~1.23 m, right ~1.40 m.

## Current state and diagnosis

- Nav2 is running idle; Explore is stopped; motor API reports zero command and no faults. Keep Nav2/EKF running while SLAM mapping is expected, because stopping it removes the odometry TF needed by the scan message filter.
- The missing front map area was not a missing LIDAR measurement. In the initial idle map session, odometry TF was absent and scans were queued/dropped. Separately, the active SLAM scan-admission thresholds mean very short movements can leave the grid unchanged; the measured ~20 cm motion produced new map coverage where ~11.5 cm did not. This strongly supports scan insertion/motion gating as the cause of the sparse map and repeated stale-map decisions for small navigation corrections.
- Do not change the config based only on this result. Next, perform a controlled A/B test of scan admission with thresholds changed at runtime (no file edit), record map/odom/scan, and compare graph/map growth and CPU before choosing durable settings. Also decouple odometry availability from the full Nav2 lifecycle so mapping cannot claim to be live while scans are being dropped.
- These tests diagnose scan-to-map update behavior; they do not yet resolve the separate DWB exploration oscillation/recovery behavior.

## Follow-up: valid scan-admission A/B and code-level finding

- A first attempt to run `scripts/test_motion_calibration.py` after sourcing the ROS environment failed before motion: the ROS Python 3.12 `PYTHONPATH` was inherited by the app Python 3.13 venv, so NumPy's 3.12 extension could not load. Re-running the app script without sourcing ROS in its shell fixed the environment. No motion occurred in the failed attempt.
- With the app's normal 0.10 m configuration, a short 150-PWM forward/reverse pair measured by LiDAR/ICP about +9.7 cm and -8.9 cm. A smaller pair measured about +6.0 cm and -5.6 cm. In the live mapper, graph marker count stayed at 3 nodes across that smaller pair. The live PGM hash also remained unchanged.
- The earlier runtime A/B that used `ros2 param set` to change `minimum_travel_distance` to 0.03 m was not a valid A/B: the live SLAM mapper reads/sets Karto parameters during configure, and `shouldProcessScan()` caches its squared distance threshold in a function-static variable. Updating the ROS parameter value on the running node does not update that cached scan gate. Parameters were restored to 0.10 m and 0.15 rad; no project config was changed.
- A valid offline A/B replayed the same recorded scan/odometry bag (`logs/slam-admission-baseline2-20261009-212632`) in separate ROS domains, with two fresh SLAM Toolbox processes and startup YAMLs differing only in `minimum_travel_distance` (0.10 m vs 0.03 m). The TF relay reproduced `odom -> base_link` from recorded odometry and the known static `base_link -> laser` transform. Default startup produced 1 graph node and a 16 KB serialized scan-data file; 0.03 m startup produced 5 graph nodes and a 71 KB scan-data file. This supports the motion-admission threshold as a real cause of sparse scan insertion for these short corrections, even though the final occupancy-grid image did not change because the robot revisited already mapped surfaces.
- The installed package is `slam_toolbox` 2.8.5. In its `shouldProcessScan()` implementation, the configured 0.10 m threshold is squared, then the non-precise branch rejects scans while `distance_squared < 0.8 * threshold_squared`; that corresponds to about 8.9 cm for this config. With `check_min_dist_and_heading_precisely=false`, this scan prefilter uses distance only; the 0.15 rad heading value is not an “or” trigger in this code path. `minimum_time_interval=0.2` is an additional time gate, not a substitute for the movement gate.
- Current live state after the offline test: normal application/Nav2/SLAM remain untouched; motor command is zero, Explore stopped, and the live mapper still has the original 0.10 m / 0.15 rad ROS parameter values. The separate DWB exploration oscillation issue remains distinct and unresolved.
