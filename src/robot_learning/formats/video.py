"""Optional MP4-to-HDF5 image preprocessing for legacy recordings."""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Sequence, Tuple


CAMERA_ID = re.compile(r"[A-Za-z0-9_]+\Z")


def resample_indices(source_count: int, target_count: int) -> Tuple[int, ...]:
    if type(source_count) is not int or type(target_count) is not int or source_count <= 0 or target_count <= 0:
        raise ValueError("video and target frame counts must be positive integers")
    if target_count == 1:
        return (0,)
    return tuple(index * (source_count - 1) // (target_count - 1) for index in range(target_count))


def write_encoded_video_frames(source_hdf5: Path, destination_hdf5: Path, camera_id: str,
                               frames: Sequence[bytes], jpeg_quality: int = 95) -> int:
    try:
        import h5py
        import numpy as np
    except ImportError as error:
        raise ImportError("video preprocessing requires numpy and h5py") from error
    source_hdf5 = Path(source_hdf5)
    destination_hdf5 = Path(destination_hdf5)
    if source_hdf5.is_symlink() or not source_hdf5.is_file():
        raise ValueError("source must be a regular HDF5 file")
    if destination_hdf5.exists() or destination_hdf5.is_symlink() or not destination_hdf5.parent.is_dir():
        raise ValueError("destination must not exist and its parent must exist")
    if source_hdf5.resolve() == destination_hdf5.resolve():
        raise ValueError("source and destination must differ")
    if not isinstance(camera_id, str) or not CAMERA_ID.fullmatch(camera_id):
        raise ValueError("camera ID must contain only letters, digits and underscores")
    if type(jpeg_quality) is not int or not 1 <= jpeg_quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100")
    frames = tuple(bytes(frame) for frame in frames)
    if not frames or any(not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9") for frame in frames):
        raise ValueError("encoded frames must be non-empty JPEG images")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".video-", suffix=".hdf5",
                                                   dir=str(destination_hdf5.parent))
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with h5py.File(source_hdf5, "r") as recording:
            if "joint_action/left_arm" in recording:
                target_count = len(recording["joint_action/left_arm"])
            elif "action/joint_targets" in recording:
                target_count = len(recording["action/joint_targets"])
            else:
                raise ValueError("source HDF5 has no supported action sequence")
        if target_count != len(frames):
            raise ValueError("encoded video frame count must match the HDF5 action sequence")
        shutil.copy2(source_hdf5, temporary)
        with h5py.File(temporary, "r+") as recording:
            camera_group = recording.require_group("observation").require_group(camera_id)
            if "rgb" in camera_group:
                raise ValueError("camera RGB dataset already exists")
            byte_type = h5py.vlen_dtype(np.dtype("uint8"))
            dataset = camera_group.create_dataset("rgb", (len(frames),), dtype=byte_type)
            for index, frame in enumerate(frames):
                dataset[index] = np.frombuffer(frame, dtype=np.uint8)
            camera_group.attrs["rgb_encoding"] = "jpeg"
            recording.attrs["robot_learning_video_preprocessing"] = json.dumps({
                "camera_id": camera_id,
                "jpeg_quality": jpeg_quality,
                "frame_selection": "uniform_endpoint_inclusive",
                "source_timestamps_preserved": False,
            }, sort_keys=True)
        os.replace(temporary, destination_hdf5)
        return len(frames)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def preprocess_video(video_path: Path, source_hdf5: Path, destination_hdf5: Path,
                     camera_id: str, jpeg_quality: int = 95) -> int:
    if not isinstance(camera_id, str) or not CAMERA_ID.fullmatch(camera_id):
        raise ValueError("camera ID must contain only letters, digits and underscores")
    if type(jpeg_quality) is not int or not 1 <= jpeg_quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100")
    try:
        import cv2
    except ImportError as error:
        raise ImportError("MP4 decoding requires the optional opencv-python-headless dependency") from error
    video_path = Path(video_path)
    if video_path.is_symlink() or not video_path.is_file():
        raise ValueError("video must be a regular file")
    source_hdf5 = Path(source_hdf5)
    if source_hdf5.is_symlink() or not source_hdf5.is_file():
        raise ValueError("source must be a regular HDF5 file")
    try:
        import h5py
    except ImportError as error:
        raise ImportError("video preprocessing requires h5py") from error
    with h5py.File(source_hdf5, "r") as recording:
        if "joint_action/left_arm" in recording:
            target_count = len(recording["joint_action/left_arm"])
        elif "action/joint_targets" in recording:
            target_count = len(recording["action/joint_targets"])
        else:
            raise ValueError("source HDF5 has no supported action sequence")
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise ValueError("video could not be opened")
    try:
        source_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        indices = resample_indices(source_count, target_count)
        frames = []
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            success, image = capture.read()
            if not success or image is None:
                raise ValueError("video frame decode failed at index {}".format(index))
            success, encoded = cv2.imencode(
                ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
            )
            if not success:
                raise ValueError("JPEG encoding failed at index {}".format(index))
            frames.append(encoded.tobytes())
    finally:
        capture.release()
    return write_encoded_video_frames(source_hdf5, destination_hdf5, camera_id, frames, jpeg_quality)
