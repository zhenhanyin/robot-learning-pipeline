"""Convert supported raw episode frames into browser-safe PNG previews."""

import struct
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PREVIEW_PIXELS = 4_000_000
MAX_PREVIEW_BYTES = 32_000_000


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def frame_preview_png(encoding: str, width: int, height: int, payload: bytes) -> bytes:
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise ValueError("invalid preview dimensions")
    if width * height > MAX_PREVIEW_PIXELS or len(payload) > MAX_PREVIEW_BYTES:
        raise ValueError("preview exceeds size limit")
    if encoding == "png":
        if len(payload) < 24 or not payload.startswith(PNG_SIGNATURE):
            raise ValueError("invalid PNG preview")
        if struct.unpack(">II", payload[16:24]) != (width, height):
            raise ValueError("PNG dimensions do not match episode")
        return payload
    if encoding in ("mono8", "raw8"):
        channels, color_type = 1, 0
        raster = payload
    elif encoding in ("rgb8", "bgr8"):
        channels, color_type = 3, 2
        raster = payload
        if encoding == "bgr8":
            raster = bytes(channel for offset in range(0, len(payload), 3) for channel in payload[offset:offset + 3][::-1])
    elif encoding in ("mono16;endian=little", "mono16;endian=big", "16UC1;endian=little", "16UC1;endian=big"):
        channels, color_type = 1, 0
        if len(payload) != 2 * width * height:
            raise ValueError("preview payload length does not match dimensions")
        raster = payload[1::2] if encoding.endswith("little") else payload[::2]
    else:
        raise ValueError("unsupported preview encoding")
    if len(raster) != width * height * channels:
        raise ValueError("preview payload length does not match dimensions")
    row_bytes = width * channels
    raw = b"".join(b"\x00" + raster[offset:offset + row_bytes] for offset in range(0, len(raster), row_bytes))
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")
