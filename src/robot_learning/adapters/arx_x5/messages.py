"""Read-only mapping for the legacy ARX X5 ROS2 message layout."""

from math import isfinite
from queue import Empty, Queue

from robot_learning.adapters.image import BYTES_PER_PIXEL
from robot_learning.core.errors import StaleSampleError
from robot_learning.core.models import ArmState, CameraFrame
from robot_learning.workflows.buffered_collection import FrameBuffer


def ros2_timestamp_ns(message: object) -> int:
    stamp = message.header.stamp
    if type(stamp.sec) is not int or type(stamp.nanosec) is not int:
        raise ValueError("ROS2 stamp must contain integer sec and nanosec")
    if stamp.sec < 0 or not 0 <= stamp.nanosec < 1_000_000_000:
        raise ValueError("invalid ROS2 timestamp")
    return stamp.sec * 1_000_000_000 + stamp.nanosec


def map_robot_status(message: object, arm_id: str = "left") -> ArmState:
    positions = tuple(float(value) for value in message.joint_pos)
    velocities = tuple(float(value) for value in message.joint_vel)
    if len(positions) != 7 or len(velocities) != 7:
        raise ValueError("ARX RobotStatus requires seven joint positions and velocities")
    if not all(isfinite(value) for value in positions + velocities):
        raise ValueError("ARX RobotStatus must contain finite joint values")
    return ArmState(arm_id, ros2_timestamp_ns(message), positions[:6], positions[6], velocities[:6])


def map_ros2_image(camera_id: str, message: object) -> CameraFrame:
    width, height, step, encoding = message.width, message.height, message.step, message.encoding
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("ROS2 image dimensions must be positive integers")
    if not isinstance(encoding, str) or encoding.lower() not in BYTES_PER_PIXEL:
        raise ValueError("unsupported ROS2 image encoding")
    if type(step) is not int or step != width * BYTES_PER_PIXEL[encoding.lower()]:
        raise ValueError("padded or invalid ROS2 image row stride")
    payload = bytes(message.data)
    if len(payload) != step * height:
        raise ValueError("ROS2 image payload length does not match dimensions")
    if BYTES_PER_PIXEL[encoding.lower()] == 2:
        if type(message.is_bigendian) is not int or message.is_bigendian not in (0, 1):
            raise ValueError("ROS2 16-bit image byte order is required")
        encoding = "{};endian={}".format(encoding, "big" if message.is_bigendian else "little")
    return CameraFrame(camera_id, ros2_timestamp_ns(message), encoding, width, height, payload)


class ArxRos2Stream:
    def __init__(self, camera_ids, state_wait_seconds: float = 0.1, camera_capacity: int = 120) -> None:
        if state_wait_seconds < 0:
            raise ValueError("state_wait_seconds must be non-negative")
        self.cameras = {camera_id: FrameBuffer(camera_id, camera_capacity) for camera_id in camera_ids}
        if not self.cameras:
            raise ValueError("at least one camera is required")
        self._states = Queue()
        self._state_wait_seconds = state_wait_seconds

    def receive_status(self, message: object) -> None:
        self._states.put(map_robot_status(message))

    def receive_image(self, camera_id: str, message: object) -> None:
        self.cameras[camera_id].add(map_ros2_image(camera_id, message))

    def read_state(self) -> ArmState:
        try:
            return self._states.get(timeout=self._state_wait_seconds)
        except Empty as error:
            raise StaleSampleError("no ARX follower status received") from error
