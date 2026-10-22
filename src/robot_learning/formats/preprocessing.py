"""Deterministic action statistics, normalization, and gripper cleanup."""

import json
import math
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


@dataclass(frozen=True)
class ActionStatistics:
    count: int
    minimum: Tuple[float, ...]
    maximum: Tuple[float, ...]
    mean: Tuple[float, ...]
    standard_deviation: Tuple[float, ...]

    def to_dict(self):
        return asdict(self)


def action_statistics(samples: Iterable[Sequence[float]]) -> ActionStatistics:
    count = 0
    minimum = maximum = means = sums_squared = None
    for sample in samples:
        values = tuple(float(value) for value in sample)
        if not values or not all(math.isfinite(value) for value in values):
            raise ValueError("action samples must contain finite values")
        if means is None:
            minimum = list(values)
            maximum = list(values)
            means = [0.0] * len(values)
            sums_squared = [0.0] * len(values)
        if len(values) != len(means):
            raise ValueError("action sample dimensions changed")
        count += 1
        for index, value in enumerate(values):
            minimum[index] = min(minimum[index], value)
            maximum[index] = max(maximum[index], value)
            delta = value - means[index]
            means[index] += delta / count
            sums_squared[index] += delta * (value - means[index])
    if not count:
        raise ValueError("at least one action sample is required")
    deviations = tuple(math.sqrt(max(0.0, value / count)) for value in sums_squared)
    return ActionStatistics(count, tuple(minimum), tuple(maximum), tuple(means), deviations)


def normalize_action(values: Sequence[float], statistics: ActionStatistics, method: str = "minmax"):
    values = tuple(float(value) for value in values)
    if len(values) != len(statistics.minimum) or not all(math.isfinite(value) for value in values):
        raise ValueError("action dimensions or values are invalid")
    if method == "minmax":
        return tuple(0.0 if high == low else 2.0 * (value - low) / (high - low) - 1.0
                     for value, low, high in zip(values, statistics.minimum, statistics.maximum))
    if method == "zscore":
        return tuple(0.0 if deviation == 0 else (value - mean) / deviation
                     for value, mean, deviation in zip(values, statistics.mean,
                                                       statistics.standard_deviation))
    raise ValueError("normalization method must be minmax or zscore")


def denormalize_action(values: Sequence[float], statistics: ActionStatistics, method: str = "minmax"):
    values = tuple(float(value) for value in values)
    if len(values) != len(statistics.minimum) or not all(math.isfinite(value) for value in values):
        raise ValueError("action dimensions or values are invalid")
    if method == "minmax":
        return tuple(low if high == low else low + (value + 1.0) * (high - low) / 2.0
                     for value, low, high in zip(values, statistics.minimum, statistics.maximum))
    if method == "zscore":
        return tuple(mean if deviation == 0 else mean + value * deviation
                     for value, mean, deviation in zip(values, statistics.mean,
                                                       statistics.standard_deviation))
    raise ValueError("normalization method must be minmax or zscore")


def smooth_gripper(values: Sequence[float], window_size: int = 5, threshold_ratio: float = 0.05,
                   min_stable_frames: int = 5, open_value: Optional[float] = None,
                   closed_value: Optional[float] = None) -> Tuple[float, ...]:
    values = tuple(float(value) for value in values)
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("gripper values must be non-empty and finite")
    if type(window_size) is not int or window_size < 1:
        raise ValueError("window_size must be a positive integer")
    if type(min_stable_frames) is not int or min_stable_frames < 1:
        raise ValueError("min_stable_frames must be a positive integer")
    if not math.isfinite(threshold_ratio) or threshold_ratio < 0:
        raise ValueError("threshold_ratio must be finite and non-negative")
    closed_value = min(values) if closed_value is None else float(closed_value)
    open_value = max(values) if open_value is None else float(open_value)
    if not math.isfinite(closed_value) or not math.isfinite(open_value):
        raise ValueError("open and closed values must be finite")
    threshold = abs(open_value - closed_value) * threshold_ratio

    if len(values) < window_size:
        processed = list(values)
    else:
        edge = window_size // 2
        processed = []
        for index in range(len(values)):
            start = index - edge
            processed.append(sum(values[position] for position in range(start, start + window_size)
                                 if 0 <= position < len(values)) / window_size)
        if edge:
            processed[:edge] = values[:edge]
            processed[-edge:] = values[-edge:]

    stabilized = list(processed)
    for index, value in enumerate(processed):
        if abs(value - closed_value) < threshold:
            stabilized[index] = closed_value
        if abs(value - open_value) < threshold:
            stabilized[index] = open_value

    locked = list(stabilized)
    stable_value = stabilized[0]
    stable_count = 0
    previous = stabilized[0]
    for index, value in enumerate(stabilized):
        change = abs(value - previous)
        if change < threshold:
            stable_count += 1
            if stable_count >= min_stable_frames:
                locked[index] = stable_value
        else:
            stable_value = value
            stable_count = 0
        previous = value
    return tuple(locked)


def hdf5_action_statistics(source: Path) -> ActionStatistics:
    try:
        import h5py
    except ImportError as error:
        raise ImportError("HDF5 statistics require h5py") from error
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError("source must be a regular HDF5 file")
    with h5py.File(source, "r") as recording:
        if "action" in recording and isinstance(recording["action"], h5py.Dataset):
            data = recording["action"][:]
        elif "actions" in recording and isinstance(recording["actions"], h5py.Dataset):
            data = recording["actions"][:]
        elif "action/joint_targets" in recording:
            import numpy as np

            columns = [recording["action/joint_targets"][:]]
            if "action/gripper_target" in recording:
                columns.append(recording["action/gripper_target"][:].reshape(-1, 1))
            data = np.concatenate(columns, axis=1)
        elif "joint_action/vector" in recording:
            data = recording["joint_action/vector"][:]
        elif "joint_action/left_arm" in recording:
            import numpy as np

            columns = [recording["joint_action/left_arm"][:]]
            if "joint_action/left_gripper" in recording:
                columns.append(recording["joint_action/left_gripper"][:].reshape(-1, 1))
            if "joint_action/right_arm" in recording:
                columns.append(recording["joint_action/right_arm"][:])
                if "joint_action/right_gripper" in recording:
                    columns.append(recording["joint_action/right_gripper"][:].reshape(-1, 1))
            data = np.concatenate(columns, axis=1)
        else:
            raise ValueError("no supported action dataset found")
    if getattr(data, "ndim", 0) == 1:
        data = data.reshape((-1, 1))
    if getattr(data, "ndim", 0) != 2:
        raise ValueError("action dataset must be one- or two-dimensional")
    return action_statistics(data)


def smooth_hdf5_grippers(source: Path, destination: Path, window_size: int = 5,
                         threshold_ratio: float = 0.05, min_stable_frames: int = 5) -> int:
    try:
        import h5py
        import numpy as np
    except ImportError as error:
        raise ImportError("HDF5 gripper processing requires numpy and h5py") from error
    source = Path(source)
    destination = Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError("source must be a regular HDF5 file")
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError("destination must not exist and its parent must exist")
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".gripper-", suffix=".hdf5",
                                                   dir=str(destination.parent))
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        changed = 0
        with h5py.File(temporary, "r+") as recording:
            paths = []
            for path in ("endpose/left_gripper", "joint_action/left_gripper"):
                if path in recording:
                    paths.append(path)
            if "joint_action/vector" in recording:
                vector = recording["joint_action/vector"]
                if len(vector.shape) != 2 or vector.shape[1] <= 6:
                    raise ValueError("joint_action/vector must contain gripper column 6")
                paths.append("joint_action/vector")
            for path in paths:
                dataset = recording[path]
                if dataset.dtype.kind != "f":
                    raise ValueError("gripper datasets must use a floating-point dtype: " + path)
                data = dataset[:]
                if path == "joint_action/vector":
                    data[:, 6] = smooth_gripper(data[:, 6], window_size, threshold_ratio,
                                                min_stable_frames)
                else:
                    data[:] = smooth_gripper(data, window_size, threshold_ratio,
                                             min_stable_frames)
                dataset[:] = data
                changed += 1
            if not changed:
                raise ValueError("no supported gripper datasets found")
            recording.attrs["robot_learning_gripper_smoothing"] = json.dumps({
                "window_size": window_size,
                "threshold_ratio": threshold_ratio,
                "min_stable_frames": min_stable_frames,
                "datasets": paths,
            }, sort_keys=True)
        os.replace(temporary, destination)
        return changed
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
