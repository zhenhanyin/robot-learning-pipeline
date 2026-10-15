"""Read-only observation collection through device-independent ports."""

from dataclasses import dataclass
from typing import Mapping, Optional

from robot_learning.core.ports import ActionReader, CameraAdapter, EpisodeWriter, StateReader


@dataclass(frozen=True)
class CollectionSummary:
    attempts: int
    written: int
    dropped: int


def record_samples(
    state_reader: StateReader,
    cameras: Mapping[str, CameraAdapter],
    writer: EpisodeWriter,
    attempts: int,
    tolerance_ns: int,
    action_reader: Optional[ActionReader] = None,
) -> CollectionSummary:
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts <= 0:
        raise ValueError("attempts must be positive")
    if not isinstance(tolerance_ns, int) or isinstance(tolerance_ns, bool) or tolerance_ns < 0:
        raise ValueError("tolerance_ns must be non-negative")
    if not cameras or any(not isinstance(camera_id, str) or not camera_id for camera_id in cameras):
        raise ValueError("at least one named camera is required")

    last_timestamps = {}
    arm_id = None
    written = 0
    for _ in range(attempts):
        state = state_reader.read_state()
        frames = {camera_id: cameras[camera_id].read_frame() for camera_id in sorted(cameras)}
        action = action_reader.read_action() if action_reader is not None else None

        if arm_id is None:
            arm_id = state.arm_id
        elif state.arm_id != arm_id:
            raise ValueError("arm_id changed during collection")
        if action is not None and action.arm_id != state.arm_id:
            raise ValueError("action arm_id does not match state")
        for camera_id, frame in frames.items():
            if frame.camera_id != camera_id:
                raise ValueError("camera_id does not match configured name")

        timestamps = {"state": state.timestamp_ns}
        timestamps.update(("camera:" + camera_id, frame.timestamp_ns) for camera_id, frame in frames.items())
        if action is not None:
            timestamps["action"] = action.timestamp_ns
        for source, timestamp_ns in timestamps.items():
            if timestamp_ns <= last_timestamps.get(source, -1):
                raise ValueError("source timestamps must be strictly increasing")
        last_timestamps.update(timestamps)

        if any(abs(timestamp_ns - state.timestamp_ns) > tolerance_ns for timestamp_ns in timestamps.values()):
            continue
        writer.append_state(state)
        if action is not None:
            writer.append_action(action)
        for frame in frames.values():
            writer.append_frame(frame)
        written += 1

    return CollectionSummary(attempts=attempts, written=written, dropped=attempts - written)
