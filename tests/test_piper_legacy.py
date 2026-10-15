import contextlib
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from robot_learning.adapters.piper import import_legacy_run
from robot_learning.cli import main
from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.episode import EpisodeReader
from robot_learning.formats.validation import validate_episode


def png_pixel():
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


def image_name(timestamp):
    return "{:.9f}".format(timestamp).replace(".", "_") + ".png"


class PiperLegacyImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source = root / "legacy"
        self.source.mkdir()
        self.destination = root / "episode"
        image_root = self.source / "img"
        for name in ("front_color", "wrist_color", "front_depth", "wrist_depth"):
            (image_root / name).mkdir(parents=True)
        for index in range(2):
            timestamp = 1000 + index * 0.1
            (image_root / "front_color" / image_name(timestamp)).write_bytes(png_pixel())
            (image_root / "wrist_color" / image_name(timestamp + 0.004)).write_bytes(png_pixel())
        joints = struct.Struct(">ddiiiiii")
        grippers = struct.Struct(">ddiii")
        (self.source / "follower_joint").write_bytes(b"".join(
            joints.pack(1000 + index * 0.1 + 0.001, 30.0, *([index + 1] * 6))
            for index in range(2)
        ))
        (self.source / "leader_joint").write_bytes(b"".join(
            joints.pack(1000 + index * 0.1 + 0.002, 30.0, *([index + 10] * 6))
            for index in range(2)
        ))
        (self.source / "follower_gripper").write_bytes(b"".join(
            grippers.pack((1000 + index * 0.1 + 0.003) * 1_000_000_000, 30.0, 100 + index, 0, 0)
            for index in range(2)
        ))
        (self.source / "leader_gripper").write_bytes(b"".join(
            grippers.pack((1000 + index * 0.1 + 0.003) * 1_000_000_000, 30.0, 200 + index, 0, 0)
            for index in range(2)
        ))

    def test_imports_complete_samples_and_preserves_source(self):
        summary = import_legacy_run(self.source, self.destination)
        self.assertEqual((summary.source_frames, summary.written_samples, summary.dropped_samples), (2, 2, 0))
        self.assertEqual(summary.cameras, ("base", "wrist_left"))
        episode = EpisodeReader(self.destination)
        self.assertEqual(episode.metadata["joint_units"], "piper_raw_joint_tick")
        self.assertEqual(episode.metadata["gripper_units"], "piper_raw_gripper_tick")
        records = list(episode.records())
        self.assertEqual(len(records), 8)
        self.assertEqual([type(record) for record in records[:4]], [ArmState, ArmAction, CameraFrame, CameraFrame])
        self.assertEqual(records[0].joint_positions, (1.0,) * 6)
        self.assertEqual(records[0].gripper_position, 100.0)
        self.assertEqual(records[1].source, ActionSource.LEADER_COMMAND)
        self.assertEqual(records[1].joint_targets, (10.0,) * 6)
        self.assertEqual(records[1].gripper_target, 200.0)
        self.assertEqual(records[2].payload, png_pixel())
        self.assertTrue(validate_episode(self.destination).valid)
        self.assertTrue((self.source / "follower_joint").exists())

    def test_cli_and_dropped_frame(self):
        image = self.source / "img" / "front_color" / "1000_300000000.png"
        image.write_bytes(png_pixel())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["import-piper-legacy", str(self.source), str(self.destination)]), 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["written_samples"], 2)
        self.assertEqual(summary["dropped_samples"], 1)
        self.assertTrue(validate_episode(self.destination).valid)

    def test_imports_optional_depth_images(self):
        image_root = self.source / "img"
        for index in range(2):
            timestamp = 1000 + index * 0.1
            for name in ("front_depth", "wrist_depth"):
                (image_root / name / image_name(timestamp)).write_bytes(png_pixel())
        summary = import_legacy_run(self.source, self.destination)
        self.assertEqual(len(summary.cameras), 4)
        self.assertEqual(sum(isinstance(record, CameraFrame) for record in EpisodeReader(self.destination).records()), 8)
        self.assertTrue(validate_episode(self.destination).valid)

    def test_rejects_truncated_stream_before_writing(self):
        with (self.source / "leader_joint").open("ab") as stream:
            stream.write(b"\x00")
        with self.assertRaisesRegex(ValueError, "truncated legacy stream"):
            import_legacy_run(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_rejects_invalid_png_and_symlink(self):
        image = next((self.source / "img" / "front_color").iterdir())
        image.write_bytes(b"invalid")
        with self.assertRaisesRegex(ValueError, "invalid PNG header"):
            import_legacy_run(self.source, self.destination)
        image.unlink()
        image.symlink_to(self.source / "follower_joint")
        with self.assertRaisesRegex(ValueError, "required regular file missing"):
            import_legacy_run(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_rejects_unmatched_timestamps(self):
        with self.assertRaisesRegex(ValueError, "no complete legacy samples"):
            import_legacy_run(self.source, self.destination, tolerance_ns=0)
        self.assertFalse(self.destination.exists())

    def test_rejects_invalid_image_name_and_existing_destination(self):
        (self.source / "img" / "front_color" / "bad.png").write_bytes(png_pixel())
        with self.assertRaisesRegex(ValueError, "invalid timestamped PNG filename"):
            import_legacy_run(self.source, self.destination)
        self.assertFalse(self.destination.exists())
        self.destination.mkdir()
        with self.assertRaises(FileExistsError):
            import_legacy_run(self.source, self.destination)

    def test_rejects_unpaired_depth_and_out_of_order_stream(self):
        front_depth = self.source / "img" / "front_depth"
        (front_depth / image_name(1000.0)).write_bytes(png_pixel())
        with self.assertRaisesRegex(ValueError, "both depth cameras must have images"):
            import_legacy_run(self.source, self.destination)
        (front_depth / image_name(1000.0)).unlink()
        joints = struct.Struct(">ddiiiiii")
        with (self.source / "follower_joint").open("ab") as stream:
            stream.write(joints.pack(999.0, 30.0, *([3] * 6)))
        with self.assertRaisesRegex(ValueError, "timestamps must be strictly increasing"):
            import_legacy_run(self.source, self.destination)
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
