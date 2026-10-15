"""Offline-only commands for portable episode examples."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Sequence

from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.annotation import AnnotationSpan, EpisodeAnnotation, save_annotation
from robot_learning.formats.episode import EpisodeReader, JsonlEpisodeWriter


def write_sample(directory: Path) -> None:
    with JsonlEpisodeWriter(directory, "synthetic", "synthetic", "rad") as writer:
        for index in range(3):
            timestamp_ns = index * 100_000_000
            writer.append_state(ArmState("left", timestamp_ns, (float(index),)))
            writer.append_action(
                ArmAction("left", timestamp_ns, (float(index + 1),), ActionSource.LEADER_COMMAND)
            )
            writer.append_frame(CameraFrame("base", timestamp_ns, "raw8", 1, 1, bytes([index])))


def main(argv: Sequence[str] = None) -> int:
    parser = argparse.ArgumentParser(prog="robot-learning")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="write a synthetic offline episode")
    sample.add_argument("directory", type=Path)
    inspect = commands.add_parser("inspect", help="summarize an episode")
    inspect.add_argument("directory", type=Path)
    annotate = commands.add_parser("annotate-span", help="save one offline annotation span")
    annotate.add_argument("directory", type=Path)
    annotate.add_argument("--annotator", required=True)
    annotate.add_argument("--start", required=True, type=int)
    annotate.add_argument("--end", required=True, type=int)
    annotate.add_argument("--text", required=True)
    annotate.add_argument("--used-for-vlm", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "sample":
        write_sample(args.directory)
        print(args.directory)
    elif args.command == "inspect":
        episode = EpisodeReader(args.directory)
        counts = Counter(type(record).__name__ for record in episode.records())
        print(json.dumps({"metadata": episode.metadata, "counts": counts}, indent=2))
    else:
        episode = EpisodeReader(args.directory)
        frame_count = sum(isinstance(record, CameraFrame) for record in episode.records())
        if args.end > frame_count:
            parser.error("end index exceeds frame count")
        annotation = EpisodeAnnotation(
            args.annotator,
            (AnnotationSpan(args.start, args.end, args.text, args.used_for_vlm),),
        )
        save_annotation(args.directory, annotation)
        print(args.directory / "annotation.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
