"""Replay planning and a small fail-closed command dispatch boundary."""

from math import isfinite, sqrt
from typing import Sequence, Tuple

from robot_learning.core.models import ArmState, RobotCommand
from robot_learning.core.errors import StaleSampleError
from robot_learning.core.ports import RobotAdapter
from robot_learning.workflows.policy_preview import SafetyEnvelope, SafetyStop


def is_noop(previous: RobotCommand, current: RobotCommand, threshold: float) -> bool:
    if not isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be non-negative and finite")
    if previous.arm_id != current.arm_id or len(previous.joint_targets) != len(current.joint_targets):
        raise ValueError("commands must have matching arms and dimensions")
    distance = sqrt(sum((right - left) ** 2 for left, right in
                        zip(previous.joint_targets, current.joint_targets)))
    return distance < threshold and previous.gripper_target == current.gripper_target


class NoopStateReader:
    def __init__(self, reader: object, joint_threshold: float):
        if not isfinite(joint_threshold) or joint_threshold <= 0:
            raise ValueError("joint threshold must be positive and finite")
        self.reader = reader
        self.joint_threshold = joint_threshold
        self.previous = None

    def read_state(self) -> ArmState:
        state = self.reader.read_state()
        current = RobotCommand(state.arm_id, state.timestamp_ns,
                               state.joint_positions, state.gripper_position)
        if self.previous is not None and is_noop(self.previous, current, self.joint_threshold):
            raise StaleSampleError("static ARX state filtered")
        self.previous = current
        return state


def interpolate(start: ArmState, target: RobotCommand, steps: int) -> Tuple[RobotCommand, ...]:
    if type(steps) is not int or steps < 1 or start.arm_id != target.arm_id or len(start.joint_positions) != len(target.joint_targets):
        raise ValueError("matching state, target and positive step count are required")
    if (start.gripper_position is None) != (target.gripper_target is None):
        raise ValueError("gripper availability differs")
    result = []
    for index in range(1, steps + 1):
        fraction = index / steps
        joints = tuple(left + (right - left) * fraction for left, right in
                       zip(start.joint_positions, target.joint_targets))
        gripper = None if target.gripper_target is None else (
            start.gripper_position + (target.gripper_target - start.gripper_position) * fraction)
        result.append(RobotCommand(start.arm_id, target.timestamp_ns, joints, gripper))
    return tuple(result)


def dispatch_commands(adapter: RobotAdapter, state: ArmState, commands: Sequence[RobotCommand],
                      envelope: SafetyEnvelope, now_ns: int, enabled: bool = False) -> int:
    if not enabled:
        raise SafetyStop("command dispatch requires explicit enable")
    if not 0 <= now_ns - state.timestamp_ns <= envelope.max_observation_age_ns:
        raise SafetyStop("state is stale or from the future")
    if state.arm_id != envelope.arm_id or len(state.joint_positions) != len(envelope.joint_min):
        raise SafetyStop("state arm or dimension mismatch")
    if any(not isfinite(value) or not low <= value <= high for value, low, high in
           zip(state.joint_positions, envelope.joint_min, envelope.joint_max)):
        raise SafetyStop("state exceeds joint limits")
    if envelope.gripper_min is not None and (
        state.gripper_position is None or not isfinite(state.gripper_position) or
        not envelope.gripper_min <= state.gripper_position <= envelope.gripper_max
    ):
        raise SafetyStop("state exceeds gripper limits")
    previous_joints = state.joint_positions
    previous_gripper = state.gripper_position
    for command in commands:
        if command.arm_id != envelope.arm_id or len(command.joint_targets) != len(previous_joints):
            raise SafetyStop("command arm or dimension mismatch")
        if envelope.gripper_min is None and command.gripper_target is not None:
            raise SafetyStop("gripper command requires configured limits")
        if any(not isfinite(value) or not low <= value <= high or
               abs(value - previous) > step for value, previous, low, high, step in
               zip(command.joint_targets, previous_joints, envelope.joint_min,
                   envelope.joint_max, envelope.max_joint_step)):
            raise SafetyStop("command exceeds joint limit or maximum step")
        if envelope.gripper_min is not None and (
            command.gripper_target is None or previous_gripper is None or
            not isfinite(command.gripper_target) or
            not envelope.gripper_min <= command.gripper_target <= envelope.gripper_max or
            abs(command.gripper_target - previous_gripper) > envelope.max_gripper_step
        ):
            raise SafetyStop("command exceeds gripper limit or maximum step")
        previous_joints = command.joint_targets
        previous_gripper = command.gripper_target
    for command in commands:
        adapter.send_command(command)
    return len(commands)
