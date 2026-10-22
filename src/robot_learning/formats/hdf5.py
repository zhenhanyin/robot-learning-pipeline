"""Lossless HDF5 training export with explicit action provenance."""

import json
import re
from pathlib import Path

from robot_learning.formats.training import TrainingEpisode


def export_hdf5(episode: TrainingEpisode, destination: Path) -> int:
    try:
        import h5py
        import numpy as np
    except ImportError as error:
        raise ImportError("HDF5 export requires numpy and h5py") from error
    destination = Path(destination)
    if any(not re.fullmatch(r"[A-Za-z0-9_]+", camera_id) for camera_id in episode.camera_ids):
        raise ValueError("HDF5 camera IDs must contain only letters, digits and underscores")
    if destination.exists():
        raise FileExistsError(destination)
    if not destination.parent.is_dir():
        raise ValueError("HDF5 destination parent must exist")
    created = False
    try:
        with h5py.File(destination, "x") as output:
            created = True
            for name in ("schema_version", "robot_model", "clock_domain", "joint_units"):
                output.attrs[name] = episode.metadata[name]
            output.attrs["action_source"] = episode.action_source.value
            output.attrs["arm_id"] = episode.steps[0].state.arm_id
            output.attrs["export_format"] = "robot_learning_hdf5_v1"
            if "gripper_units" in episode.metadata:
                output.attrs["gripper_units"] = episode.metadata["gripper_units"]
            output.attrs["episode_metadata_json"] = json.dumps(episode.metadata, sort_keys=True, allow_nan=False)
            observations = output.create_group("observation")
            actions = output.create_group("action")
            observations.create_dataset("joint_positions", data=np.asarray(
                [step.state.joint_positions for step in episode.steps], dtype=np.float64,
            ))
            observations.create_dataset("timestamp_ns", data=np.asarray(
                [step.state.timestamp_ns for step in episode.steps], dtype=np.int64,
            ))
            actions.create_dataset("joint_targets", data=np.asarray(
                [step.action.joint_targets for step in episode.steps], dtype=np.float64,
            ))
            actions.create_dataset("timestamp_ns", data=np.asarray(
                [step.action.timestamp_ns for step in episode.steps], dtype=np.int64,
            ))
            if episode.steps[0].state.gripper_position is not None:
                observations.create_dataset("gripper_position", data=np.asarray(
                    [step.state.gripper_position for step in episode.steps], dtype=np.float64,
                ))
                actions.create_dataset("gripper_target", data=np.asarray(
                    [step.action.gripper_target for step in episode.steps], dtype=np.float64,
                ))
            pose_format = episode.steps[0].state.end_effector_pose_format
            if pose_format is not None:
                observations.create_dataset("end_effector_pose", data=np.asarray(
                    [step.state.end_effector_pose for step in episode.steps], dtype=np.float64,
                ))
                observations.attrs["end_effector_pose_format"] = pose_format
            image_group = observations.create_group("images")
            byte_type = h5py.vlen_dtype(np.dtype("uint8"))
            text_type = h5py.string_dtype(encoding="utf-8")
            for camera_id in episode.camera_ids:
                camera = image_group.create_group(camera_id)
                frames = [step.frames[camera_id] for step in episode.steps]
                payloads = camera.create_dataset("payload", (len(frames),), dtype=byte_type)
                for index, frame in enumerate(frames):
                    payloads[index] = np.frombuffer(frame.payload, dtype=np.uint8)
                camera.create_dataset("encoding", data=[frame.encoding for frame in frames], dtype=text_type)
                camera.create_dataset("modality", data=[frame.modality for frame in frames], dtype=text_type)
                for name in ("width", "height", "timestamp_ns"):
                    camera.create_dataset(name, data=np.asarray(
                        [getattr(frame, name) for frame in frames], dtype=np.int64,
                    ))
                for name in ("intrinsic_cv", "extrinsic_cv", "cam2world_gl"):
                    calibration = [getattr(frame, name) for frame in frames]
                    if any(value is not None for value in calibration):
                        if any(value is None for value in calibration):
                            raise ValueError("camera calibration availability changed: " + camera_id + "/" + name)
                        camera.create_dataset(name, data=np.asarray(calibration, dtype=np.float64))
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return len(episode.steps)
