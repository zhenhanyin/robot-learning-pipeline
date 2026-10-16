"""Fail-closed offline evaluation of predicted action chunks."""

from dataclasses import dataclass
from math import isfinite
from time import monotonic_ns
from typing import Callable, Optional, Sequence, Tuple

from robot_learning.core.models import ArmState, CameraFrame, RobotCommand
from robot_learning.policies.client import ModelPolicyClient


class SafetyStop(RuntimeError):
    pass


@dataclass(frozen=True)
class SafetyEnvelope:
    arm_id: str
    joint_min: Tuple[float, ...]
    joint_max: Tuple[float, ...]
    max_joint_step: Tuple[float, ...]
    max_observation_age_ns: int
    max_frame_skew_ns: int
    max_prediction_ns: int
    gripper_min: Optional[float] = None
    gripper_max: Optional[float] = None
    max_gripper_step: Optional[float] = None

    def __post_init__(self):
        if not self.arm_id or not self.joint_min or len(self.joint_min) != len(self.joint_max) or len(self.joint_min) != len(self.max_joint_step):
            raise ValueError("complete joint limits are required")
        if any(not all(isfinite(value) for value in values) for values in
               (self.joint_min, self.joint_max, self.max_joint_step)):
            raise ValueError("joint limits must be finite")
        if any(low >= high or step <= 0 for low, high, step in
               zip(self.joint_min, self.joint_max, self.max_joint_step)):
            raise ValueError("joint limits and maximum steps are invalid")
        if any(type(value) is not int or value <= 0 for value in
               (self.max_observation_age_ns, self.max_frame_skew_ns, self.max_prediction_ns)):
            raise ValueError("time limits must be positive integer nanoseconds")
        gripper = (self.gripper_min, self.gripper_max, self.max_gripper_step)
        if any(value is not None for value in gripper):
            if any(value is None or not isfinite(value) for value in gripper):
                raise ValueError("all gripper limits must be finite")
            if self.gripper_min >= self.gripper_max or self.max_gripper_step <= 0:
                raise ValueError("gripper limits and maximum step are invalid")


class OfflinePolicyRunner:
    def __init__(self, policy: ModelPolicyClient, envelope: SafetyEnvelope,
                 clock_ns: Callable[[], int] = monotonic_ns):
        if policy.spec.joint_count != len(envelope.joint_min):
            raise ValueError("policy and joint limits have different dimensions")
        if policy.spec.gripper_in_action != (envelope.gripper_min is not None):
            raise ValueError("policy and gripper limits disagree")
        self.policy = policy
        self.envelope = envelope
        self.clock_ns = clock_ns
        self.stopped = False

    def emergency_stop(self) -> None:
        self.stopped = True

    def _fail(self, reason: str) -> None:
        self.stopped = True
        raise SafetyStop(reason)

    def preview(self, state: ArmState, frames: Sequence[CameraFrame], now_ns: int) -> Tuple[RobotCommand, ...]:
        if self.stopped:
            raise SafetyStop("runner is stopped")
        if type(now_ns) is not int or now_ns < 0:
            self._fail("invalid observation clock")
        if state.arm_id != self.envelope.arm_id or len(state.joint_positions) != len(self.envelope.joint_min):
            self._fail("state arm or dimension mismatch")
        if not 0 <= now_ns - state.timestamp_ns <= self.envelope.max_observation_age_ns:
            self._fail("state is stale or from the future")
        if any(not isfinite(value) or not low <= value <= high for value, low, high in
               zip(state.joint_positions, self.envelope.joint_min, self.envelope.joint_max)):
            self._fail("state exceeds joint limits")
        if self.envelope.gripper_min is not None and (state.gripper_position is None or
                not isfinite(state.gripper_position) or
                not self.envelope.gripper_min <= state.gripper_position <= self.envelope.gripper_max):
            self._fail("state exceeds gripper limits")
        if len(frames) != len(self.policy.spec.camera_map) or set(frame.camera_id for frame in frames) != set(self.policy.spec.camera_map.values()):
            self._fail("camera set differs from policy spec")
        if any(abs(frame.timestamp_ns - state.timestamp_ns) > self.envelope.max_frame_skew_ns or
               frame.timestamp_ns > now_ns for frame in frames):
            self._fail("camera frame is stale or from the future")
        try:
            started_ns = self.clock_ns()
            commands = self.policy.predict(state, frames)
            elapsed_ns = self.clock_ns() - started_ns
        except Exception as error:
            self.stopped = True
            raise SafetyStop("policy prediction failed") from error
        if self.stopped:
            raise SafetyStop("runner is stopped")
        if elapsed_ns < 0 or elapsed_ns > self.envelope.max_prediction_ns:
            self._fail("policy prediction exceeded deadline")
        previous_joints = state.joint_positions
        previous_gripper = state.gripper_position
        for command in commands:
            if command.arm_id != self.envelope.arm_id or len(command.joint_targets) != len(previous_joints):
                self._fail("predicted arm or dimension mismatch")
            if any(not low <= value <= high or abs(value - previous) > step for value, previous, low, high, step in
                   zip(command.joint_targets, previous_joints, self.envelope.joint_min,
                       self.envelope.joint_max, self.envelope.max_joint_step)):
                self._fail("predicted joint exceeds limit or maximum step")
            if self.envelope.gripper_min is not None and (command.gripper_target is None or
                    not self.envelope.gripper_min <= command.gripper_target <= self.envelope.gripper_max or
                    abs(command.gripper_target - previous_gripper) > self.envelope.max_gripper_step):
                self._fail("predicted gripper exceeds limit or maximum step")
            previous_joints = command.joint_targets
            previous_gripper = command.gripper_target
        return commands
