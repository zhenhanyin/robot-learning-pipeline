"""Values exchanged between robot adapters and workflows."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class ActionSource(str, Enum):
    LEADER_COMMAND = "leader_command"
    FOLLOWER_COMMAND = "follower_command"
    NEXT_STATE = "next_state"
    MODEL_PREDICTION = "model_prediction"


@dataclass(frozen=True)
class ArmState:
    arm_id: str
    timestamp_ns: int
    joint_positions: Tuple[float, ...]
    gripper_position: Optional[float] = None
    joint_velocities: Optional[Tuple[float, ...]] = None

    def __post_init__(self):
        if not self.arm_id or self.timestamp_ns < 0 or not self.joint_positions:
            raise ValueError("arm_id, timestamp_ns, and joint_positions are required")
        if self.joint_velocities is not None and len(self.joint_velocities) != len(self.joint_positions):
            raise ValueError("joint_velocities must match joint_positions")


@dataclass(frozen=True)
class ArmAction:
    arm_id: str
    timestamp_ns: int
    joint_targets: Tuple[float, ...]
    source: ActionSource
    gripper_target: Optional[float] = None

    def __post_init__(self):
        if not self.arm_id or self.timestamp_ns < 0 or not self.joint_targets:
            raise ValueError("arm_id, timestamp_ns, and joint_targets are required")
        if not isinstance(self.source, ActionSource):
            raise ValueError("source must be an ActionSource")


@dataclass(frozen=True)
class RobotCommand:
    arm_id: str
    timestamp_ns: int
    joint_targets: Tuple[float, ...]
    gripper_target: Optional[float] = None

    def __post_init__(self):
        if not self.arm_id or self.timestamp_ns < 0 or not self.joint_targets:
            raise ValueError("arm_id, timestamp_ns, and joint_targets are required")


@dataclass(frozen=True)
class CameraFrame:
    camera_id: str
    timestamp_ns: int
    encoding: str
    width: int
    height: int
    payload: bytes

    def __post_init__(self):
        if not self.camera_id or not self.encoding or self.timestamp_ns < 0:
            raise ValueError("camera_id, encoding, and timestamp_ns are required")
        if self.width <= 0 or self.height <= 0 or not self.payload:
            raise ValueError("width, height, and payload must be non-empty")
