"""Vendor-neutral input contract and fail-closed gate for VR/teleoperation."""

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Callable, Optional, Protocol, Tuple

from robot_learning.core.models import ArmState, RobotCommand
from robot_learning.core.ports import RobotAdapter
from robot_learning.workflows.motion import dispatch_commands, validate_commands
from robot_learning.workflows.policy_preview import SafetyEnvelope, SafetyStop


@dataclass(frozen=True)
class TeleoperationFrame:
    device_id: str
    arm_id: str
    timestamp_ns: int
    sequence: int
    position_m: Tuple[float, float, float]
    orientation_xyzw: Tuple[float, float, float, float]
    deadman_pressed: bool
    gripper_signal: Optional[float] = None
    reset_requested: bool = False

    def __post_init__(self):
        object.__setattr__(self, "position_m", tuple(self.position_m))
        object.__setattr__(self, "orientation_xyzw", tuple(self.orientation_xyzw))
        if not self.device_id or not self.arm_id or type(self.timestamp_ns) is not int or self.timestamp_ns < 0:
            raise ValueError("device, arm and non-negative timestamp are required")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")
        if len(self.position_m) != 3 or len(self.orientation_xyzw) != 4:
            raise ValueError("teleoperation pose requires xyz and quaternion_xyzw")
        pose = self.position_m + self.orientation_xyzw
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
               for value in pose):
            raise ValueError("teleoperation pose must contain finite values")
        quaternion_norm = sqrt(sum(value * value for value in self.orientation_xyzw))
        if abs(quaternion_norm - 1.0) > 0.01:
            raise ValueError("orientation quaternion must be normalized")
        if type(self.deadman_pressed) is not bool or type(self.reset_requested) is not bool:
            raise ValueError("teleoperation buttons must be boolean")
        if self.gripper_signal is not None and (
                isinstance(self.gripper_signal, bool) or not isinstance(self.gripper_signal, (int, float)) or
                not isfinite(self.gripper_signal) or not 0 <= self.gripper_signal <= 1):
            raise ValueError("gripper_signal must be normalized between 0 and 1")


class TeleoperationReader(Protocol):
    def read_latest(self) -> Optional[TeleoperationFrame]:
        ...


@dataclass(frozen=True)
class TeleoperationResult:
    status: str
    command: Optional[RobotCommand] = None
    published: bool = False


class TeleoperationBridge:
    def __init__(self, device_id: str, envelope: SafetyEnvelope,
                 map_frame: Callable[[TeleoperationFrame, ArmState], RobotCommand],
                 adapter: RobotAdapter, max_frame_age_ns: int = 100_000_000):
        if not device_id or not callable(map_frame):
            raise ValueError("device_id and an explicit pose-to-command mapper are required")
        if type(max_frame_age_ns) is not int or max_frame_age_ns <= 0:
            raise ValueError("max_frame_age_ns must be positive")
        self.device_id = device_id
        self.envelope = envelope
        self.map_frame = map_frame
        self.adapter = adapter
        self.max_frame_age_ns = max_frame_age_ns
        self.last_sequence = -1

    def process(self, frame: TeleoperationFrame, state: ArmState, now_ns: int,
                enabled: bool = False) -> TeleoperationResult:
        if not isinstance(frame, TeleoperationFrame) or frame.device_id != self.device_id:
            raise SafetyStop("unexpected teleoperation device")
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if frame.sequence <= self.last_sequence:
            raise SafetyStop("teleoperation sequence is stale or replayed")
        self.last_sequence = frame.sequence
        if frame.arm_id != self.envelope.arm_id or state.arm_id != self.envelope.arm_id:
            raise SafetyStop("teleoperation arm mismatch")
        if type(now_ns) is not int or not 0 <= now_ns - frame.timestamp_ns <= self.max_frame_age_ns:
            raise SafetyStop("teleoperation frame is stale or from the future")
        if frame.reset_requested:
            return TeleoperationResult("reset_requested")
        if not frame.deadman_pressed:
            return TeleoperationResult("deadman_released")
        command = self.map_frame(frame, state)
        if not isinstance(command, RobotCommand):
            raise SafetyStop("teleoperation mapper did not return a RobotCommand")
        validate_commands(state, (command,), self.envelope, now_ns)
        if enabled:
            dispatch_commands(self.adapter, state, (command,), self.envelope, now_ns, enabled=True)
        return TeleoperationResult("published" if enabled else "preview", command, enabled)
