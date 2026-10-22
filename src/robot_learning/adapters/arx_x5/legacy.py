"""Read-only mapping for the old ARX HDF5 joint-action layout."""

from io import BytesIO
from math import isfinite
from pathlib import Path
from shutil import rmtree
from typing import Optional, Tuple

from robot_learning.core.models import ArmState, CameraFrame, RobotCommand
from robot_learning.formats.episode import JsonlEpisodeWriter


CAMERA_DATASETS = {
    "head": "observation/head_camera/rgb",
    "left_wrist": "observation/left_camera/rgb",
    "front": "observation/front_camera/rgb",
    "right_wrist": "observation/right_camera/rgb",
}
CAMERA_CALIBRATION_DATASETS = {
    "cam2world_gl": (4, 4),
    "extrinsic_cv": (3, 4),
    "intrinsic_cv": (3, 3),
}


def read_legacy_arx_commands(source: Path, rate_hz: float, arm_id: str = "left") -> Tuple[RobotCommand, ...]:
    if not isfinite(rate_hz) or rate_hz <= 0 or not arm_id:
        raise ValueError("positive replay rate and arm ID are required")
    try:
        import h5py
    except ImportError as error:
        raise ImportError("legacy ARX replay requires h5py") from error
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError("legacy ARX source must be a regular HDF5 file")
    with h5py.File(source, "r") as recording:
        if "joint_action/left_arm" not in recording or "joint_action/left_gripper" not in recording:
            raise ValueError("legacy ARX joint_action/left_arm and left_gripper are required")
        joints = recording["joint_action/left_arm"]
        grippers = recording["joint_action/left_gripper"]
        if len(joints.shape) != 2 or joints.shape[1] != 6 or len(grippers.shape) != 1 or len(joints) != len(grippers) or not len(joints):
            raise ValueError("legacy ARX left-arm and gripper dimensions differ")
        commands = []
        for index in range(len(joints)):
            values = tuple(float(value) for value in joints[index])
            gripper = float(grippers[index])
            if not all(isfinite(value) for value in values + (gripper,)):
                raise ValueError("legacy ARX action contains non-finite values")
            commands.append(RobotCommand(arm_id, round(index * 1_000_000_000 / rate_hz), values, gripper))
    return tuple(commands)


def read_legacy_arx_frame(source: Path, camera_id: str, index: int,
                          rate_hz: float) -> CameraFrame:
    if camera_id not in CAMERA_DATASETS or type(index) is not int or index < 0:
        raise ValueError("known camera ID and non-negative frame index required")
    if not isfinite(rate_hz) or rate_hz <= 0:
        raise ValueError("positive replay rate is required")
    try:
        import h5py
        from PIL import Image
    except ImportError as error:
        raise ImportError("legacy ARX images require h5py and Pillow") from error
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError("legacy ARX source must be a regular HDF5 file")
    with h5py.File(source, "r") as recording:
        dataset_name = CAMERA_DATASETS[camera_id]
        if dataset_name not in recording or index >= len(recording[dataset_name]):
            raise ValueError("legacy ARX image is missing")
        payload = bytes(recording[dataset_name][index]).rstrip(b"\x00")
    if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
        raise ValueError("legacy ARX JPEG is empty or corrupt")
    with Image.open(BytesIO(payload)) as image:
        width, height = image.size
    return CameraFrame(camera_id, round(index * 1_000_000_000 / rate_hz),
                       "jpeg", width, height, payload)


def import_legacy_arx_episode(source: Path, destination: Path, rate_hz: float,
                              cameras: Optional[Tuple[str, ...]] = None) -> int:
    if cameras is not None and (not cameras or len(set(cameras)) != len(cameras)
                                or any(camera not in CAMERA_DATASETS for camera in cameras)):
        raise ValueError("distinct legacy ARX camera names are required")
    commands = read_legacy_arx_commands(source, rate_hz)
    try:
        import h5py
        from PIL import Image
    except ImportError as error:
        raise ImportError("legacy ARX import requires h5py and Pillow") from error
    with h5py.File(source, "r") as recording:
        if cameras is None:
            cameras = tuple(camera for camera, dataset in CAMERA_DATASETS.items() if dataset in recording)
        if not cameras:
            raise ValueError("legacy ARX file has no supported camera datasets")
        for camera in cameras:
            dataset_name = CAMERA_DATASETS[camera]
            if dataset_name not in recording or len(recording[dataset_name]) != len(commands):
                raise ValueError("legacy ARX camera length differs from joints: " + camera)
        endposes = None
        if "endpose/left_endpose" in recording:
            dataset = recording["endpose/left_endpose"]
            if len(dataset.shape) != 2 or dataset.shape != (len(commands), 7):
                raise ValueError("legacy ARX end-effector poses must have shape (frames, 7)")
            endposes = dataset[:]
            if not all(isfinite(float(value)) for row in endposes for value in row):
                raise ValueError("legacy ARX end-effector pose contains non-finite values")
        calibration_paths = {}
        for camera_id in cameras:
            group_name = CAMERA_DATASETS[camera_id].rsplit("/", 1)[0]
            fields = {}
            for field, shape in CAMERA_CALIBRATION_DATASETS.items():
                dataset_name = group_name + "/" + field
                if dataset_name not in recording:
                    continue
                dataset = recording[dataset_name]
                if dataset.shape != (len(commands),) + shape:
                    raise ValueError("legacy ARX camera calibration dimensions differ: " + dataset_name)
                fields[field] = dataset_name
            if fields:
                calibration_paths[camera_id] = fields
        pointcloud_info = None
        if "pointcloud" in recording:
            pointcloud = recording["pointcloud"]
            if pointcloud.size:
                raise ValueError("non-empty legacy pointcloud datasets require an explicit point format")
            pointcloud_info = {"source_shape": list(pointcloud.shape), "stored": False}
        extra_metadata = {
            "source_format": "legacy_arx_hdf5",
            "source_action_semantics": "joint_action_left_arm_and_gripper; confirm whether state or command",
        }
        if "joint_action/right_arm" in recording:
            right_arm = recording["joint_action/right_arm"]
            extra_metadata["legacy_right_arm_all_zero_placeholder"] = bool(
                all(float(value) == 0.0 for row in right_arm for value in row)
            )
        if endposes is not None:
            extra_metadata.update({
                "end_effector_pose_units": "legacy_arx_units_unverified",
                "end_effector_frame": "unspecified",
            })
        if pointcloud_info is not None:
            extra_metadata["pointcloud"] = pointcloud_info
        writer = JsonlEpisodeWriter(destination, "arx_x5_legacy", "synthetic_index_from_rate",
                                    "arx_raw_joint_unit_unverified", "arx_raw_gripper_unit_unverified",
                                    extra_metadata)
        try:
            with writer:
                for index, command in enumerate(commands):
                    pose = None if endposes is None else tuple(float(value) for value in endposes[index])
                    writer.append_state(ArmState(
                        command.arm_id, command.timestamp_ns, command.joint_targets, command.gripper_target,
                        end_effector_pose=pose,
                        end_effector_pose_format="xyz_quaternion_xyzw" if pose is not None else None,
                    ))
                    for camera in cameras:
                        payload = bytes(recording[CAMERA_DATASETS[camera]][index]).rstrip(b"\x00")
                        if not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
                            raise ValueError("legacy ARX JPEG is empty or corrupt")
                        with Image.open(BytesIO(payload)) as image:
                            width, height = image.size
                        calibration = {}
                        for field, dataset_name in calibration_paths.get(camera, {}).items():
                            matrix = recording[dataset_name][index]
                            values = tuple(float(value) for value in matrix.reshape(-1))
                            if not all(isfinite(value) for value in values):
                                raise ValueError("legacy ARX camera calibration contains non-finite values")
                            calibration[field] = values
                        writer.append_frame(CameraFrame(camera, command.timestamp_ns, "jpeg",
                                                        width, height, payload, "rgb",
                                                        calibration.get("intrinsic_cv"),
                                                        calibration.get("extrinsic_cv"),
                                                        calibration.get("cam2world_gl")))
        except Exception:
            rmtree(destination)
            raise
    return len(commands)
