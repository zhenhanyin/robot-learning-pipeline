"""Explicit write bridge for an externally installed Piper CAN SDK."""

from math import isfinite
from time import monotonic, sleep

from robot_learning.core.models import RobotCommand


class PiperCommandAdapter:
    def __init__(self, sdk: object, arm_id: str, joint_ticks_per_unit: float,
                 gripper_ticks_per_unit: float, gripper_effort: int = 1000,
                 speed_percent: int = 30):
        if not arm_id or not all(isfinite(value) and value > 0 for value in
                                 (joint_ticks_per_unit, gripper_ticks_per_unit)):
            raise ValueError("arm ID and positive unit scales are required")
        if type(gripper_effort) is not int or not 0 <= gripper_effort <= 5000:
            raise ValueError("invalid gripper effort")
        if type(speed_percent) is not int or not 1 <= speed_percent <= 100:
            raise ValueError("invalid speed percent")
        self.sdk = sdk
        self.arm_id = arm_id
        self.joint_ticks_per_unit = joint_ticks_per_unit
        self.gripper_ticks_per_unit = gripper_ticks_per_unit
        self.gripper_effort = gripper_effort
        self.speed_percent = speed_percent
        self.enabled = False

    def enable(self, timeout_seconds: float = 5.0, poll_seconds: float = 0.1) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds < 0 or not isfinite(poll_seconds) or poll_seconds <= 0:
            raise ValueError("invalid motor enable timeout or poll interval")
        deadline = monotonic() + timeout_seconds
        while True:
            self.sdk.EnableArm(7)
            status = self.sdk.GetArmLowSpdInfoMsgs()
            if all(getattr(status, "motor_{}".format(index)).foc_status.driver_enable_status
                   for index in range(1, 7)):
                break
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError("Piper motors did not report enabled status")
            sleep(min(poll_seconds, remaining))
        self.sdk.MotionCtrl_2(0x01, 0x01, self.speed_percent)
        self.enabled = True

    def send_command(self, command: RobotCommand) -> None:
        if not self.enabled:
            raise RuntimeError("Piper command mode is not enabled")
        if command.arm_id != self.arm_id or len(command.joint_targets) != 6:
            raise ValueError("Piper command requires the configured arm and six joints")
        if any(not isfinite(value) for value in command.joint_targets):
            raise ValueError("joint targets must be finite")
        joints = tuple(round(value * self.joint_ticks_per_unit) for value in command.joint_targets)
        if any(not -(2 ** 31) <= value < 2 ** 31 for value in joints):
            raise ValueError("Piper joint target exceeds CAN signed 32-bit range")
        gripper = None
        if command.gripper_target is not None:
            if not isfinite(command.gripper_target) or command.gripper_target < 0:
                raise ValueError("invalid Piper gripper target")
            gripper = round(command.gripper_target * self.gripper_ticks_per_unit)
            if gripper >= 2 ** 31:
                raise ValueError("Piper gripper target exceeds CAN range")
        self.sdk.JointCtrl(*joints)
        if gripper is not None:
            self.sdk.GripperCtrl(gripper, self.gripper_effort, 0x01, 0x00)

    def stop(self) -> None:
        self.enabled = False
        self.sdk.MotionCtrl_1(0x01, 0x00, 0x00)
