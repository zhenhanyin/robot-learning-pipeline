import tempfile
import unittest
from pathlib import Path

from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.episode import EpisodeReader, JsonlEpisodeWriter
from robot_learning.workflows import CollectionSummary, record_samples


class StateSource:
    def __init__(self, states):
        self.states = iter(states)

    def read_state(self):
        return next(self.states)

    def send_command(self, command):
        raise AssertionError("collection must never send commands")


class FrameSource:
    def __init__(self, frames):
        self.frames = iter(frames)

    def read_frame(self):
        return next(self.frames)


class ActionSourceReader:
    def __init__(self, actions):
        self.actions = iter(actions)

    def read_action(self):
        return next(self.actions)


def states(*timestamps):
    return [ArmState("left", timestamp, (float(index),)) for index, timestamp in enumerate(timestamps)]


def frames(camera_id, *timestamps):
    return [
        CameraFrame(camera_id, timestamp, "raw8", 1, 1, bytes([index]))
        for index, timestamp in enumerate(timestamps)
    ]


def actions(*timestamps):
    return [ArmAction("left", timestamp, (1.0,), ActionSource.LEADER_COMMAND) for timestamp in timestamps]


class CollectionTests(unittest.TestCase):
    def test_collects_matching_samples_and_drops_out_of_tolerance(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            state_samples = states(100, 200, 300)
            base_frames = frames("base", 102, 250, 302)
            wrist_frames = frames("wrist_left", 99, 201, 301)
            action_samples = actions(101, 201, 301)
            with JsonlEpisodeWriter(directory, "synthetic", "synthetic", "rad") as writer:
                summary = record_samples(
                    StateSource(state_samples),
                    {"wrist_left": FrameSource(wrist_frames), "base": FrameSource(base_frames)},
                    writer,
                    attempts=3,
                    tolerance_ns=5,
                    action_reader=ActionSourceReader(action_samples),
                )
            self.assertEqual(summary, CollectionSummary(attempts=3, written=2, dropped=1))
            self.assertEqual(
                list(EpisodeReader(directory).records()),
                [
                    state_samples[0], action_samples[0], base_frames[0], wrist_frames[0],
                    state_samples[2], action_samples[2], base_frames[2], wrist_frames[2],
                ],
            )

    def test_action_is_optional(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            with JsonlEpisodeWriter(directory, "synthetic", "synthetic", "rad") as writer:
                summary = record_samples(
                    StateSource(states(0)), {"base": FrameSource(frames("base", 0))}, writer, 1, 0
                )
            self.assertEqual(summary.written, 1)
            self.assertEqual(len(list(EpisodeReader(directory).records())), 2)

    def test_rejects_invalid_setup(self):
        reader = StateSource(states(0))
        camera = {"base": FrameSource(frames("base", 0))}
        with self.assertRaises(ValueError):
            record_samples(reader, camera, None, 0, 0)
        with self.assertRaises(ValueError):
            record_samples(reader, camera, None, 1.5, 0)
        with self.assertRaises(ValueError):
            record_samples(reader, camera, None, 1, -1)
        with self.assertRaises(ValueError):
            record_samples(reader, camera, None, 1, 0.5)
        with self.assertRaises(ValueError):
            record_samples(reader, {}, None, 1, 0)

    def test_rejects_mismatched_camera_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            with JsonlEpisodeWriter(directory, "synthetic", "synthetic", "rad") as writer:
                with self.assertRaises(ValueError):
                    record_samples(
                        StateSource(states(0)),
                        {"base": FrameSource(frames("other", 0))},
                        writer,
                        1,
                        0,
                    )
            self.assertEqual(list(EpisodeReader(directory).records()), [])

    def test_rejects_nonmonotonic_and_wrong_arm(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "episode"
            with JsonlEpisodeWriter(directory, "synthetic", "synthetic", "rad") as writer:
                with self.assertRaisesRegex(ValueError, "strictly increasing"):
                    record_samples(
                        StateSource(states(0, 1)),
                        {"base": FrameSource(frames("base", 0, 0))},
                        writer,
                        2,
                        0,
                    )
            self.assertEqual(len(list(EpisodeReader(directory).records())), 2)

            other_directory = Path(temporary) / "wrong_arm"
            with JsonlEpisodeWriter(other_directory, "synthetic", "synthetic", "rad") as writer:
                with self.assertRaisesRegex(ValueError, "action arm_id"):
                    record_samples(
                        StateSource(states(0)),
                        {"base": FrameSource(frames("base", 0))},
                        writer,
                        1,
                        0,
                        ActionSourceReader([ArmAction("right", 0, (1.0,), ActionSource.LEADER_COMMAND)]),
                    )
            self.assertEqual(list(EpisodeReader(other_directory).records()), [])


if __name__ == "__main__":
    unittest.main()
