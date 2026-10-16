"""Decode supported Episode images to RGB arrays for training adapters."""

from io import BytesIO

from robot_learning.core.models import CameraFrame


def rgb_array(frame: CameraFrame):
    import numpy as np

    if frame.width * frame.height > 50_000_000:
        raise ValueError("training image exceeds pixel limit")
    if frame.encoding == "png":
        from PIL import Image

        with Image.open(BytesIO(frame.payload)) as source:
            if source.size != (frame.width, frame.height):
                raise ValueError("PNG dimensions differ from frame metadata")
            return np.asarray(source.convert("RGB")).copy()
    if frame.encoding in ("rgb8", "bgr8"):
        array = np.frombuffer(frame.payload, dtype=np.uint8)
        if array.size != frame.width * frame.height * 3:
            raise ValueError("RGB payload length differs from dimensions")
        array = array.reshape((frame.height, frame.width, 3))
        return array.copy() if frame.encoding == "rgb8" else array[:, :, ::-1].copy()
    if frame.encoding in ("mono8", "raw8"):
        array = np.frombuffer(frame.payload, dtype=np.uint8)
        if array.size != frame.width * frame.height:
            raise ValueError("mono payload length differs from dimensions")
        return np.repeat(array.reshape((frame.height, frame.width, 1)), 3, axis=2)
    raise ValueError("training image export requires PNG or 8-bit RGB/mono images")
