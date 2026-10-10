# 2026-09-22 Navigation Session

## Confirmed observations

- The robot repeatedly drifted left during nominally straight `x=0, y=36`
  commands. Two approximately 14-16 cm encoder-derived runs showed the right
  wheel ahead of the left by about 7% and 13%; SLAM heading also changed left
  by about 5.3 and 4.2 degrees.
- A short S3 direct equal-PWM test bypassed the gyro straightening path and
  still produced more right-wheel ticks (`RR +143`, `RL +97`). The primary
  mismatch is therefore electromechanical (motor/gear/wheel/load/traction),
  not a Pi/Nav2 command-sign error. The old gyro-only correction is not
  sufficient to cancel the variable mismatch.
- Stationary six-second sampling kept both encoder values and the exported
  SLAM pose stable.
- A previous frontier defect was confirmed and fixed: only the first
  cost-ranked frontier was examined, so a rear-facing winner suppressed valid
  forward frontiers. Commit `050f4b7` contains that earlier fix.

## Implemented today, awaiting runtime verification

- Motor UART telemetry now carries a monotonically increasing sample sequence.
  The ROS cmd_vel bridge ignores cached duplicate samples rather than turning
  them into zero encoder speed.
- The bridge rejects implausible encoder discontinuities (such as an S3
  counter reset) and no longer substitutes commanded speed for missing wheel
  feedback; missing feedback becomes conservative zero odometry.
- Nav2 DWB `min_vel_x` is zero, allowing a collision-checked in-place/low
  linear-speed turn when the robot faces a nearby wall.
- Frontier selection keeps its forward preference but, once no forward target
  exists, can select a rear/side frontier for a controlled Nav2 reorientation.
  The corresponding `explore_lite` package was built successfully.
- `MotorEspS3.ino` now has a 50 Hz straight-drive assist: encoder differential
  PI is the fast inner loop, with gyro yaw correction as the outer loop. It is
  disabled for single-wheel `SET` commands and requested turns.

## Validation status

- S3 firmware was flashed after these changes.
- 2026-09-23 straight-drive verification: with about 2.1 m LiDAR clearance,
  a 1.6 s app command at `x=0, y=30` advanced about 13 cm (`front_cm` 210 to
  197). Encoder deltas were `RL +1721`, `RR +1876` (right about 9% ahead),
  and the gyro trace retained a left-yaw tendency. The new assist is active
  but its conservative PI gains have not yet eliminated the mismatch.
- 2026-09-23 isolated equal-PWM verification: a 0.5 s S3 `SET` test bypassed
  Pi/Nav2 and the straight-drive assist, yet yielded `RL +2758`, `RR +2912`
  (right about 5.6% ahead). This reconfirms the underlying variable is in the
  drivetrain/wheels/load/traction rather than command mapping. It does not by
  itself distinguish motor output, gearbox/wheel diameter, and surface load.
- 2026-09-23 control-path review found a separate compensation bug: every
  repeated `DRIVE` keep-alive could erase the most recent encoder correction,
  and small requested-speed changes reset the PI accumulator. The local
  firmware now retains both values for a continuing straight-drive intent;
  it still needs to be flashed before the next validation run.
- The first post-fix run showed that retaining the correction made the system
  overcorrect (`RL +2380`, `RR +2231`, left about 6.7% ahead) and the raw
  10 Hz gyro contribution oscillated. The pending firmware tune lowers the
  encoder PI gains and turns the gyro into a filtered, slower outer loop.
- The filtered/lower-gain run was stable but under-corrected (`RL +2254`,
  `RR +2370`, right about 5.1% ahead). Pending firmware diagnostics expose
  the current encoder deltas, filtered gyro, and applied PWM correction via
  `/status` so the next gain change is evidence-based.
- After the LiDAR cable was rerouted away from the left wheel, another short
  app straight run still showed the right wheel ahead (`RL +1409`, `RR +1554`,
  about 10.3%). Cable contact is therefore not the primary cause, although it
  may previously have added run-to-run variation. The next physical isolator
  is an unloaded, wheels-off-ground equal-PWM test: a mismatch there points to
  motor/driver/gear/encoder; a mismatch only on the floor points to wheel,
  rolling resistance, load distribution, or traction.
- Wheels-off-ground direct equal-PWM tests gave the opposite ordering from
  floor tests: forward `RL +7571`, `RR +6454` (left about 17% faster), and
  reverse magnitudes `RL 7793`, `RR 6365` (left about 22% faster). Thus the
  unloaded motor/driver/gear path is consistently faster on the left, whereas
  a grounded robot has the right encoder ahead. The reversal rules out a
  simple fixed command-mapping or "right motor is stronger" diagnosis; it
  requires a load/contact effect (left rolling resistance, right slip,
  wheel/frame interference under load, weight distribution, or caster/ground
  interaction). LiDAR cable contact is no longer the primary explanation.

## 2026-09-27 Motor replacement check

- The first post-replacement app straight command produced no forward LiDAR
  displacement. `RR` encoder remained at zero while `RL` changed only briefly.
- Direct S3 single-channel tests isolated the fault: `RL` advanced from -67 to
  -591 in 0.3 s, while `RR` remained zero. At comparable short commands the
  INA219 current stayed around 585 mA for `RR`, but rose from about 567 mA to
  691 mA for `RL`. The right motor channel is therefore not taking motor load
  (disconnected/loose lead, wrong TB6612 terminal, failed channel, or motor
  lead issue); this is not an encoder-only or navigation issue.
- Firmware logical mapping is intentionally cross-wired: physical left `RL`
  uses TB6612 B (`PIN_RR`, GPIO 12/13/14), and physical right `RR` uses TB6612
  A (`PIN_RL`, GPIO 11/10/9). Check the physical right motor leads and the
  TB6612 A output/connector before any further drive test.
- Python syntax checks, patch dry-run, and `explore_lite` build passed.
- Arduino CLI is not installed on the Pi, so firmware compilation was not run
  locally before flashing.
- The app must be restarted tomorrow for its Pi-side changes to take effect.
- Repository changes are currently uncommitted and unpushed.

## Tomorrow's safe test order

1. Start the app and confirm fresh, incrementing telemetry sequence plus
   healthy encoder, IMU, LiDAR, and ultrasonic readings while stationary.
2. With at least 1 m clear ahead, run one short straight test; record starting
   and ending encoder ticks, IMU yaw/gyro trace, LiDAR scan, and pose.
3. Repeat only if the first run is safe; tune the new encoder PI conservatively
   from the observed wheel-tick difference.
4. Run an angled-drive test only after straight behavior is acceptable.
5. Restart Nav2/exploration only after those manual motion checks pass.
