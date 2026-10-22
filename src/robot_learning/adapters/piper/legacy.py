"""Read the older Piper recorder layout without importing its SDK."""

import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

from robot_learning.adapters.piper.timebase import as_nanoseconds
from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.episode import JsonlEpisodeWriter
from robot_learning.workflows.synchronization import synchronize_timestamps


JOINT_RECORD = struct.Struct(">ddiiiiii")
GRIPPER_RECORD = struct.Struct(">ddiii")
ENDPOSE_RECORD = struct.Struct(">ddiiiiii")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IMAGE_NAME = re.compile(r"[0-9]+_[0-9]+\.png\Z")


@dataclass(frozen=True)
class TimedValues:
    timestamp_ns: int
    values: Tuple[int, ...]


@dataclass(frozen=True)
class TimedImage:
    timestamp_ns: int
    width: int
    height: int
    path: Path


@dataclass(frozen=True)
class LegacyImportSummary:
    source_frames: int
    written_samples: int
    dropped_samples: int
    cameras: Tuple[str, ...]


def _regular_file(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("required regular file missing: {}".format(path))
    return path


def _read_stream(path: Path, layout: struct.Struct, timestamp_scale: int) -> List[TimedValues]:
    _regular_file(path)
    records = []
    with path.open("rb") as stream:
        while True:
            block = stream.read(layout.size)
            if not block:
                break
            if len(block) != layout.size:
                raise ValueError("truncated legacy stream: {}".format(path))
            timestamp, _, *values = layout.unpack(block)
            records.append(TimedValues(as_nanoseconds(timestamp, timestamp_scale), tuple(values)))
    if not records:
        raise ValueError("empty legacy stream: {}".format(path))
    return records


def _read_images(directory: Path) -> List[TimedImage]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("required image directory missing: {}".format(directory))
    images = []
    for path in directory.iterdir():
        if not IMAGE_NAME.fullmatch(path.name):
            if path.suffix.lower() == ".png":
                raise ValueError("invalid timestamped PNG filename: {}".format(path))
            continue
        _regular_file(path)
        timestamp = as_nanoseconds(path.stem.replace("_", "."), 1_000_000_000)
        with path.open("rb") as image_file:
            header = image_file.read(33)
        if len(header) < 33 or header[:8] != PNG_SIGNATURE or header[12:16] != b"IHDR":
            raise ValueError("invalid PNG header: {}".format(path))
        width, height = struct.unpack(">II", header[16:24])
        if not width or not height:
            raise ValueError("invalid PNG dimensions: {}".format(path))
        images.append(TimedImage(timestamp, width, height, path))
    images.sort(key=lambda image: image.timestamp_ns)
    if not images:
        raise ValueError("no timestamped PNG images: {}".format(directory))
    return images


def _timestamps(records: Sequence[TimedValues]) -> List[int]:
    return [record.timestamp_ns for record in records]


def import_legacy_run(source: Path, destination: Path, tolerance_ns: int = 30_000_000) -> LegacyImportSummary:
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_dir():
        raise ValueError("source must be a regular directory")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    if type(tolerance_ns) is not int or tolerance_ns < 0:
        raise ValueError("tolerance_ns must be non-negative")

    follower_joints = _read_stream(source / "follower_joint", JOINT_RECORD, 1_000_000_000)
    follower_grippers = _read_stream(source / "follower_gripper", GRIPPER_RECORD, 1)
    leader_joints = _read_stream(source / "leader_joint", JOINT_RECORD, 1_000_000_000)
    leader_grippers = _read_stream(source / "leader_gripper", GRIPPER_RECORD, 1)
    endpose_path = source / "follower_endpose"
    if endpose_path.is_symlink():
        raise ValueError("follower_endpose must not be a symlink")
    follower_endposes = (_read_stream(endpose_path, ENDPOSE_RECORD, 1_000_000_000)
                         if endpose_path.exists() else None)

    image_root = source / "img"
    if image_root.is_symlink() or not image_root.is_dir():
        raise ValueError("required image directory missing: {}".format(image_root))
    front = _read_images(image_root / "front_color")
    cameras = {"wrist_left": _read_images(image_root / "wrist_color")}
    front_depth = image_root / "front_depth"
    wrist_depth = image_root / "wrist_depth"
    if front_depth.is_symlink() or wrist_depth.is_symlink():
        raise ValueError("depth camera directories must not be symlinks")
    if front_depth.is_dir() and wrist_depth.is_dir():
        if any(front_depth.iterdir()) and any(wrist_depth.iterdir()):
            cameras["base_depth"] = _read_images(front_depth)
            cameras["wrist_left_depth"] = _read_images(wrist_depth)
        elif any(front_depth.iterdir()) or any(wrist_depth.iterdir()):
            raise ValueError("both depth cameras must have images")
    elif front_depth.exists() or wrist_depth.exists():
        raise ValueError("both depth camera directories are required")

    streams = {
        "follower_joint": _timestamps(follower_joints),
        "follower_gripper": _timestamps(follower_grippers),
        "leader_joint": _timestamps(leader_joints),
        "leader_gripper": _timestamps(leader_grippers),
    }
    if follower_endposes is not None:
        streams["follower_endpose"] = _timestamps(follower_endposes)
    streams.update((name, [image.timestamp_ns for image in images]) for name, images in cameras.items())
    matches = synchronize_timestamps([image.timestamp_ns for image in front], streams, tolerance_ns)
    if not matches:
        raise ValueError("no complete legacy samples within tolerance")

    extra_metadata = {"source_format": "legacy_piper_binary_png"}
    if follower_endposes is not None:
        extra_metadata.update({
            "end_effector_pose_units": "piper_raw_endpose_tick_unverified",
            "end_effector_frame": "unspecified",
        })
    if any(camera.endswith("_depth") for camera in cameras):
        extra_metadata["depth_units"] = "legacy_png_units_unverified"
    with JsonlEpisodeWriter(
        destination, "piper_legacy", "legacy_piper_epoch_assumed",
        "piper_raw_joint_tick", "piper_raw_gripper_tick", extra_metadata,
    ) as writer:
        for match in matches:
            indices = match.stream_indices
            follower_joint = follower_joints[indices["follower_joint"]]
            follower_gripper = follower_grippers[indices["follower_gripper"]]
            leader_joint = leader_joints[indices["leader_joint"]]
            leader_gripper = leader_grippers[indices["leader_gripper"]]
            pose_values = () if follower_endposes is None else tuple(
                float(value) for value in follower_endposes[indices["follower_endpose"]].values
            )
            writer.append_state(ArmState(
                "left", follower_joint.timestamp_ns,
                tuple(map(float, follower_joint.values)), float(follower_gripper.values[0]),
                end_effector_pose=pose_values or None,
                end_effector_pose_format="xyz_rpy" if pose_values else None,
            ))
            writer.append_action(ArmAction("left", leader_joint.timestamp_ns, tuple(map(float, leader_joint.values)), ActionSource.LEADER_COMMAND, float(leader_gripper.values[0])))
            selected_images = [("base", front[match.anchor_index])]
            selected_images.extend((name, cameras[name][indices[name]]) for name in sorted(cameras))
            for camera_id, image in selected_images:
                _regular_file(image.path)
                modality = "depth" if camera_id.endswith("_depth") else "rgb"
                writer.append_frame(CameraFrame(camera_id, image.timestamp_ns, "png", image.width,
                                                image.height, image.path.read_bytes(), modality))

    return LegacyImportSummary(len(front), len(matches), len(front) - len(matches), ("base", *sorted(cameras)))
