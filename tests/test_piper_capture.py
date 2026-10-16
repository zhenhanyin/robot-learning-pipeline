import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from examples.collect_piper_synthetic import FakePiper, FakeRos
from robot_learning.apps.piper_capture import (
    PiperCaptureConfig, capture_piper_ros1, check_capture_environment, load_capture_config,
)
from robot_learning.cli import main
from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.episode import EpisodeReader, JsonlEpisodeWriter
from robot_learning.formats.validation import validate_episode
from robot_learning.workflows import FrameBuffer, record_buffered_samples


class BufferTests(unittest.TestCase):
    def test_nearest_is_not_reused_and_rejects_old_frames(self):
        buffer = FrameBuffer("base", capacity=3)
        self.assertTrue(buffer.add(CameraFrame("base", 100, "raw8", 1, 1, b"a")))
        self.assertTrue(buffer.add(CameraFrame("base", 105, "raw8", 1, 1, b"b")))
        self.assertFalse(buffer.add(CameraFrame("base", 105, "raw8", 1, 1, b"b")))
        self.assertEqual(buffer.take_nearest(104, 5, 0).payload, b"b")
        self.assertIsNone(buffer.take_nearest(104, 5, 0))
        with self.assertRaisesRegex(ValueError, "camera_id"):
            buffer.add(CameraFrame("wrong", 200, "raw8", 1, 1, b"x"))

    def test_waits_for_future_frame(self):
        buffer = FrameBuffer("base")
        timer = threading.Timer(0.01, lambda: buffer.add(CameraFrame("base", 100, "raw8", 1, 1, b"x")))
        timer.start()
        self.addCleanup(timer.join)
        self.assertEqual(buffer.take_nearest(100, 0, 0.2).timestamp_ns, 100)

    def test_drops_incomplete_group_without_partial_events(self):
        class StateReader:
            def __init__(self):
                self.index = 0

            def read_state(self):
                self.index += 1
                return ArmState("left", self.index * 100, (1.0,))

        buffer = FrameBuffer("base")
        buffer.add(CameraFrame("base", 100, "raw8", 1, 1, b"x"))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            with JsonlEpisodeWriter(directory, "synthetic", "test", "tick") as writer:
                summary = record_buffered_samples(StateReader(), {"base": buffer}, writer, 2, 5, 0)
            self.assertEqual((summary.written, summary.dropped), (1, 1))
            self.assertEqual(len(list(EpisodeReader(directory).records())), 2)

    def test_duplicate_state_is_dropped_but_backwards_time_fails(self):
        class StateReader:
            def __init__(self, timestamps):
                self.timestamps = iter(timestamps)

            def read_state(self):
                return ArmState("left", next(self.timestamps), (1.0,))

        buffer = FrameBuffer("base")
        buffer.add(CameraFrame("base", 100, "raw8", 1, 1, b"x"))
        buffer.add(CameraFrame("base", 200, "raw8", 1, 1, b"y"))

        class ActionReader:
            def __init__(self):
                self.calls = 0

            def read_action(self):
                self.calls += 1
                return ArmAction("left", self.calls * 100, (1.0,), ActionSource.LEADER_COMMAND)

        action_reader = ActionReader()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            with JsonlEpisodeWriter(directory, "synthetic", "test", "tick") as writer:
                summary = record_buffered_samples(
                    StateReader([100, 100, 200]), {"base": buffer}, writer, 3, 0, 0,
                    action_reader=action_reader,
                )
            self.assertEqual((summary.written, summary.dropped), (2, 1))
            self.assertEqual(action_reader.calls, 2)
            other = Path(temporary) / "backwards"
            with JsonlEpisodeWriter(other, "synthetic", "test", "tick") as writer:
                with self.assertRaisesRegex(ValueError, "strictly increasing"):
                    record_buffered_samples(StateReader([200, 100]), {"base": FrameBuffer("base")}, writer, 2, 0, 0)


class PiperCaptureTests(unittest.TestCase):
    def test_fake_can_ros1_pipeline_and_cleanup(self):
        class TrackedPiper(FakePiper):
            instance = None

            def __init__(self, can_name):
                super().__init__(can_name)
                TrackedPiper.instance = self

        config = PiperCaptureConfig(
            "fake:TrackedPiper", "can0", {"base": "/base", "wrist_left": "/wrist"},
            3, 30, 5_000_000, 0, True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            summary = capture_piper_ros1(config, directory, FakeRos(), object, TrackedPiper)
            self.assertEqual(summary.written, 3)
            self.assertEqual(len(list(EpisodeReader(directory).records())), 12)
            self.assertTrue(validate_episode(directory).valid)
            self.assertFalse(TrackedPiper.instance.running)
            self.assertEqual(TrackedPiper.instance.can_name, "can0")

    def test_config_validation_and_offline_doctor(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "config.json"
            source = Path("configs/piper_ros1.json")
            data = json.loads(source.read_text(encoding="utf-8"))
            config_path.write_text(json.dumps(data), encoding="utf-8")
            config = load_capture_config(config_path)
            self.assertEqual(config.cameras["base"], "/ob_camera_02/color/image_raw")
            self.assertIn("can_interface", check_capture_environment(config))
            with patch("robot_learning.apps.piper_capture.check_capture_environment", return_value={"piper_sdk": False}):
                self.assertEqual(main(["doctor-piper", "--config", str(config_path)]), 1)
            data["include_action"] = "false"
            config_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "boolean"):
                load_capture_config(config_path)
            self.assertEqual(main(["collect-piper", "--config", str(config_path), str(Path(temporary) / "out")]), 2)


if __name__ == "__main__":
    unittest.main()
