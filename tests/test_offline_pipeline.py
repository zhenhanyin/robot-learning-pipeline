import json
import tempfile
import unittest
from pathlib import Path

from robot_learning.cli import main, write_sample
from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.annotation import AnnotationSpan, EpisodeAnnotation, load_annotation, save_annotation
from robot_learning.formats.episode import EpisodeReader, JsonlEpisodeWriter
from robot_learning.workflows import synchronize_timestamps


class SynchronizationTests(unittest.TestCase):
    def test_matches_nearest_without_reuse(self):
        matches = synchronize_timestamps(
            [100, 110, 200], {"base": [102, 198], "wrist": [101, 202]}, 5
        )
        self.assertEqual([match.anchor_index for match in matches], [0, 2])
        self.assertEqual(matches[1].stream_indices, {"base": 1, "wrist": 1})

    def test_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            synchronize_timestamps([2, 1], {"base": [1]}, 1)
        with self.assertRaises(ValueError):
            synchronize_timestamps([1], {"base": [1, 1]}, 1)
        with self.assertRaises(ValueError):
            synchronize_timestamps([1], {"base": [1]}, -1)


class EpisodeTests(unittest.TestCase):
    def test_round_trip_and_annotation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            state = ArmState("left", 1, (1.0, 2.0), joint_velocities=(0.0, 0.0))
            action = ArmAction("left", 1, (2.0, 3.0), ActionSource.LEADER_COMMAND)
            frame = CameraFrame("base", 1, "raw8", 1, 1, b"\x00")
            with JsonlEpisodeWriter(directory, "synthetic", "synthetic", "rad") as writer:
                writer.append_state(state)
                writer.append_action(action)
                writer.append_frame(frame)
            self.assertEqual(list(EpisodeReader(directory).records()), [state, action, frame])
            annotation = EpisodeAnnotation("tester", (AnnotationSpan(0, 1, "pick"),))
            save_annotation(directory, annotation)
            self.assertEqual(load_annotation(directory), annotation)
            with self.assertRaises(FileExistsError):
                save_annotation(directory, annotation)
            with self.assertRaises(ValueError):
                writer.append_state(state)

    def test_rejects_traversal_and_schema_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            write_sample(directory)
            events = directory / "events.jsonl"
            records = [json.loads(line) for line in events.read_text().splitlines()]
            records[-1]["data"]["file"] = "../escape.bin"
            events.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            with self.assertRaises(ValueError):
                list(EpisodeReader(directory).records())
            metadata = directory / "metadata.json"
            data = json.loads(metadata.read_text())
            data["schema_version"] = 99
            metadata.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                EpisodeReader(directory)

    def test_cli_offline_flow(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            self.assertEqual(main(["sample", str(directory)]), 0)
            self.assertEqual(main(["inspect", str(directory)]), 0)
            self.assertEqual(
                main(["annotate-span", str(directory), "--annotator", "tester", "--start", "0", "--end", "2", "--text", "pick"]),
                0,
            )
            self.assertEqual(load_annotation(directory).spans[0].text, "pick")


if __name__ == "__main__":
    unittest.main()
