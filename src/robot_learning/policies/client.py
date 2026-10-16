"""Injectable ACT, H-RDT and OpenPI-shaped inference clients."""

from dataclasses import dataclass
from itertools import islice
from math import isfinite
from numbers import Real
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Sequence, Tuple

from robot_learning.core.models import ArmState, CameraFrame, RobotCommand


@dataclass(frozen=True)
class PolicySpec:
    model: str
    camera_map: Mapping[str, str]
    joint_count: int
    gripper_in_action: bool = False
    prompt: Optional[str] = None
    max_chunk_steps: int = 64

    def __post_init__(self):
        if self.model not in ("act", "hrdt", "pi0", "pi0.5"):
            raise ValueError("unsupported policy model")
        if type(self.joint_count) is not int or self.joint_count <= 0:
            raise ValueError("joint_count must be positive")
        if type(self.max_chunk_steps) is not int or self.max_chunk_steps <= 0:
            raise ValueError("max_chunk_steps must be positive")
        if not self.camera_map or any(not key or not value for key, value in self.camera_map.items()):
            raise ValueError("camera_map must name every model and source camera")
        if len(set(self.camera_map.values())) != len(self.camera_map):
            raise ValueError("source cameras must be unique")
        if self.model in ("pi0", "pi0.5") and not self.prompt:
            raise ValueError("OpenPI policies require a prompt")
        object.__setattr__(self, "camera_map", MappingProxyType(dict(self.camera_map)))


class ModelPolicyClient:
    def __init__(self, spec: PolicySpec, backend: object, encode_frame: Callable[[CameraFrame], object]):
        if not callable(encode_frame):
            raise ValueError("encode_frame must be provided explicitly")
        self.spec = spec
        self.backend = backend
        self.encode_frame = encode_frame

    def predict(self, state: ArmState, frames: Sequence[CameraFrame]) -> Tuple[RobotCommand, ...]:
        if len(state.joint_positions) != self.spec.joint_count:
            raise ValueError("state joint dimension differs from policy spec")
        if self.spec.gripper_in_action != (state.gripper_position is not None):
            raise ValueError("state gripper availability differs from policy spec")
        by_id = {frame.camera_id: frame for frame in frames}
        if len(by_id) != len(frames) or set(by_id) != set(self.spec.camera_map.values()):
            raise ValueError("camera set differs from policy spec")
        images = {model_name: self.encode_frame(by_id[source_name])
                  for model_name, source_name in self.spec.camera_map.items()}
        if any(image is None for image in images.values()):
            raise ValueError("camera encoder returned no image")
        if self.spec.model == "act":
            observation = {"qpos": state.joint_positions, "images": images}
            result = self.backend.get_chunk(observation)
        elif self.spec.model == "hrdt":
            observation = {"puppet_left": state.joint_positions, "images": images}
            result = self.backend.predict_action(observation)
        else:
            observation = {"state": state.joint_positions, "images": images, "prompt": self.spec.prompt}
            response = self.backend.infer(observation)
            if not isinstance(response, Mapping) or "actions" not in response:
                raise ValueError("OpenPI response must contain actions")
            result = response["actions"]
        if isinstance(result, (str, bytes)):
            raise ValueError("policy must return an action chunk")
        try:
            chunk = list(islice(result, self.spec.max_chunk_steps + 1))
        except (TypeError, ValueError) as error:
            raise ValueError("policy must return an action chunk") from error
        if not chunk:
            raise ValueError("policy returned an empty action chunk")
        if len(chunk) > self.spec.max_chunk_steps:
            raise ValueError("policy action chunk is too long")
        width = self.spec.joint_count + int(self.spec.gripper_in_action)
        commands = []
        for action in chunk:
            if isinstance(action, (str, bytes)):
                raise ValueError("action must be a numeric vector")
            try:
                values = tuple(action)
            except TypeError as error:
                raise ValueError("action must be a numeric vector") from error
            if len(values) != width or any(isinstance(value, bool) or not isinstance(value, Real)
                                           or not isfinite(value) for value in values):
                raise ValueError("action dimension or numeric value is invalid")
            commands.append(RobotCommand(state.arm_id, state.timestamp_ns,
                                         tuple(float(value) for value in values[:self.spec.joint_count]),
                                         float(values[-1]) if self.spec.gripper_in_action else None))
        return tuple(commands)
