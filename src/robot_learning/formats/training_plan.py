"""Portable, framework-neutral training plans for external model runners."""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional


@dataclass(frozen=True)
class TrainingPlan:
    model: str
    backend: str
    dataset_path: str
    dataset_format: str
    output_path: str
    task: str
    hyperparameters: Mapping[str, object]
    action_source: Optional[str] = None
    joint_units: Optional[str] = None
    action_units: Optional[str] = None
    schema_version: int = 1

    def __post_init__(self):
        if self.schema_version != 1:
            raise ValueError("unsupported training plan schema_version")
        if self.model not in ("act", "hrdt", "pi0", "pi0.5", "llama_factory"):
            raise ValueError("unsupported model")
        if not isinstance(self.backend, str) or self.backend.count(":") != 1:
            raise ValueError("backend must use module:factory syntax")
        if any(not isinstance(value, str) or not value for value in
               (self.dataset_path, self.output_path, self.task)):
            raise ValueError("dataset_path, output_path and task are required")
        if self.dataset_format not in ("hdf5", "lerobot", "vlm-sharegpt"):
            raise ValueError("unsupported dataset_format")
        if self.model == "llama_factory" and self.dataset_format != "vlm-sharegpt":
            raise ValueError("LLaMA-Factory plans require vlm-sharegpt data")
        if self.model != "llama_factory" and self.dataset_format == "vlm-sharegpt":
            raise ValueError("robot policies require hdf5 or lerobot data")
        if self.dataset_format in ("hdf5", "lerobot"):
            if (not self.action_source or not isinstance(self.joint_units, str) or not self.joint_units or
                    not isinstance(self.action_units, str) or not self.action_units):
                raise ValueError("robot training plans require action source and explicit units")
            if self.action_source not in ("leader_command", "follower_command", "next_state", "model_prediction"):
                raise ValueError("unsupported action_source")
        options = dict(self.hyperparameters)
        _validate_json_value(options)
        object.__setattr__(self, "hyperparameters", MappingProxyType(options))

    @classmethod
    def load(cls, path: Path) -> "TrainingPlan":
        path = Path(path)
        if path.stat().st_size > 1_048_576:
            raise ValueError("training plan exceeds the size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
        allowed = {"schema_version", "model", "backend", "dataset_path", "dataset_format",
                   "output_path", "task", "hyperparameters", "action_source", "joint_units",
                   "action_units"}
        required = {"model", "backend", "dataset_path", "dataset_format", "output_path",
                    "task", "hyperparameters"}
        if not isinstance(value, Mapping) or set(value) - allowed or required - set(value):
            raise ValueError("training plan fields are invalid")
        return cls(**value)

    def validate_paths(self, base_directory: Path = Path(".")) -> None:
        base = Path(base_directory).resolve()
        dataset = (base / self.dataset_path).resolve()
        output = (base / self.output_path).resolve()
        if not dataset.exists():
            raise ValueError("training dataset path does not exist")
        if dataset == output or dataset in output.parents or output in dataset.parents:
            raise ValueError("training output must not overlap the source dataset")
        if not output.parent.exists():
            raise ValueError("training output parent directory does not exist")


def _validate_json_value(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("hyperparameters must contain finite numbers")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("hyperparameter names must be strings")
            if not key.lower().endswith("_env") and any(
                    token in key.lower() for token in ("password", "secret", "api_key", "token")):
                raise ValueError("credentials must not be stored in training plans")
            if key.lower().endswith("_env") and (not isinstance(item, str) or
                    not re.fullmatch(r"[A-Z_][A-Z0-9_]*", item)):
                raise ValueError("credential environment references must be variable names")
            _validate_json_value(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_value(item)
        return
    raise ValueError("hyperparameters must be JSON-compatible")
