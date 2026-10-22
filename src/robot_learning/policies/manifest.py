"""Strict, portable manifests for external robot policy checkpoints."""

import json
import os
import re
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from robot_learning.core.models import ArmState, CameraFrame, RobotCommand
from robot_learning.policies.client import ModelPolicyClient, PolicySpec


@dataclass(frozen=True)
class AffineTransform:
    offset: Tuple[float, ...]
    scale: Tuple[float, ...]

    def __post_init__(self):
        object.__setattr__(self, "offset", tuple(self.offset))
        object.__setattr__(self, "scale", tuple(self.scale))
        if not self.offset or len(self.offset) != len(self.scale):
            raise ValueError("transform offset and scale dimensions must match")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
               for value in self.offset + self.scale):
            raise ValueError("transform values must be finite")
        if any(value == 0 for value in self.scale):
            raise ValueError("transform scales must be non-zero")

    def apply(self, values: Tuple[float, ...]) -> Tuple[float, ...]:
        if len(values) != len(self.offset):
            raise ValueError("transform feature dimension mismatch")
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
               for value in values):
            raise ValueError("transform input must contain finite numbers")
        return tuple((value - offset) / scale for value, offset, scale in
                     zip(values, self.offset, self.scale))

    def invert(self, values: Tuple[float, ...]) -> Tuple[float, ...]:
        if len(values) != len(self.offset):
            raise ValueError("transform feature dimension mismatch")
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
               for value in values):
            raise ValueError("transform input must contain finite numbers")
        return tuple(value * scale + offset for value, offset, scale in
                     zip(values, self.offset, self.scale))


@dataclass(frozen=True)
class PolicyManifest:
    model: str
    backend: str
    joint_names: Tuple[str, ...]
    joint_units: str
    action_units: str
    camera_map: Mapping[str, str]
    gripper_in_action: bool
    image_format: str = "frame"
    prompt: Optional[str] = None
    checkpoint_env: Optional[str] = None
    backend_options: Mapping[str, object] = None
    state_transform: Optional[AffineTransform] = None
    action_transform: Optional[AffineTransform] = None
    max_chunk_steps: int = 64
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported policy manifest schema_version")
        if self.model not in ("act", "hrdt", "pi0", "pi0.5"):
            raise ValueError("unsupported policy model")
        if isinstance(self.joint_names, str) or not self.joint_names or any(
                not isinstance(name, str) or not name for name in self.joint_names):
            raise ValueError("joint_names must contain non-empty names")
        if len(set(self.joint_names)) != len(self.joint_names):
            raise ValueError("joint_names must be unique")
        if (not isinstance(self.joint_units, str) or not self.joint_units or
                not isinstance(self.action_units, str) or not self.action_units):
            raise ValueError("joint_units and action_units must be explicit")
        if not isinstance(self.backend, str) or self.backend.count(":") != 1:
            raise ValueError("backend must use module:factory syntax")
        if self.image_format not in ("frame", "bytes", "rgb-array"):
            raise ValueError("unsupported image_format")
        if type(self.gripper_in_action) is not bool:
            raise ValueError("gripper_in_action must be boolean")
        if self.model in ("pi0", "pi0.5") and not self.prompt:
            raise ValueError("OpenPI policies require a prompt")
        if self.prompt is not None and not isinstance(self.prompt, str):
            raise ValueError("prompt must be text")
        if self.checkpoint_env is not None and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", self.checkpoint_env):
            raise ValueError("checkpoint_env must be an environment variable name")
        if not isinstance(self.camera_map, Mapping) or any(
                not isinstance(key, str) or not key or not isinstance(value, str) or not value
                for key, value in self.camera_map.items()):
            raise ValueError("camera_map must map non-empty model camera names to source IDs")
        if len(set(self.camera_map.values())) != len(self.camera_map):
            raise ValueError("source cameras must be unique")
        if self.backend_options is not None and not isinstance(self.backend_options, Mapping):
            raise ValueError("backend_options must be a mapping")
        options = dict(self.backend_options or {})
        if any(not isinstance(key, str) for key in options):
            raise ValueError("backend option names must be strings")
        if any(not key.lower().endswith("_env") and
               re.search(r"(api[_-]?key|access[_-]?token|client[_-]?secret|password)", key, re.I)
               for key in options):
            raise ValueError("credentials must be provided through environment variables")
        for key, value in options.items():
            if key.lower().endswith("_env") and (not isinstance(value, str) or
                    not re.fullmatch(r"[A-Z_][A-Z0-9_]*", value)):
                raise ValueError("credential environment references must be variable names")
        if self.state_transform is not None and (not isinstance(self.state_transform, AffineTransform) or
                len(self.state_transform.offset) != len(self.joint_names) + int(self.gripper_in_action)):
            raise ValueError("state transform dimension differs from observation features")
        if self.action_transform is not None and (not isinstance(self.action_transform, AffineTransform) or
                len(self.action_transform.offset) != len(self.joint_names) + int(self.gripper_in_action)):
            raise ValueError("action transform dimension differs from action features")
        if type(self.max_chunk_steps) is not int or self.max_chunk_steps <= 0:
            raise ValueError("max_chunk_steps must be positive")
        if not self.camera_map:
            raise ValueError("camera_map is required")
        object.__setattr__(self, "camera_map", MappingProxyType(dict(self.camera_map)))
        object.__setattr__(self, "backend_options", MappingProxyType(options))

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "PolicyManifest":
        allowed = {"schema_version", "model", "backend", "joint_names", "joint_units",
                   "action_units", "camera_map", "gripper_in_action", "image_format", "prompt",
                   "checkpoint_env", "backend_options", "state_transform", "action_transform",
                   "max_chunk_steps"}
        if not isinstance(value, Mapping) or set(value) - allowed:
            raise ValueError("policy manifest contains unsupported fields")
        required = {"model", "backend", "joint_names", "joint_units", "action_units",
                    "camera_map", "gripper_in_action"}
        if required - set(value):
            raise ValueError("policy manifest is missing required fields")
        if not isinstance(value["joint_names"], (list, tuple)) or isinstance(value["joint_names"], str):
            raise ValueError("joint_names must be a list")
        if not isinstance(value["camera_map"], Mapping):
            raise ValueError("camera_map must be an object")
        return cls(
            model=value["model"], backend=value["backend"],
            joint_names=tuple(value["joint_names"]), joint_units=value["joint_units"],
            action_units=value["action_units"], camera_map=value["camera_map"],
            gripper_in_action=value["gripper_in_action"],
            image_format=value.get("image_format", "frame"), prompt=value.get("prompt"),
            checkpoint_env=value.get("checkpoint_env"), backend_options=value.get("backend_options", {}),
            state_transform=_parse_transform(value.get("state_transform")),
            action_transform=_parse_transform(value.get("action_transform")),
            max_chunk_steps=value.get("max_chunk_steps", 64),
            schema_version=value.get("schema_version", 1),
        )

    @classmethod
    def load(cls, path: Path) -> "PolicyManifest":
        path = Path(path)
        if path.stat().st_size > 1_048_576:
            raise ValueError("policy manifest exceeds the size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_mapping(value)

    def build(self) -> "ConfiguredPolicyClient":
        from robot_learning.policies.factory import load_policy

        options = dict(self.backend_options)
        if self.checkpoint_env:
            checkpoint = os.environ.get(self.checkpoint_env)
            if not checkpoint:
                raise ValueError("checkpoint environment variable is not set")
            checkpoint = str(Path(checkpoint).expanduser().resolve())
            if not Path(checkpoint).exists():
                raise ValueError("checkpoint path from environment does not exist")
            if "checkpoint_path" in options:
                raise ValueError("checkpoint_path must come from checkpoint_env")
            options["checkpoint_path"] = checkpoint
        spec = PolicySpec(self.model, self.camera_map, len(self.joint_names),
                          self.gripper_in_action, self.prompt, self.max_chunk_steps)
        client = load_policy(spec, self.backend, options, self.image_format)
        return ConfiguredPolicyClient(client, self.state_transform, self.action_transform)

    def validate_training_plan(self, plan: object) -> None:
        if getattr(plan, "model", None) != self.model:
            raise ValueError("policy and training plan models differ")
        if getattr(plan, "joint_units", None) != self.joint_units:
            raise ValueError("policy and training plan joint units differ")
        if getattr(plan, "action_units", None) != self.action_units:
            raise ValueError("policy and training plan action units differ")


class ConfiguredPolicyClient:
    def __init__(self, client: ModelPolicyClient, state_transform: Optional[AffineTransform],
                 action_transform: Optional[AffineTransform]):
        self.client = client
        self.state_transform = state_transform
        self.action_transform = action_transform
        self.spec = client.spec

    def predict(self, state: ArmState, frames: Tuple[CameraFrame, ...]) -> Tuple[RobotCommand, ...]:
        from dataclasses import replace

        observation_state = state
        if self.state_transform is not None:
            features = state.joint_positions
            if self.spec.gripper_in_action:
                features += (state.gripper_position,)
            normalized = self.state_transform.apply(features)
            joints = normalized[:self.spec.joint_count]
            gripper = normalized[-1] if self.spec.gripper_in_action else state.gripper_position
            observation_state = replace(state, joint_positions=joints, gripper_position=gripper)
        commands = self.client.predict(observation_state, frames)
        if self.action_transform is None:
            return commands
        result = []
        for command in commands:
            features = command.joint_targets
            if self.spec.gripper_in_action:
                features += (command.gripper_target,)
            actual = self.action_transform.invert(features)
            result.append(RobotCommand(command.arm_id, command.timestamp_ns,
                                       actual[:self.spec.joint_count],
                                       actual[-1] if self.spec.gripper_in_action else command.gripper_target))
        return tuple(result)


def _parse_transform(value: object) -> Optional[AffineTransform]:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"offset", "scale"}:
        raise ValueError("affine transform requires offset and scale")
    return AffineTransform(tuple(value["offset"]), tuple(value["scale"]))
