import struct
import unittest
import zlib

from robot_learning.apps.preview import frame_preview_png


class PreviewTests(unittest.TestCase):
    def test_bgr_and_depth_preview(self):
        bgr = frame_preview_png("bgr8", 1, 1, b"\x01\x02\x03")
        self.assertEqual(zlib.decompress(bgr[41:-16]), b"\x00\x03\x02\x01")
        depth = frame_preview_png("16UC1;endian=little", 1, 1, b"\x00\x80")
        self.assertEqual(zlib.decompress(depth[41:-16]), b"\x00\x80")

    def test_rejects_bad_dimensions_encoding_and_payload(self):
        for encoding, width, height, payload in (
            ("rgb8", 0, 1, b""),
            ("rgb8", 1, 1, b"\x00"),
            ("jpeg", 1, 1, b"\x00"),
            ("16UC1;endian=little", 1, 1, b"\x00\x01\x02"),
        ):
            with self.subTest(encoding=encoding, payload=payload), self.assertRaises(ValueError):
                frame_preview_png(encoding, width, height, payload)
        png = frame_preview_png("rgb8", 1, 1, b"\x00\x00\x00")
        with self.assertRaisesRegex(ValueError, "dimensions"):
            frame_preview_png("png", 2, 1, png)
        self.assertEqual(struct.unpack(">II", png[16:24]), (1, 1))


if __name__ == "__main__":
    unittest.main()
