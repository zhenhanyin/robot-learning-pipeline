"""Read-only bridge for a Piper SDK object supplied by the caller."""

from typing import Tuple

from robot_learning.adapters.piper.timebase import as_nanoseconds
from robot_learning.core.models import ActionSource, ArmAction, ArmState
from robot_learning.core.errors import StaleSampleError


def _joints(message: object, field: str) -> Tuple[float, ...]:
    joints = getattr(message, field)
    return tuple(float(getattr(joints, "joint_{}".format(index))) for index in range(1, 7))


class PiperReadOnlyAdapter:
    def __init__(self, sdk: object, arm_id: str = "left", max_gripper_skew_ns: int = 30_000_000) -> None:
        if not isinstance(arm_id, str) or not arm_id:
            raise ValueError("arm_id is required")
        if type(max_gripper_skew_ns) is not int or max_gripper_skew_ns < 0:
            raise ValueError("max_gripper_skew_ns must be non-negative")
        self.sdk = sdk
        self.arm_id = arm_id
        self.max_gripper_skew_ns = max_gripper_skew_ns

    def _gripper(self, message: object, field: str, joint_timestamp_ns: int) -> float:
        gripper_timestamp_ns = as_nanoseconds(getattr(message, "time_stamp"), 1)
        if abs(gripper_timestamp_ns - joint_timestamp_ns) > self.max_gripper_skew_ns:
            raise StaleSampleError("Piper gripper timestamp is outside tolerance")
        return float(getattr(getattr(message, field), "grippers_angle"))

    def read_state(self) -> ArmState:
        joint = self.sdk.GetArmJointMsgs()
        gripper = self.sdk.GetArmGripperMsgs()
        timestamp_ns = as_nanoseconds(joint.time_stamp, 1_000_000_000)
        return ArmState(
            self.arm_id,
            timestamp_ns,
            _joints(joint, "joint_state"),
            self._gripper(gripper, "gripper_state", timestamp_ns),
        )

    def read_action(self) -> ArmAction:
        joint = self.sdk.GetArmJointCtrl()
        gripper = self.sdk.GetArmGripperCtrl()
        timestamp_ns = as_nanoseconds(joint.time_stamp, 1_000_000_000)
        return ArmAction(
            self.arm_id,
            timestamp_ns,
            _joints(joint, "joint_ctrl"),
            ActionSource.LEADER_COMMAND,
            self._gripper(gripper, "gripper_ctrl", timestamp_ns),
        )
