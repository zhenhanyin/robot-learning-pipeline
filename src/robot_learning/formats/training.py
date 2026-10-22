"""Strict, format-independent training steps assembled from an Episode."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Mapping, Tuple

from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.episode import EpisodeReader
from robot_learning.formats.validation import validate_episode


@dataclass(frozen=True)
class TrainingStep:
    state: ArmState
    action: ArmAction
    frames: Mapping[str, CameraFrame]
    frame_indices: Mapping[str, int]


@dataclass(frozen=True)
class TrainingEpisode:
    metadata: Mapping[str, object]
    steps: Tuple[TrainingStep, ...]
    camera_ids: Tuple[str, ...]
    action_source: ActionSource


def load_training_episode(directory: Path, action_policy: str = "recorded", tolerance_ns: int = 30_000_000) -> TrainingEpisode:
    if action_policy not in ("recorded", "next-state"):
        raise ValueError("action_policy must be recorded or next-state")
    if type(tolerance_ns) is not int or tolerance_ns < 0:
        raise ValueError("tolerance_ns must be non-negative")
    report = validate_episode(directory)
    if not report.valid:
        raise ValueError("invalid episode: {}".format("; ".join(report.errors)))
    reader = EpisodeReader(directory)
    groups = []
    frame_index = 0
    for record in reader.records():
        if isinstance(record, ArmState):
            groups.append({"state": record, "action": None, "frames": {}, "frame_indices": {}})
        elif isinstance(record, ArmAction):
            if not groups or groups[-1]["action"] is not None:
                raise ValueError("action must follow exactly one state")
            groups[-1]["action"] = record
        else:
            if not groups or record.camera_id in groups[-1]["frames"]:
                raise ValueError("frame must follow a state and have a unique camera ID")
            groups[-1]["frames"][record.camera_id] = record
            groups[-1]["frame_indices"][record.camera_id] = frame_index
            frame_index += 1
    if not groups:
        raise ValueError("episode has no states")
    camera_ids = tuple(sorted(groups[0]["frames"]))
    if not camera_ids:
        raise ValueError("episode has no camera frames")
    if action_policy == "next-state":
        if any(group["action"] is not None for group in groups):
            raise ValueError("next-state policy refuses recorded actions")
        if len(groups) < 2:
            raise ValueError("next-state policy requires at least two states")
        selected_groups = groups[:-1]
    else:
        if any(group["action"] is None for group in groups):
            raise ValueError("recorded action missing; select next-state explicitly for state-only episodes")
        selected_groups = groups
    steps = []
    sources = set()
    first_state = groups[0]["state"]
    for index, group in enumerate(groups):
        state = group["state"]
        if state.arm_id != first_state.arm_id or len(state.joint_positions) != len(first_state.joint_positions):
            raise ValueError("arm ID or state dimension changed")
        if (state.gripper_position is None) != (first_state.gripper_position is None):
            raise ValueError("gripper availability changed")
        if state.end_effector_pose_format != first_state.end_effector_pose_format:
            raise ValueError("end-effector pose availability or format changed")
        if not all(isfinite(value) for value in state.joint_positions):
            raise ValueError("state contains non-finite joints")
        if state.gripper_position is not None and not isfinite(state.gripper_position):
            raise ValueError("state contains non-finite gripper")
        if index >= len(selected_groups):
            continue
        if tuple(sorted(group["frames"])) != camera_ids:
            raise ValueError("camera set changed or a frame is missing")
        for frame in group["frames"].values():
            if abs(frame.timestamp_ns - state.timestamp_ns) > tolerance_ns:
                raise ValueError("camera frame exceeds synchronization tolerance")
        if action_policy == "next-state":
            next_state = groups[index + 1]["state"]
            action = ArmAction(state.arm_id, next_state.timestamp_ns, next_state.joint_positions,
                               ActionSource.NEXT_STATE, next_state.gripper_position)
        else:
            action = group["action"]
            if abs(action.timestamp_ns - state.timestamp_ns) > tolerance_ns:
                raise ValueError("action exceeds synchronization tolerance")
        if action.arm_id != state.arm_id or len(action.joint_targets) != len(state.joint_positions):
            raise ValueError("action arm ID or dimension differs from state")
        if (action.gripper_target is None) != (state.gripper_position is None):
            raise ValueError("action gripper availability differs from state")
        if not all(isfinite(value) for value in action.joint_targets):
            raise ValueError("action contains non-finite joints")
        if action.gripper_target is not None and not isfinite(action.gripper_target):
            raise ValueError("action contains non-finite gripper")
        sources.add(action.source)
        steps.append(TrainingStep(state, action, group["frames"], group["frame_indices"]))
    if len(sources) != 1:
        raise ValueError("mixed action sources are not supported")
    return TrainingEpisode(reader.metadata, tuple(steps), camera_ids, sources.pop())
