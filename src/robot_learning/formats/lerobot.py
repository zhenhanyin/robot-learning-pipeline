"""Optional LeRobot v3 export through its public dataset API."""

import json
import re
from pathlib import Path
from typing import Optional, Type

from robot_learning.formats.images import rgb_array
from robot_learning.formats.training import TrainingEpisode


REPO_ID = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
CAMERA_ID = re.compile(r"[A-Za-z0-9_]+\Z")


def export_lerobot(
    episode: TrainingEpisode, destination: Path, repo_id: str, fps: int, task: str,
    dataset_type: Optional[Type[object]] = None,
) -> int:
    try:
        import numpy as np
    except ImportError as error:
        raise ImportError("LeRobot export requires numpy") from error
    if dataset_type is None:
        try:
            from lerobot.datasets import LeRobotDataset
        except ImportError as error:
            raise ImportError("LeRobot v3 export requires lerobot >= 0.4.0 and its optional dependencies") from error
        dataset_type = LeRobotDataset
    destination = Path(destination)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError("LeRobot destination must not exist and its parent must exist")
    if not isinstance(repo_id, str) or not REPO_ID.fullmatch(repo_id):
        raise ValueError("repo_id must be owner/name")
    if type(fps) is not int or fps <= 0:
        raise ValueError("fps must be a positive integer")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task is required")
    if any(not CAMERA_ID.fullmatch(camera_id) for camera_id in episode.camera_ids):
        raise ValueError("camera IDs must contain only letters, digits and underscores")
    rgb_camera_ids = tuple(camera_id for camera_id in episode.camera_ids
                           if episode.steps[0].frames[camera_id].modality == "rgb")
    if not rgb_camera_ids:
        raise ValueError("LeRobot export requires at least one RGB camera")
    period_ns = 1_000_000_000 / fps
    timestamps = [step.state.timestamp_ns for step in episode.steps]
    if any(abs((timestamp - timestamps[0]) - index * period_ns) > period_ns * 0.2
           for index, timestamp in enumerate(timestamps)):
        raise ValueError("state timestamps are not close to the requested constant FPS")
    first_step = episode.steps[0]
    dimensions = {camera_id: (first_step.frames[camera_id].width, first_step.frames[camera_id].height)
                  for camera_id in rgb_camera_ids}
    for step in episode.steps:
        for camera_id in rgb_camera_ids:
            frame = step.frames[camera_id]
            if (frame.width, frame.height) != dimensions[camera_id]:
                raise ValueError("camera dimensions changed")
            rgb_array(frame)
    state_size = len(first_step.state.joint_positions) + int(first_step.state.gripper_position is not None)
    features = {
        "observation.state": {"dtype": "float32", "shape": (state_size,), "names": ["state"]},
        "action": {"dtype": "float32", "shape": (state_size,), "names": ["action"]},
    }
    pose_format = first_step.state.end_effector_pose_format
    if pose_format is not None:
        pose_names = ("x", "y", "z", "roll", "pitch", "yaw") if pose_format == "xyz_rpy" else (
            "x", "y", "z", "qx", "qy", "qz", "qw",
        )
        features["observation.end_effector_pose"] = {
            "dtype": "float32", "shape": (len(pose_names),), "names": list(pose_names),
        }
    for camera_id, (width, height) in dimensions.items():
        features["observation.images." + camera_id] = {
            "dtype": "image", "shape": (height, width, 3), "names": ["height", "width", "channel"],
        }
    dataset = dataset_type.create(
        repo_id=repo_id, root=destination, fps=fps, robot_type=str(episode.metadata["robot_model"]),
        features=features, use_videos=False,
    )
    try:
        for step in episode.steps:
            state = list(step.state.joint_positions)
            action = list(step.action.joint_targets)
            if step.state.gripper_position is not None:
                state.append(step.state.gripper_position)
                action.append(step.action.gripper_target)
            frame = {
                "observation.state": np.asarray(state, dtype=np.float32),
                "action": np.asarray(action, dtype=np.float32),
                "task": task,
            }
            if step.state.end_effector_pose is not None:
                frame["observation.end_effector_pose"] = np.asarray(
                    step.state.end_effector_pose, dtype=np.float32,
                )
            for camera_id in rgb_camera_ids:
                frame["observation.images." + camera_id] = rgb_array(step.frames[camera_id])
            dataset.add_frame(frame)
        dataset.save_episode()
    finally:
        dataset.finalize()
    reader = dataset_type(repo_id=repo_id, root=destination)
    if len(reader) != len(episode.steps):
        raise ValueError("LeRobot readback length differs from source")
    if "action" not in reader[0] or "observation.state" not in reader[0]:
        raise ValueError("LeRobot readback lacks state or action")
    manifest = {
        "source_schema_version": episode.metadata["schema_version"],
        "robot_model": episode.metadata["robot_model"],
        "clock_domain": episode.metadata["clock_domain"],
        "joint_units": episode.metadata["joint_units"],
        "gripper_units": episode.metadata.get("gripper_units"),
        "action_source": episode.action_source.value,
        "source_state_timestamps_ns": timestamps,
        "source_action_timestamps_ns": [step.action.timestamp_ns for step in episode.steps],
        "fps": fps,
        "rgb_camera_ids": list(rgb_camera_ids),
        "depth_camera_ids": [camera_id for camera_id in episode.camera_ids
                             if episode.steps[0].frames[camera_id].modality == "depth"],
        "end_effector_pose_format": first_step.state.end_effector_pose_format,
        "camera_calibration": {
            camera_id: {
                name: [None if getattr(step.frames[camera_id], name) is None
                       else list(getattr(step.frames[camera_id], name)) for step in episode.steps]
                for name in ("intrinsic_cv", "extrinsic_cv", "cam2world_gl")
                if any(getattr(step.frames[camera_id], name) is not None for step in episode.steps)
            }
            for camera_id in episode.camera_ids
            if any(any(getattr(step.frames[camera_id], name) is not None
                       for name in ("intrinsic_cv", "extrinsic_cv", "cam2world_gl"))
                   for step in episode.steps)
        },
    }
    (destination / "robot_learning_export.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
    )
    return len(episode.steps)
