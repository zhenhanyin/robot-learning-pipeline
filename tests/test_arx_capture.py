import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from robot_learning.adapters.arx_x5 import map_robot_status, map_ros2_image
from robot_learning.apps.arx_capture import (
    capture_arx_ros2, load_arx_config, replay_arx_messages,
)
from robot_learning.cli import main
from robot_learning.formats.episode import EpisodeReader
from robot_learning.formats.validation import validate_episode


def message(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: message(item) for key, item in value.items()})
    return value


def status(nanosec, position=0.0):
    return message({"header": {"stamp": {"sec": 1, "nanosec": nanosec}},
                    "joint_pos": [position] * 7, "joint_vel": [0.0] * 7})


def image(nanosec, encoding="rgb8", data=None):
    return message({"header": {"stamp": {"sec": 1, "nanosec": nanosec}},
                    "width": 1, "height": 1, "step": 2 if encoding == "mono16" else 3,
                    "encoding": encoding, "is_bigendian": 1, "data": data or [1, 2, 3]})


class ArxMappingTests(unittest.TestCase):
    def test_status_separates_gripper_and_preserves_stamp(self):
        record = map_robot_status(status(42, 1.5))
        self.assertEqual(record.timestamp_ns, 1_000_000_042)
        self.assertEqual(record.joint_positions, (1.5,) * 6)
        self.assertEqual(record.gripper_position, 1.5)
        self.assertEqual(record.joint_velocities, (0.0,) * 6)

    def test_rejects_invalid_status_and_timestamp(self):
        invalid = status(0)
        invalid.joint_pos = [0.0] * 6
        with self.assertRaisesRegex(ValueError, "seven"):
            map_robot_status(invalid)
        invalid = status(0, float("nan"))
        with self.assertRaisesRegex(ValueError, "finite"):
            map_robot_status(invalid)
        invalid = status(1_000_000_000)
        with self.assertRaisesRegex(ValueError, "timestamp"):
            map_robot_status(invalid)

    def test_image_mapping_and_stride_checks(self):
        record = map_ros2_image("head", image(5))
        self.assertEqual((record.timestamp_ns, record.encoding, record.payload), (1_000_000_005, "rgb8", b"\x01\x02\x03"))
        depth = map_ros2_image("depth", image(5, "mono16", [0, 1]))
        self.assertEqual(depth.encoding, "mono16;endian=big")
        invalid = image(5)
        invalid.step = 4
        with self.assertRaisesRegex(ValueError, "stride"):
            map_ros2_image("head", invalid)


class ArxCaptureTests(unittest.TestCase):
    def setUp(self):
        self.config = load_arx_config(Path("configs/arx_x5_ros2.json"))

    def test_offline_message_replay_and_preview(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "messages.jsonl"
            output = Path(temporary) / "episode"
            with source.open("w", encoding="utf-8") as events:
                for index in range(3):
                    for topic in self.config.cameras.values():
                        events.write(json.dumps({"topic": topic, "message": vars(image(index * 100_000_000))}, default=lambda value: vars(value)) + "\n")
                    events.write(json.dumps({"topic": self.config.follower_status_topic,
                                             "message": vars(status(index * 100_000_000))}, default=lambda value: vars(value)) + "\n")
            summary = replay_arx_messages(self.config, source, output)
            self.assertEqual((summary.written, summary.dropped), (3, 0))
            self.assertTrue(validate_episode(output).valid)
            episode = EpisodeReader(output)
            self.assertEqual(episode.metadata["joint_units"], "arx_raw_joint_unit_unverified")
            records = list(episode.records())
            self.assertEqual(len(records), 9)
            self.assertEqual(sorted(record.camera_id for record in records if hasattr(record, "camera_id")),
                             ["head", "head", "head", "left_wrist", "left_wrist", "left_wrist"])
            self.assertFalse(any(hasattr(record, "source") for record in records))
            self.assertEqual(main(["preview-arx", str(output)]), 0)
            self.assertEqual(main(["replay-arx-messages", "--config", "configs/arx_x5_ros2.json", str(source), str(Path(temporary) / "again")]), 0)

    def test_drops_missing_frames_and_rejects_unknown_topic(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "messages.jsonl"
            events = [
                {"topic": "/camera_01/color/image_raw", "message": vars(image(0))},
                {"topic": self.config.follower_status_topic, "message": vars(status(0))},
            ]
            source.write_text("\n".join(json.dumps(event, default=lambda value: vars(value)) for event in events), encoding="utf-8")
            summary = replay_arx_messages(self.config, source, Path(temporary) / "episode")
            self.assertEqual(summary.written, 0)
            self.assertTrue(validate_episode(Path(temporary) / "episode").valid)
            source.write_text(json.dumps({"topic": "/wrong", "message": {}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unconfigured"):
                replay_arx_messages(self.config, source, Path(temporary) / "other")

    def test_config_requires_explicit_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            data = json.loads(Path("configs/arx_x5_ros2.json").read_text(encoding="utf-8"))
            data["joint_units"] = ""
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "joint_units"):
                load_arx_config(path)
            data["joint_units"] = "rad"
            data["cameras"]["head"] = data["follower_status_topic"]
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "distinct"):
                load_arx_config(path)

    def test_replay_drops_out_of_tolerance_frame(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "messages.jsonl"
            events = [
                {"topic": topic, "message": vars(image(100_000_000))}
                for topic in self.config.cameras.values()
            ]
            events.append({"topic": self.config.follower_status_topic, "message": vars(status(0))})
            source.write_text("\n".join(json.dumps(event, default=lambda value: vars(value)) for event in events), encoding="utf-8")
            summary = replay_arx_messages(self.config, source, Path(temporary) / "episode")
            self.assertEqual((summary.written, summary.dropped), (0, 1))

    def test_fake_ros2_live_capture_cleans_up(self):
        class FakeNode:
            def __init__(self):
                self.callbacks = {}
                self.destroyed = False

            def create_subscription(self, message_type, topic, callback, queue_size):
                self.callbacks[topic] = callback

            def destroy_node(self):
                self.destroyed = True

        class FakeRos:
            def __init__(self):
                self.node = FakeNode()
                self.events = []
                for topic in self_config.cameras.values():
                    self.events.append((topic, image(0)))
                self.events.append((self_config.follower_status_topic, status(0)))
                self.shutdown_called = False

            def init(self):
                pass

            def create_node(self, name):
                return self.node

            def spin_once(self, node, timeout_sec):
                if self.events:
                    topic, sample = self.events.pop(0)
                    node.callbacks[topic](sample)
                else:
                    time.sleep(0.001)

            def shutdown(self):
                self.shutdown_called = True

        self_config = self.config
        ros = FakeRos()
        with tempfile.TemporaryDirectory() as temporary:
            summary = capture_arx_ros2(self.config, Path(temporary) / "episode", ros, object, object)
            self.assertEqual(summary.written, 1)
            self.assertTrue(validate_episode(Path(temporary) / "episode").valid)
        self.assertTrue(ros.node.destroyed)
        self.assertTrue(ros.shutdown_called)


if __name__ == "__main__":
    unittest.main()
