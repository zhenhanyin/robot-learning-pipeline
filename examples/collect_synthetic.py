"""Run the read-only collection workflow without any robot hardware."""

import argparse
from pathlib import Path

from robot_learning.core import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats import JsonlEpisodeWriter
from robot_learning.workflows import record_samples


class SyntheticArm:
    def __init__(self):
        self.index = 0

    def read_state(self):
        index = self.index
        self.index += 1
        return ArmState("left", index * 100_000_000, (float(index),))


class SyntheticCamera:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.index = 0

    def read_frame(self):
        index = self.index
        self.index += 1
        timestamp_ns = index * 100_000_000 + 1_000_000
        return CameraFrame(self.camera_id, timestamp_ns, "raw8", 1, 1, bytes([index]))


class SyntheticLeader:
    def __init__(self):
        self.index = 0

    def read_action(self):
        index = self.index
        self.index += 1
        timestamp_ns = index * 100_000_000 + 2_000_000
        return ArmAction("left", timestamp_ns, (float(index + 1),), ActionSource.LEADER_COMMAND)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    with JsonlEpisodeWriter(args.directory, "synthetic", "synthetic", "rad") as writer:
        summary = record_samples(
            SyntheticArm(),
            {"base": SyntheticCamera("base"), "wrist_left": SyntheticCamera("wrist_left")},
            writer,
            attempts=3,
            tolerance_ns=5_000_000,
            action_reader=SyntheticLeader(),
        )
    print(summary)


if __name__ == "__main__":
    main()
