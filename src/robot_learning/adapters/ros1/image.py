"""Map unpadded ROS1 Image messages to portable CameraFrame records."""

from threading import Lock
from typing import Callable

from robot_learning.core.models import CameraFrame


BYTES_PER_PIXEL = {
    "rgb8": 3,
    "bgr8": 3,
    "mono8": 1,
    "mono16": 2,
    "16uc1": 2,
}


class LatestMessage:
    def __init__(self) -> None:
        self._lock = Lock()
        self._message = None

    def update(self, message: object) -> None:
        with self._lock:
            self._message = message

    def get(self) -> object:
        with self._lock:
            if self._message is None:
                raise ValueError("no camera message received")
            return self._message


class Ros1ImageReader:
    def __init__(self, camera_id: str, latest_message: Callable[[], object]) -> None:
        if not isinstance(camera_id, str) or not camera_id:
            raise ValueError("camera_id is required")
        self.camera_id = camera_id
        self.latest_message = latest_message

    def read_frame(self) -> CameraFrame:
        return map_ros1_image(self.camera_id, self.latest_message())


def map_ros1_image(camera_id: str, message: object) -> CameraFrame:
    if not isinstance(camera_id, str) or not camera_id:
        raise ValueError("camera_id is required")
    width = message.width
    height = message.height
    step = message.step
    encoding = message.encoding
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("ROS1 image dimensions must be positive integers")
    if not isinstance(encoding, str) or encoding.lower() not in BYTES_PER_PIXEL:
        raise ValueError("unsupported ROS1 image encoding")
    if type(step) is not int or step != width * BYTES_PER_PIXEL[encoding.lower()]:
        raise ValueError("padded or invalid ROS1 image row stride")
    payload = bytes(message.data)
    if len(payload) != step * height:
        raise ValueError("ROS1 image payload length does not match dimensions")
    if BYTES_PER_PIXEL[encoding.lower()] == 2:
        if type(message.is_bigendian) is not int or message.is_bigendian not in (0, 1):
            raise ValueError("ROS1 16-bit image byte order is required")
        encoding = "{};endian={}".format(encoding, "big" if message.is_bigendian else "little")
    timestamp_ns = message.header.stamp.to_nsec()
    if type(timestamp_ns) is not int or timestamp_ns < 0:
        raise ValueError("ROS1 image timestamp must be nanoseconds")
    return CameraFrame(camera_id, timestamp_ns, encoding, width, height, payload)
