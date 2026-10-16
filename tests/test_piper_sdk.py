import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from robot_learning.adapters.piper import PiperReadOnlyAdapter
from robot_learning.adapters.ros1 import LatestMessage, Ros1ImageReader
from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.episode import EpisodeReader, JsonlEpisodeWriter
from robot_learning.formats.validation import validate_episode
from robot_learning.workflows.collection import record_samples


def joints(value):
    return SimpleNamespace(**{"joint_{}".format(index): value for index in range(1, 7)})


def image(timestamp_ns, encoding="rgb8", payload=b"\x00\x01\x02", step=3, is_bigendian=0):
    return SimpleNamespace(
        width=1,
        height=1,
        step=step,
        encoding=encoding,
        data=payload,
        is_bigendian=is_bigendian,
        header=SimpleNamespace(stamp=SimpleNamespace(to_nsec=lambda: timestamp_ns)),
    )


class FakePiper:
    def __init__(self):
        self.index = 0
        self.gripper_offset_ns = 0

    def timestamp_ns(self):
        return 1_000_000_000_000 + self.index * 100_000_000

    def GetArmJointMsgs(self):
        return SimpleNamespace(time_stamp=self.timestamp_ns() / 1_000_000_000, joint_state=joints(self.index + 1))

    def GetArmGripperMsgs(self):
        return SimpleNamespace(
            time_stamp=self.timestamp_ns() + self.gripper_offset_ns,
            gripper_state=SimpleNamespace(grippers_angle=100 + self.index),
        )

    def GetArmJointCtrl(self):
        return SimpleNamespace(time_stamp=self.timestamp_ns() / 1_000_000_000, joint_ctrl=joints(10 + self.index))

    def GetArmGripperCtrl(self):
        result = SimpleNamespace(
            time_stamp=self.timestamp_ns(),
            gripper_ctrl=SimpleNamespace(grippers_angle=200 + self.index),
        )
        self.index += 1
        return result


class PiperSdkTests(unittest.TestCase):
    def test_fake_sdk_ros_image_and_collection(self):
        fake = FakePiper()
        adapter = PiperReadOnlyAdapter(fake)
        image_index = iter(range(2))
        camera = Ros1ImageReader("base", lambda: image(1_000_000_000_000 + next(image_index) * 100_000_000))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            with JsonlEpisodeWriter(
                directory, "piper", "legacy_piper_epoch_assumed",
                "piper_raw_joint_tick", "piper_raw_gripper_tick",
            ) as writer:
                summary = record_samples(adapter, {"base": camera}, writer, 2, 30_000_000, adapter)
            self.assertEqual((summary.written, summary.dropped), (2, 0))
            records = list(EpisodeReader(directory).records())
            self.assertEqual([type(record) for record in records[:3]], [ArmState, ArmAction, CameraFrame])
            self.assertEqual(records[0].joint_positions, (1.0,) * 6)
            self.assertEqual(records[1].source, ActionSource.LEADER_COMMAND)
            self.assertEqual(records[2].payload, b"\x00\x01\x02")
            self.assertTrue(validate_episode(directory).valid)

    def test_stale_gripper_and_invalid_setup(self):
        fake = FakePiper()
        fake.gripper_offset_ns = 50_000_000
        with self.assertRaisesRegex(ValueError, "outside tolerance"):
            PiperReadOnlyAdapter(fake).read_state()
        with self.assertRaises(ValueError):
            PiperReadOnlyAdapter(fake, arm_id="")
        with self.assertRaises(ValueError):
            PiperReadOnlyAdapter(fake, max_gripper_skew_ns=-1)

    def test_ros1_image_validation_and_byte_order(self):
        buffer = LatestMessage()
        reader = Ros1ImageReader("base_depth", buffer.get)
        with self.assertRaisesRegex(ValueError, "no camera message"):
            reader.read_frame()
        buffer.update(image(3, encoding="16UC1", payload=b"\x01\x00", step=2))
        self.assertEqual(reader.read_frame().encoding, "16UC1;endian=little")
        buffer.update(image(4, encoding="16UC1", payload=b"\x00\x01", step=2, is_bigendian=1))
        self.assertEqual(reader.read_frame().encoding, "16UC1;endian=big")
        buffer.update(image(5, encoding="rgb8", step=4))
        with self.assertRaisesRegex(ValueError, "row stride"):
            reader.read_frame()
        buffer.update(image(6, encoding="jpeg"))
        with self.assertRaisesRegex(ValueError, "unsupported"):
            reader.read_frame()
        buffer.update(image(7, payload=b"\x00"))
        with self.assertRaisesRegex(ValueError, "payload length"):
            reader.read_frame()


if __name__ == "__main__":
    unittest.main()
