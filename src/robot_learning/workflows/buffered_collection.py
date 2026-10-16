"""Synchronize asynchronous camera frames with read-only arm samples."""

from collections import deque
from threading import Condition
from time import monotonic
from typing import Callable, Deque, Mapping, Optional

from robot_learning.core.models import CameraFrame
from robot_learning.core.errors import StaleSampleError
from robot_learning.core.ports import ActionReader, EpisodeWriter, StateReader
from robot_learning.workflows.collection import CollectionSummary


class FrameBuffer:
    def __init__(self, camera_id: str, capacity: int = 120) -> None:
        if not isinstance(camera_id, str) or not camera_id:
            raise ValueError("camera_id is required")
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("capacity must be positive")
        self.camera_id = camera_id
        self._frames: Deque[CameraFrame] = deque(maxlen=capacity)
        self._condition = Condition()
        self._last_timestamp_ns = -1

    def add(self, frame: CameraFrame) -> bool:
        if frame.camera_id != self.camera_id:
            raise ValueError("camera_id does not match buffer")
        with self._condition:
            if frame.timestamp_ns <= self._last_timestamp_ns:
                return False
            self._frames.append(frame)
            self._last_timestamp_ns = frame.timestamp_ns
            self._condition.notify_all()
        return True

    def take_nearest(self, anchor_ns: int, tolerance_ns: int, wait_seconds: float) -> Optional[CameraFrame]:
        if type(anchor_ns) is not int or anchor_ns < 0:
            raise ValueError("anchor_ns must be non-negative")
        if type(tolerance_ns) is not int or tolerance_ns < 0:
            raise ValueError("tolerance_ns must be non-negative")
        if wait_seconds < 0:
            raise ValueError("wait_seconds must be non-negative")
        deadline = monotonic() + wait_seconds
        with self._condition:
            while True:
                while self._frames and self._frames[0].timestamp_ns < anchor_ns - tolerance_ns:
                    self._frames.popleft()
                if self._frames and self._frames[-1].timestamp_ns >= anchor_ns:
                    break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            candidates = [
                (abs(frame.timestamp_ns - anchor_ns), index)
                for index, frame in enumerate(self._frames)
                if abs(frame.timestamp_ns - anchor_ns) <= tolerance_ns
            ]
            if not candidates:
                return None
            _, selected_index = min(candidates)
            for _ in range(selected_index):
                self._frames.popleft()
            return self._frames.popleft()


def record_buffered_samples(
    state_reader: StateReader,
    cameras: Mapping[str, FrameBuffer],
    writer: EpisodeWriter,
    attempts: int,
    tolerance_ns: int,
    wait_seconds: float,
    action_reader: Optional[ActionReader] = None,
    pace: Optional[Callable[[], None]] = None,
) -> CollectionSummary:
    if type(attempts) is not int or attempts <= 0:
        raise ValueError("attempts must be positive")
    if type(tolerance_ns) is not int or tolerance_ns < 0:
        raise ValueError("tolerance_ns must be non-negative")
    if wait_seconds < 0:
        raise ValueError("wait_seconds must be non-negative")
    if not cameras or any(camera_id != camera.camera_id for camera_id, camera in cameras.items()):
        raise ValueError("at least one correctly named camera is required")
    written = 0
    last_state_ns = -1
    last_action_ns = -1
    arm_id = None
    for _ in range(attempts):
        try:
            state = state_reader.read_state()
        except StaleSampleError:
            if pace is not None:
                pace()
            continue
        if state.timestamp_ns < last_state_ns:
            raise ValueError("state timestamps must be strictly increasing")
        if state.timestamp_ns == last_state_ns:
            if pace is not None:
                pace()
            continue
        last_state_ns = state.timestamp_ns
        if arm_id is None:
            arm_id = state.arm_id
        elif state.arm_id != arm_id:
            raise ValueError("arm_id changed during collection")
        try:
            action = action_reader.read_action() if action_reader is not None else None
        except StaleSampleError:
            if pace is not None:
                pace()
            continue
        if action is not None:
            if action.arm_id != state.arm_id:
                raise ValueError("action arm_id does not match state")
            if action.timestamp_ns < last_action_ns:
                raise ValueError("action timestamps must be strictly increasing")
            if action.timestamp_ns == last_action_ns:
                if pace is not None:
                    pace()
                continue
            last_action_ns = action.timestamp_ns
        if action is None or abs(action.timestamp_ns - state.timestamp_ns) <= tolerance_ns:
            frames = {
                camera_id: cameras[camera_id].take_nearest(state.timestamp_ns, tolerance_ns, wait_seconds)
                for camera_id in sorted(cameras)
            }
            if all(frame is not None for frame in frames.values()):
                writer.append_state(state)
                if action is not None:
                    writer.append_action(action)
                for frame in frames.values():
                    writer.append_frame(frame)
                written += 1
        if pace is not None:
            pace()
    return CollectionSummary(attempts, written, attempts - written)
