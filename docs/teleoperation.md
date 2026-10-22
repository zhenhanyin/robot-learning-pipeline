# VR and teleoperation adapter

`robot_learning.adapters.teleop` defines the vendor-neutral input boundary. A device integration converts its own SDK/controller data into `TeleoperationFrame`: device/session ID, arm ID, monotonic timestamp and sequence, position in metres, normalized XYZW quaternion, deadman state, optional normalized gripper signal and a reset-request event.

`TeleoperationBridge` rejects stale/replayed samples, device/arm mismatches, invalid quaternion or non-finite values. A required injected `map_frame(frame, current_state)` performs the robot-specific coordinate conversion/IK and returns a `RobotCommand`; the bridge checks it against `SafetyEnvelope`. Without `enabled=True`, the result is preview-only. Publishing requires explicit enable and an injected `RobotAdapter`. Releasing deadman suppresses new commands; it does not guarantee the vendor controller will hold, brake or stop safely.

The old ARX VR code relies on vendor ROS/ROS2 workspaces, prebuilt `.so` libraries, a Quest APK and robot-specific launch/configuration. None is copied. The repository does not provide an IK solver, controller pairing, physical reset-to-home behavior, firmware lock/unlock, or a verified VR-to-robot calibration. `reset_requested` is only a signal to the integrator, never an automatic movement. Hardware safety, network latency, frame calibration, deadman release and stop behavior must be tested against vendor documentation before use.

Offline contract tests cover valid mapping, deadman release, replay/stale rejection, explicit publish gating, arm mismatch and reset behavior. They do not substitute for VR equipment or robot validation.
