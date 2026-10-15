import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from robot_learning.cli import main, write_sample
from robot_learning.formats.annotation import AnnotationSpan, EpisodeAnnotation, save_annotation
from robot_learning.formats.validation import validate_episode


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "demo"
        write_sample(self.directory)

    def events(self):
        return [json.loads(line) for line in (self.directory / "events.jsonl").read_text().splitlines()]

    def write_events(self, events):
        (self.directory / "events.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
        )

    def test_valid_episode_and_cli(self):
        save_annotation(self.directory, EpisodeAnnotation("tester", (AnnotationSpan(0, 2, "pick"),)))
        report = validate_episode(self.directory)
        self.assertTrue(report.valid)
        self.assertEqual(report.counts, {"state": 3, "action": 3, "frame": 3})
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["validate", str(self.directory)]), 0)
        self.assertEqual(json.loads(output.getvalue())["errors"], [])

    def test_missing_and_unreferenced_frames(self):
        (self.directory / "frames" / "000001.bin").unlink()
        (self.directory / "frames" / "orphan.bin").write_bytes(b"x")
        report = validate_episode(self.directory)
        self.assertFalse(report.valid)
        self.assertTrue(any("missing or symlinked frame" in error for error in report.errors))
        self.assertTrue(any("unreferenced frame file" in error for error in report.errors))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["validate", str(self.directory)]), 1)
        self.assertFalse(json.loads(output.getvalue())["valid"])

    def test_rejects_duplicate_reference_and_timestamp(self):
        events = self.events()
        frames = [event for event in events if event["type"] == "frame"]
        frames[1]["data"]["file"] = frames[0]["data"]["file"]
        frames[1]["data"]["timestamp_ns"] = frames[0]["data"]["timestamp_ns"]
        self.write_events(events)
        report = validate_episode(self.directory)
        self.assertTrue(any("duplicate frame reference" in error for error in report.errors))
        self.assertTrue(any("non-increasing frame timestamp" in error for error in report.errors))

    def test_rejects_bad_schema_and_annotation(self):
        metadata_path = self.directory / "metadata.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["schema_version"] = True
        metadata["gripper_units"] = ""
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        save_annotation(self.directory, EpisodeAnnotation("tester", (AnnotationSpan(2, 4, "outside"),)))
        report = validate_episode(self.directory)
        self.assertTrue(any("schema_version" in error for error in report.errors))
        self.assertTrue(any("gripper_units" in error for error in report.errors))
        self.assertTrue(any("annotation span exceeds frame count" in error for error in report.errors))

    def test_rejects_malformed_record_and_symlink(self):
        events = self.events()
        events[0]["data"]["joint_positions"] = []
        self.write_events(events)
        self.assertTrue(any("episode reader" in error for error in validate_episode(self.directory).errors))
        (self.directory / "frames" / "000000.bin").unlink()
        (self.directory / "frames" / "000000.bin").symlink_to(self.directory / "metadata.json")
        self.assertTrue(any("symlinked frame" in error for error in validate_episode(self.directory).errors))

    def test_rejects_unsafe_paths_and_invalid_json(self):
        events = self.events()
        frames = [event for event in events if event["type"] == "frame"]
        frames[0]["data"]["file"] = "../metadata.json"
        self.write_events(events)
        self.assertTrue(any("unsafe frame filename" in error for error in validate_episode(self.directory).errors))
        (self.directory / "events.jsonl").write_text("not json\n", encoding="utf-8")
        self.assertTrue(any("events.jsonl line 1" in error for error in validate_episode(self.directory).errors))
        alias = self.directory.parent / "alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        self.assertFalse(validate_episode(alias).valid)
        (self.directory / "annotation.json").symlink_to(self.directory / "metadata.json")
        self.assertTrue(any("annotation.json must not be a symlink" in error for error in validate_episode(self.directory).errors))


if __name__ == "__main__":
    unittest.main()
