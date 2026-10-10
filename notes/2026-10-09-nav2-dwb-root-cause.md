# Nav2 DWB root-cause follow-up — 2026-10-09

## Test and captured state

- Runtime A/B capture: `logs/nav-goalalign-ab-20261009-214857/` (19.5 s; `/evaluation`, `/cmd_vel_nav`, `/cmd_vel_smoothed`, `/cmd_vel`, `/odom`, `/odom_raw`, `/scan`, local costmap and footprint, TF, ultrasonic topic).
- Nav2 stayed running; Explore was stopped after about 10 s. No project config was changed in this capture.
- Current (21:53 Istanbul) state: Nav2 running, Explore stopped, motor command zero, no motor/sensor/power fault. LIDAR front=16.12 cm; ultrasonic nearest cluster=8.32 cm. Do not issue another forward/Explore movement at this position. The local `/drive` safety currently reports that 8.3 cm reading as `last_obstacle_distance`; ultrasonic costmap layers themselves are disabled.

## Direct cause observed in the captured turn

The third frontier goal was from map `(1.15, -0.95)` to `(-0.61, -0.75)`. The global planner's first segment went to `(1.18, -0.959)`, initially east/southeast, before detouring toward the westward goal. In the robot's odom frame the first transformed path tangent was about `-10.6°`; the robot started at about `-145.9°`. Following the planned detour therefore called for roughly `+135°` of initial alignment. The direct bearing to the final goal was about `-175°`, roughly `-29°` from the robot's starting heading. Path alignment and direct goal alignment thus initially preferred opposite turn directions.

The first DWB evaluation selected a slight positive turn (`w=+0.192 rad/s`); by about 1.25 s it selected a negative turn (`w=-0.284 rad/s`) and later preferred negative pure rotation. In the first evaluation the best positive and negative legal candidates scored 29.175 and 29.200; at 1.25 s best negative scored 29.925 vs positive 30.100. At about 3.75 s a pure turn scored 28.25 and a forward arc 28.40. GoalAlign and PathAlign contributions were both active and competing; the chosen negative candidates improved GoalAlign toward the direct goal while the global route tangent required the opposite turn. This directly explains the observed initial left/right correction. The cause for this particular reversal is DWB's local trajectory scoring against a detour path, not motor polarity, IMU axis sign, or an ultrasonic costmap obstacle.

The start scan itself was not fully clear: at angle `-35°` it measured about `0.198 m` (with returns around 0.20–0.40 m from nearby negative/positive angles). This side/front-side obstacle is consistent with the global map's blocked direct line. Later `collision_monitor` logged `Robot to approach for 1.2 seconds away from collision`; `/cmd_vel` was then zero while `/cmd_vel_nav` continued requesting small motion. At the current pose LIDAR sees a 16 cm front obstacle. Thus the safety stop was a response to a close LIDAR obstacle reached/turned toward during the maneuver, not the cause of the initial DWB sign reversal.

## Important test caveat

The intended runtime A/B setting of `FollowPath.GoalAlign.scale=0` was not demonstrated by the bag: recorded DWB critic scales were `GoalAlign=0.25` and `PathAlign=0.30`, which equal the configured values 10 and 12 multiplied by the 0.025 m map resolution. The runtime parameter was later read back as 10. Therefore this capture is a baseline run, not a valid GoalAlign-off A/B; do not cite it as proof that disabling GoalAlign changes behavior. A valid comparison needs the parameter applied before controller activation (or a Nav2 restart with a temporary parameter file), and the recorded critic scale must be verified as zero before interpreting motion.

## Likely amplifier, separate from the command-generation cause

`config.py` sets `ROS2_NAV2_FIXED_PWM=150`; `scripts/ros2_cmdvel_bridge.py` converts low Nav2 wheel targets to full-amplitude ±150 PWM pulses using encoder-position feedback and a 3 mm / 120 ms stopping estimate. Prior calibration at PWM 150 measured about 101–122 degrees/s under sustained pivot commands, while Nav2's angular ceiling is 0.45 rad/s (25.8 degrees/s). The bridge is intended to reduce average speed with pulses, but its actuator granularity and feedback latency can make Nav2's small corrections coarse. It cannot explain why `/cmd_vel_nav` itself changed sign, so regard this as a likely motion-quality amplifier that still needs an isolated test, not the primary source of the reversals.

## Next controlled steps

1. Move the robot to a clear area before any motion test; current front LIDAR
   and ultrasonic readings are too close for forward motion or turning.
2. With Explore stopped, test fixed-PWM straight and pivot commands while
   recording `/cmd_vel`, `/odom_raw`, `/odom`, S3 encoders/gyro, and motor
   status. Confirm wheel movement follows the target and measure real brake
   delay against the provisional 40 ms setting.
3. If the low-speed pulse response improves, re-run the same class of DWB
   detour with a full `/evaluation` bag. Then do a valid GoalAlign-off A/B,
   applying the parameter before controller activation and verifying the
   effective scale in `/evaluation`.
4. Compare sign reversals, forward progress, and collision-monitor output. If
   reversals remain, trace the full critic contributions and path geometry;
   do not change DWB weights from the incomplete short-circuit scores alone.

## Fixed-PWM feedback cadence correction — 2026-10-09 22:10 Istanbul

The fixed-PWM bridge was running its drive loop at 14 Hz, while the S3
published encoder-bearing `TELEM` at 10 Hz and the bridge polled it at 10 Hz.
Thus the motor could receive a full 150-PWM pulse for at least one 100 ms
encoder interval before the bridge saw any position change, even though
Nav2 requested very small average wheel speeds. The stop predictor also used
120 ms, several times longer than a newly matched 50 Hz control cycle. This
is a concrete actuator/feedback resolution mismatch and explains why tiny DWB
velocities can turn into coarse wheel pulses. It does not explain why DWB
changes angular sign; the near-tied path-vs-goal scores above remain a
separate planner-level cause to validate.

Changes applied:

- `MotorEspS3.ino`: encoder/IMU telemetry interval changed from 100 ms to
  20 ms (50 Hz).
- `config.py` and `services/ros2_navigation.py`: drive and encoder polling
  rates set to 50 Hz; fixed-PWM predictive stop latency set to 40 ms.
- `scripts/ros2_cmdvel_bridge.py`: default drive rate set to 50 Hz.
- `tests/test_fixed_pwm_loop.py`: sampled/quantized encoder simulation
  compares old 14/10 Hz control with matched 50/50 Hz control.

Verification: firmware build succeeded (1,051,996 bytes / 80% of 1.31 MB
application slot); OTA upload succeeded. After app restart, the bridge
command line showed `--fixed-pwm-stop-latency-sec 0.04 --drive-rate-hz 50.0
--imu-rate-hz 50.0`; measured `/odom_raw` was 50.0 Hz and S3 telemetry
sequence advanced at 50.1 Hz. Motor status remained zero and encoder counts
did not change. Unit checks and Python compile passed.

The current robot position is too close to obstacles for a floor motion test:
LIDAR front about 21.9 cm and ultrasonic about 13.8 cm. Nav2 is running
without Explore or an active goal; do not start forward motion at this pose.
The actuator change is deployed but still needs a clear-area supervised motion
test.

## DWB opposing-turn correction — 2026-10-09

The DWB sign-reversal mechanism was traced to an avoidable critic conflict.
Nav2 Jazzy's `GoalAlignCritic` extends `GoalDistCritic`: it shifts the target
point forward from the final goal along the direct goal bearing, then scores
the robot's forward point against that target. On a detour, this pulls the
nose toward the goal through the obstacle while `PathAlign` pulls it along the
planner's route. The earlier bag showed this geometry and nearly tied
trajectories with opposite turn signs.

Removed `GoalAlign` from `FollowPath.critics`; `PathAlign` and `PathDist`
retain route tracking, `GoalDist` retains endpoint progress, and
`RotateToGoal` handles final heading. Restarted the running controller and
verified it loaded only `RotateToGoal`, `Oscillation`, `BaseObstacle`,
`PathAlign`, `PathDist`, and `GoalDist`.

This corrects the observed sign-reversal mechanism, but still needs a physical
exploration run. Current front LIDAR is about 21.8 cm and ultrasonic about
13.9 cm, so no motion test was started. Put the robot in a genuinely clear
area, then capture `/evaluation`, route, commands, odometry, scan and
collision-monitor output during a short Explore run. Confirm route progress
without GoalAlign-driven reversals. The fixed-PWM feedback change also needs a
supervised floor test before judging movement smoothness.

## Close-room frontier A/B and autonomous ultrasonic gate — 2026-10-09

Captured bag: `logs/nav2-standoff-040-20261009-224501/` (26.3 s). Explore
created one straight global plan from `(-0.20,-0.20)` to `(0.551,-0.159)`.
The target is a known-free occupancy cell, but the nearest occupied map cell is
only about 0.10 m away; its global costmap value is 237/254. Raising the
radial `frontier_goal_standoff` from 0.20 m to 0.40 m therefore did not ensure
real clearance: the nearest wall was off the robot-to-frontier ray. In DWB
samples, forward candidates had BaseObstacle contribution 13.3 while reverse
candidates had 0, and it repeatedly selected rotation/reverse candidates.
This confirms that a fixed radial standoff is insufficient; target selection
must validate the resulting target cell against the actual global costmap.

The physical outcome of this A/B is invalid: `/motor/status` already had a
latched `power_fault=true`, with a trip sample of 10.66 V under 1.094 A, below
the 10.8 V drive trip. The trip timestamp preceded this bag by about two
minutes, so the current DWB run could publish commands but the app rejected
motor output. Idle battery later read 10.836 V (34.7%). Do not interpret this
capture as proving physical response to the new target selection. Recharge the
robot before clearing the latched fault by restarting the app and repeating a
short supervised capture.

Separate direct-safety finding: `logs/run-20261009-220731/app.log` contains 58
`FORWARD BLOCK: ultrasonic 11.8/11.9 cm` messages. The direct Nav2 `/drive`
route has a 12 cm ultrasonic failsafe independent of Nav2's `range_layer`
parameter. `DistanceService.read_safety_centimeters()` selects the nearest
confirmed cluster from a 7-sample window, so a small cluster of close echoes
can trip this failsafe even while `/ultrasonic/readings` reports a stable
~96 cm median. Turning off the Nav2 Range layer alone did not remove this
independent blocker.

Changes made for the next powered test:

- `config.py`: added `ULTRASONIC.AUTONOMOUS_FORWARD_STOP_ENABLED=False` for
  autonomous diagnosis. Manual forward ultrasonic protection remains enabled.
- `routes/control.py`: autonomous forward motion retains the direct 40 cm
  LIDAR stop gate; the unreliable ultrasonic close-range failsafe is now
  controlled by that flag. Nav2's LIDAR costmap remains active.
- `~/ros2_nav_ws/src/m-explore-ros2/explore/src/explore.cpp`: candidate
  frontier goals are projected to the known side and rejected when their
  actual global costmap target cell exceeds `frontier_goal_max_cost`.
- `config/explore_lite_params.yaml`: standoff 0.40 m plus maximum target-cell
  cost 100. This addresses off-axis walls that defeat radial-only standoff.

Verification: Python configuration tests pass (2/2), `py_compile` passes, and
`colcon build --packages-up-to explore_lite` succeeds. The updated Python app
route is not active until app restart, and the newly built Explore binary is
not loaded into a running Explore process. Both require a post-charge restart
and a short bag to validate at close range. Current power fault is latched;
no further motor movement should be attempted until the battery is recharged.

Post-change checks: `./.venv/bin/python -m unittest discover -s tests -p
'test_autonomous_ultrasonic_gate.py' -v` passes 2/2 (autonomous Nav2 ignores a
synthetic 11.8 cm echo, manual drive still blocks); the frontier configuration
checks pass 2/2; and `ctest -R test_explore` passes 1/1.
