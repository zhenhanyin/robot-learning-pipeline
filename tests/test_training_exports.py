import json
import tempfile
import unittest
from pathlib import Path

from robot_learning.cli import main, write_sample
from robot_learning.core.models import ArmState, CameraFrame
from robot_learning.formats.annotation import AnnotationSpan, EpisodeAnnotation, save_annotation
from robot_learning.formats.episode import JsonlEpisodeWriter
from robot_learning.formats.hdf5 import export_hdf5
from robot_learning.formats.images import rgb_array
from robot_learning.formats.lerobot import export_lerobot
from robot_learning.formats.training import load_training_episode
from robot_learning.formats.vlm import export_vlm


class FakeLeRobotDataset:
    datasets = {}

    def __init__(self, repo_id, root):
        self.root = Path(root)
        self.frames = self.datasets[self.root].frames

    @classmethod
    def create(cls, repo_id, root, fps, robot_type, features, use_videos):
        root = Path(root)
        root.mkdir()
        instance = cls.__new__(cls)
        instance.root = root
        instance.frames = []
        instance.features = features
        instance.fps = fps
        instance.saved = False
        instance.finalized = False
        cls.datasets[root] = instance
        return instance

    def add_frame(self, frame):
        self.frames.append(frame)

    def save_episode(self):
        self.saved = True

    def finalize(self):
        self.finalized = True

    def __len__(self):
        return len(self.frames)

    def __getitem__(self, index):
        return self.frames[index]


class TrainingExportTests(unittest.TestCase):
    def test_same_episode_to_hdf5_and_injected_lerobot(self):
        import h5py

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "episode"
            write_sample(source)
            episode = load_training_episode(source)
            self.assertEqual(episode.action_source.value, "leader_command")
            self.assertEqual(export_hdf5(episode, root / "training.hdf5"), 3)
            with h5py.File(root / "training.hdf5", "r") as output:
                self.assertEqual(output["observation/joint_positions"].shape, (3, 1))
                self.assertEqual(output["action/joint_targets"][:, 0].tolist(), [1.0, 2.0, 3.0])
                self.assertEqual(bytes(output["observation/images/base/payload"][2]), b"\x02")
                self.assertEqual(output.attrs["action_source"], "leader_command")
            target = root / "lerobot"
            self.assertEqual(export_lerobot(episode, target, "local/demo", 10, "test pick", FakeLeRobotDataset), 3)
            dataset = FakeLeRobotDataset.datasets[target]
            self.assertTrue(dataset.saved and dataset.finalized)
            self.assertEqual(dataset.frames[1]["action"].tolist(), [2.0])
            self.assertEqual(dataset.frames[0]["observation.images.base"].shape, (1, 1, 3))
            self.assertEqual(dataset.frames[0]["task"], "test pick")
            mapping = json.loads(Path("integrations/openpi/feature-map.example.json").read_text(encoding="utf-8"))
            self.assertIn(mapping["observation_state_key"], dataset.features)
            self.assertIn(mapping["action_key"], dataset.features)
            manifest = json.loads((target / "robot_learning_export.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["action_source"], "leader_command")
            self.assertEqual(manifest["source_state_timestamps_ns"], [0, 100_000_000, 200_000_000])

    def test_explicit_next_state_policy_and_recorded_default(self):
        import h5py

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "episode"
            with JsonlEpisodeWriter(source, "arx_x5", "ros2_header", "raw_unverified") as writer:
                for index in range(3):
                    timestamp = index * 100_000_000
                    writer.append_state(ArmState("left", timestamp, (float(index),)))
                    writer.append_frame(CameraFrame("head", timestamp, "rgb8", 1, 1, bytes([index, 0, 0])))
            with self.assertRaisesRegex(ValueError, "recorded action missing"):
                load_training_episode(source)
            episode = load_training_episode(source, "next-state")
            self.assertEqual(len(episode.steps), 2)
            self.assertEqual(episode.action_source.value, "next_state")
            self.assertEqual(episode.steps[0].action.joint_targets, (1.0,))
            self.assertEqual(episode.steps[0].action.timestamp_ns, 100_000_000)
            target = Path(temporary) / "next_state.hdf5"
            self.assertEqual(export_hdf5(episode, target), 2)
            with h5py.File(target, "r") as output:
                self.assertEqual(output.attrs["action_source"], "next_state")
                self.assertEqual(output.attrs["joint_units"], "raw_unverified")

    def test_refuses_partial_groups_mixed_sources_and_bad_timing(self):
        from robot_learning.core.models import ActionSource, ArmAction

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "missing"
            with JsonlEpisodeWriter(source, "synthetic", "test", "rad") as writer:
                writer.append_state(ArmState("left", 0, (0.0,)))
                writer.append_action(ArmAction("left", 0, (1.0,), ActionSource.LEADER_COMMAND))
                writer.append_frame(CameraFrame("base", 0, "rgb8", 1, 1, b"abc"))
                writer.append_state(ArmState("left", 100, (1.0,)))
                writer.append_action(ArmAction("left", 100, (2.0,), ActionSource.LEADER_COMMAND))
            with self.assertRaisesRegex(ValueError, "camera set changed"):
                load_training_episode(source)
            source = root / "skew"
            with JsonlEpisodeWriter(source, "synthetic", "test", "rad") as writer:
                writer.append_state(ArmState("left", 0, (0.0,)))
                writer.append_action(ArmAction("left", 50, (1.0,), ActionSource.LEADER_COMMAND))
                writer.append_frame(CameraFrame("base", 0, "rgb8", 1, 1, b"abc"))
            with self.assertRaisesRegex(ValueError, "action exceeds"):
                load_training_episode(source, tolerance_ns=10)
            source = root / "mixed"
            with JsonlEpisodeWriter(source, "synthetic", "test", "rad") as writer:
                for index, action_source in enumerate((ActionSource.LEADER_COMMAND, ActionSource.FOLLOWER_COMMAND)):
                    writer.append_state(ArmState("left", index, (float(index),)))
                    writer.append_action(ArmAction("left", index, (float(index),), action_source))
                    writer.append_frame(CameraFrame("base", index, "rgb8", 1, 1, b"abc"))
            with self.assertRaisesRegex(ValueError, "mixed action sources"):
                load_training_episode(source)

    def test_rgb_mapping_and_lerobot_fps_guard(self):
        self.assertEqual(rgb_array(CameraFrame("base", 0, "bgr8", 1, 1, b"\x01\x02\x03")).tolist(),
                         [[[3, 2, 1]]])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "episode"
            write_sample(source)
            episode = load_training_episode(source)
            with self.assertRaisesRegex(ValueError, "FPS"):
                export_lerobot(episode, root / "out", "local/demo", 30, "test", FakeLeRobotDataset)
            with self.assertRaisesRegex(ValueError, "repo_id"):
                export_lerobot(episode, root / "out", "bad", 10, "test", FakeLeRobotDataset)
            self.assertFalse((root / "out").exists())

    def test_vlm_uses_only_approved_span_and_camera(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "episode"
            with JsonlEpisodeWriter(source, "synthetic", "test", "rad") as writer:
                for index in range(3):
                    writer.append_state(ArmState("left", index, (float(index),)))
                    writer.append_frame(CameraFrame("base", index, "rgb8", 1, 1, bytes([index, 0, 0])))
                    writer.append_frame(CameraFrame("wrist_left", index, "rgb8", 1, 1, bytes([0, index, 0])))
            save_annotation(source, EpisodeAnnotation("tester", (
                AnnotationSpan(0, 4, "pick object", True), AnnotationSpan(4, 6, "ignore", False),
            )))
            destination = root / "vlm"
            self.assertEqual(export_vlm(source, destination, "base", "What is happening?"), 2)
            examples = json.loads((destination / "data.json").read_text(encoding="utf-8"))
            self.assertEqual([item["messages"][1]["content"] for item in examples], ["pick object"] * 2)
            self.assertEqual(examples[0]["images"], ["images/000000.png"])
            with Image.open(destination / examples[0]["images"][0]) as image:
                self.assertEqual(image.size, (1, 1))
            info = json.loads((destination / "dataset_info.json").read_text(encoding="utf-8"))
            self.assertEqual(info["robot_learning_vlm"]["formatting"], "sharegpt")

    def test_cli_export_and_missing_optional_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "episode"
            write_sample(source)
            self.assertEqual(main(["export", str(source), str(root / "episode.hdf5"), "--format", "hdf5"]), 0)
            self.assertEqual(main(["export", str(source), str(root / "episode.hdf5"), "--format", "hdf5"]), 2)


if __name__ == "__main__":
    unittest.main()
