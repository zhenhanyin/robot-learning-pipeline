"""Values exchanged between robot adapters and workflows."""

from dataclasses import dataclass
from enum import Enum
from math import isfinite
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
    end_effector_pose: Optional[Tuple[float, ...]] = None
    end_effector_pose_format: Optional[str] = None

    def __post_init__(self):
        if not self.arm_id or self.timestamp_ns < 0 or not self.joint_positions:
            raise ValueError("arm_id, timestamp_ns, and joint_positions are required")
        if self.joint_velocities is not None and len(self.joint_velocities) != len(self.joint_positions):
            raise ValueError("joint_velocities must match joint_positions")
        if (self.end_effector_pose is None) != (self.end_effector_pose_format is None):
            raise ValueError("end_effector_pose and format must be provided together")
        if self.end_effector_pose is not None:
            expected_dimensions = {"xyz_rpy": 6, "xyz_quaternion_xyzw": 7}
            if self.end_effector_pose_format not in expected_dimensions:
                raise ValueError("unsupported end-effector pose format")
            if len(self.end_effector_pose) != expected_dimensions[self.end_effector_pose_format]:
                raise ValueError("end-effector pose dimensions do not match format")
            if not all(isfinite(value) for value in self.end_effector_pose):
                raise ValueError("end-effector pose must contain finite values")


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
    modality: str = "rgb"
    intrinsic_cv: Optional[Tuple[float, ...]] = None
    extrinsic_cv: Optional[Tuple[float, ...]] = None
    cam2world_gl: Optional[Tuple[float, ...]] = None

    def __post_init__(self):
        if not self.camera_id or not self.encoding or self.timestamp_ns < 0:
            raise ValueError("camera_id, encoding, and timestamp_ns are required")
        if self.width <= 0 or self.height <= 0 or not self.payload:
            raise ValueError("width, height, and payload must be non-empty")
        if self.modality not in ("rgb", "depth"):
            raise ValueError("camera modality must be rgb or depth")
        calibration_dimensions = {"intrinsic_cv": 9, "extrinsic_cv": 12, "cam2world_gl": 16}
        for name, dimensions in calibration_dimensions.items():
            values = getattr(self, name)
            if values is not None and (len(values) != dimensions or not all(isfinite(value) for value in values)):
                raise ValueError("{} must contain {} finite values".format(name, dimensions))
