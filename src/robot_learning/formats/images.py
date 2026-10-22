"""Decode supported Episode images to RGB arrays for training adapters."""

from io import BytesIO

from robot_learning.core.models import CameraFrame


def rgb_array(frame: CameraFrame):
    import numpy as np

    if frame.modality != "rgb":
        raise ValueError("RGB export cannot convert a depth frame")
    if frame.width * frame.height > 50_000_000:
        raise ValueError("training image exceeds pixel limit")
    if frame.encoding in ("png", "jpeg"):
        from PIL import Image

        with Image.open(BytesIO(frame.payload)) as source:
            if source.size != (frame.width, frame.height):
                raise ValueError("image dimensions differ from frame metadata")
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
    raise ValueError("training image export requires PNG, JPEG or 8-bit RGB/mono images")


def depth_array(frame: CameraFrame):
    import numpy as np

    if frame.modality != "depth":
        raise ValueError("depth export requires a depth frame")
    if frame.width * frame.height > 50_000_000:
        raise ValueError("depth image exceeds pixel limit")
    encoding = frame.encoding.lower()
    if encoding in ("16uc1", "mono16", "mono16;endian=little", "16uc1;endian=little"):
        values = np.frombuffer(frame.payload, dtype="<u2")
    elif encoding in ("mono16;endian=big", "16uc1;endian=big"):
        values = np.frombuffer(frame.payload, dtype=">u2").astype(np.uint16)
    elif encoding in ("32fc1", "32fc1;endian=little"):
        values = np.frombuffer(frame.payload, dtype="<f4")
    elif encoding == "32fc1;endian=big":
        values = np.frombuffer(frame.payload, dtype=">f4").astype(np.float32)
    elif encoding in ("png", "depth_png"):
        from io import BytesIO
        from PIL import Image

        with Image.open(BytesIO(frame.payload)) as source:
            if source.size != (frame.width, frame.height):
                raise ValueError("depth image dimensions differ from frame metadata")
            array = np.asarray(source).copy()
        if array.ndim != 2:
            raise ValueError("depth PNG must be a single-channel image")
        return array
    else:
        raise ValueError("unsupported depth image encoding")
    if values.size != frame.width * frame.height:
        raise ValueError("depth payload length differs from dimensions")
    return values.reshape((frame.height, frame.width)).copy()
