"""Offline-only commands for portable episode examples."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.annotation import AnnotationSpan, EpisodeAnnotation, save_annotation
from robot_learning.formats.episode import EpisodeReader, JsonlEpisodeWriter
from robot_learning.formats.validation import validate_episode


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
    validate = commands.add_parser("validate", help="check offline episode integrity")
    validate.add_argument("directory", type=Path)
    import_piper = commands.add_parser("import-piper-legacy", help="import a legacy Piper recording offline")
    import_piper.add_argument("source", type=Path)
    import_piper.add_argument("destination", type=Path)
    import_piper.add_argument("--tolerance-ms", type=int, default=30)
    doctor_piper = commands.add_parser("doctor-piper", help="check Piper capture dependencies without connecting")
    doctor_piper.add_argument("--config", required=True, type=Path)
    collect_piper = commands.add_parser("collect-piper", help="record Piper CAN and ROS1 streams")
    collect_piper.add_argument("--config", required=True, type=Path)
    collect_piper.add_argument("directory", type=Path)
    doctor_arx = commands.add_parser("doctor-arx", help="check optional ARX ROS2 dependencies")
    doctor_arx.add_argument("--config", required=True, type=Path)
    collect_arx = commands.add_parser("collect-arx", help="record read-only ARX ROS2 streams")
    collect_arx.add_argument("--config", required=True, type=Path)
    collect_arx.add_argument("directory", type=Path)
    replay_arx = commands.add_parser("replay-arx-messages", help="replay ROS2 message fixture into an episode offline")
    replay_arx.add_argument("--config", required=True, type=Path)
    replay_arx.add_argument("source", type=Path)
    replay_arx.add_argument("directory", type=Path)
    preview_arx = commands.add_parser("preview-arx", help="inspect ARX episode timeline without robot commands")
    preview_arx.add_argument("directory", type=Path)
    export = commands.add_parser("export", help="export validated episode training data")
    export.add_argument("source", type=Path)
    export.add_argument("destination", type=Path)
    export.add_argument("--format", choices=("hdf5", "lerobot"), required=True)
    export.add_argument("--action-policy", choices=("recorded", "next-state"), default="recorded")
    export.add_argument("--tolerance-ms", type=int, default=30)
    export.add_argument("--fps", type=int)
    export.add_argument("--repo-id")
    export.add_argument("--task")
    build_vlm = commands.add_parser("build-vlm", help="build annotated LLaMA-Factory image dataset")
    build_vlm.add_argument("source", type=Path)
    build_vlm.add_argument("destination", type=Path)
    build_vlm.add_argument("--camera", required=True)
    build_vlm.add_argument("--instruction", required=True)
    build_vlm.add_argument("--stride", type=int, default=1)
    annotate = commands.add_parser("annotate-span", help="save one offline annotation span")
    annotate.add_argument("directory", type=Path)
    annotate.add_argument("--annotator", required=True)
    annotate.add_argument("--start", required=True, type=int)
    annotate.add_argument("--end", required=True, type=int)
    annotate.add_argument("--text", required=True)
    annotate.add_argument("--used-for-vlm", action="store_true")
    annotate_web = commands.add_parser("annotate", help="serve the local offline annotator")
    annotate_web.add_argument("--data-root", required=True, type=Path)
    annotate_web.add_argument("--port", type=int, default=8765)
    task_demo = commands.add_parser("task-demo", help="serve the synthetic offline task dashboard")
    task_demo.add_argument("--port", type=int, default=8766)
    control_web = commands.add_parser("control-web", help="serve the Piper ROS1 control API on loopback")
    control_web.add_argument("--port", type=int, default=8767)
    replay_hdf5 = commands.add_parser("replay-arx-hdf5", help="preview or explicitly publish legacy ARX HDF5 commands")
    replay_hdf5.add_argument("source", type=Path)
    replay_hdf5.add_argument("--rate", type=float, default=30)
    replay_hdf5.add_argument("--noop-threshold", type=float, default=0)
    replay_hdf5.add_argument("--publish", action="store_true")
    replay_hdf5.add_argument("--limits", type=Path)
    replay_hdf5.add_argument("--interpolation-steps", type=int, default=0)
    import_arx = commands.add_parser("import-arx-legacy", help="import legacy ARX HDF5 states, poses, images, and calibration")
    import_arx.add_argument("source", type=Path)
    import_arx.add_argument("directory", type=Path)
    import_arx.add_argument("--rate", type=float, required=True)
    import_arx.add_argument("--cameras", nargs="+")
    action_stats = commands.add_parser("action-stats", help="calculate action statistics from HDF5")
    action_stats.add_argument("source", type=Path)
    smooth_gripper = commands.add_parser("smooth-gripper-hdf5", help="write a smoothed HDF5 copy")
    smooth_gripper.add_argument("source", type=Path)
    smooth_gripper.add_argument("destination", type=Path)
    smooth_gripper.add_argument("--window-size", type=int, default=5)
    smooth_gripper.add_argument("--threshold-ratio", type=float, default=0.05)
    smooth_gripper.add_argument("--min-stable-frames", type=int, default=5)
    preprocess_video = commands.add_parser("preprocess-video", help="attach uniformly sampled MP4 frames to an HDF5 copy")
    preprocess_video.add_argument("video", type=Path)
    preprocess_video.add_argument("source", type=Path)
    preprocess_video.add_argument("destination", type=Path)
    preprocess_video.add_argument("--camera", required=True)
    preprocess_video.add_argument("--jpeg-quality", type=int, default=95)
    policy_manifest = commands.add_parser("validate-policy-manifest", help="validate external checkpoint and policy mappings")
    policy_manifest.add_argument("manifest", type=Path)
    policy_manifest.add_argument("--training-plan", type=Path)
    training_plan = commands.add_parser("validate-training-plan", help="validate framework-neutral model training configuration")
    training_plan.add_argument("plan", type=Path)
    training_plan.add_argument("--check-paths", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "sample":
        write_sample(args.directory)
        print(args.directory)
    elif args.command == "inspect":
        episode = EpisodeReader(args.directory)
        counts = Counter(type(record).__name__ for record in episode.records())
        print(json.dumps({"metadata": episode.metadata, "counts": counts}, indent=2))
    elif args.command == "validate":
        report = validate_episode(args.directory)
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return 0 if report.valid else 1
    elif args.command == "import-piper-legacy":
        from dataclasses import asdict

        from robot_learning.adapters.piper import import_legacy_run

        if args.tolerance_ms < 0:
            parser.error("tolerance-ms must be non-negative")
        summary = import_legacy_run(args.source, args.destination, args.tolerance_ms * 1_000_000)
        print(json.dumps(asdict(summary), indent=2))
    elif args.command == "action-stats":
        from robot_learning.formats.preprocessing import hdf5_action_statistics

        try:
            print(json.dumps(hdf5_action_statistics(args.source).to_dict(), indent=2))
        except (OSError, ValueError, ImportError, KeyError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command == "smooth-gripper-hdf5":
        from robot_learning.formats.preprocessing import smooth_hdf5_grippers

        try:
            changed = smooth_hdf5_grippers(args.source, args.destination, args.window_size,
                                           args.threshold_ratio, args.min_stable_frames)
            print(json.dumps({"datasets_smoothed": changed, "destination": str(args.destination)}))
        except (OSError, ValueError, ImportError, KeyError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command == "preprocess-video":
        from robot_learning.formats.video import preprocess_video

        try:
            count = preprocess_video(args.video, args.source, args.destination,
                                     args.camera, args.jpeg_quality)
            print(json.dumps({"camera": args.camera, "frames": count,
                              "destination": str(args.destination)}))
        except (OSError, ValueError, ImportError, KeyError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command == "validate-policy-manifest":
        from robot_learning.policies.manifest import PolicyManifest

        try:
            manifest = PolicyManifest.load(args.manifest)
            if args.training_plan:
                from robot_learning.formats.training_plan import TrainingPlan

                manifest.validate_training_plan(TrainingPlan.load(args.training_plan))
            print(json.dumps({"valid": True, "model": manifest.model,
                              "joint_count": len(manifest.joint_names),
                              "action_dimension": len(manifest.joint_names) + int(manifest.gripper_in_action),
                              "cameras": sorted(manifest.camera_map),
                              "checkpoint_env_required": manifest.checkpoint_env}, ensure_ascii=False))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command == "validate-training-plan":
        from robot_learning.formats.training_plan import TrainingPlan

        try:
            plan = TrainingPlan.load(args.plan)
            if args.check_paths:
                plan.validate_paths(args.plan.parent)
            print(json.dumps({"valid": True, "model": plan.model,
                              "dataset_format": plan.dataset_format,
                              "paths_checked": args.check_paths}, ensure_ascii=False))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            print(json.dumps({"valid": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command in ("doctor-piper", "collect-piper"):
        from dataclasses import asdict

        from robot_learning.apps.piper_capture import (
            capture_piper_ros1, check_capture_environment, load_capture_config,
        )

        try:
            config = load_capture_config(args.config)
            if args.command == "doctor-piper":
                checks = check_capture_environment(config)
                print(json.dumps(checks, indent=2))
                return 0 if all(checks.values()) else 1
            summary = capture_piper_ros1(config, args.directory)
            print(json.dumps(asdict(summary), indent=2))
            return 0 if summary.written else 1
        except (OSError, ValueError, ImportError, AttributeError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command in ("doctor-arx", "collect-arx", "replay-arx-messages"):
        from dataclasses import asdict

        from robot_learning.apps.arx_capture import (
            capture_arx_ros2, check_arx_environment, load_arx_config, replay_arx_messages,
        )

        try:
            config = load_arx_config(args.config)
            if args.command == "doctor-arx":
                checks = check_arx_environment()
                print(json.dumps(checks, indent=2))
                return 0 if all(checks.values()) else 1
            if args.command == "collect-arx":
                summary = capture_arx_ros2(config, args.directory)
            else:
                summary = replay_arx_messages(config, args.source, args.directory)
            print(json.dumps(asdict(summary), indent=2))
            return 0 if summary.written else 1
        except (OSError, ValueError, ImportError, AttributeError, RuntimeError, KeyError, TypeError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command == "preview-arx":
        report = validate_episode(args.directory)
        if not report.valid:
            print(json.dumps(report.to_dict(), ensure_ascii=False), file=sys.stderr)
            return 1
        episode = EpisodeReader(args.directory)
        if episode.metadata["robot_model"] != "arx_x5":
            print(json.dumps({"error": "not an ARX X5 episode"}), file=sys.stderr)
            return 2
        timeline = [
            {"timestamp_ns": record.timestamp_ns, "joints": len(record.joint_positions), "gripper": record.gripper_position}
            for record in episode.records() if isinstance(record, ArmState)
        ]
        print(json.dumps({"robot_model": "arx_x5", "joint_units": episode.metadata["joint_units"],
                          "gripper_units": episode.metadata.get("gripper_units"), "states": timeline,
                          "command_published": False}, indent=2))
    elif args.command == "export":
        from robot_learning.formats.training import load_training_episode

        try:
            episode = load_training_episode(args.source, args.action_policy, args.tolerance_ms * 1_000_000)
            if args.format == "hdf5":
                from robot_learning.formats.hdf5 import export_hdf5

                count = export_hdf5(episode, args.destination)
            else:
                from robot_learning.formats.lerobot import export_lerobot

                if args.fps is None or args.repo_id is None or args.task is None:
                    parser.error("LeRobot export requires --fps, --repo-id and --task")
                count = export_lerobot(episode, args.destination, args.repo_id, args.fps, args.task)
            print(json.dumps({"format": args.format, "samples": count, "action_source": episode.action_source.value}))
        except (OSError, ValueError, ImportError, KeyError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command == "build-vlm":
        from robot_learning.formats.vlm import export_vlm

        try:
            count = export_vlm(args.source, args.destination, args.camera, args.instruction, args.stride)
            print(json.dumps({"format": "llamafactory_sharegpt", "samples": count}))
        except (OSError, ValueError, ImportError, KeyError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command == "annotate":
        from robot_learning.apps.annotator import serve

        if not 0 <= args.port <= 65535:
            parser.error("port must be between 0 and 65535")
        serve(args.data_root, args.port)
    elif args.command == "task-demo":
        from robot_learning.apps.task_demo import serve

        if not 0 <= args.port <= 65535:
            parser.error("port must be between 0 and 65535")
        serve(args.port)
    elif args.command == "control-web":
        from robot_learning.apps.control_web import serve

        if not 0 <= args.port <= 65535:
            parser.error("port must be between 0 and 65535")
        serve(args.port)
    elif args.command == "replay-arx-hdf5":
        from robot_learning.apps.arx_replay import (
            load_replay_config, publish_arx_ros2, replay_plan,
        )

        try:
            if args.interpolation_steps < 0:
                parser.error("interpolation-steps must be non-negative")
            if args.publish and args.limits is None:
                parser.error("--publish requires --limits with verified units and bounds")
            config = load_replay_config(args.limits) if args.publish else None
            rate = config.rate_hz if config else args.rate
            commands = replay_plan(args.source, rate, args.noop_threshold)
            published = publish_arx_ros2(commands, config, args.interpolation_steps) if config else 0
            print(json.dumps({"selected_frames": len(commands), "published": published,
                              "joint_units": config.joint_units if config else "source_unverified",
                              "gripper_units": config.gripper_units if config else "source_unverified"}))
        except (OSError, ValueError, ImportError, RuntimeError, KeyError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
    elif args.command == "import-arx-legacy":
        from robot_learning.adapters.arx_x5 import import_legacy_arx_episode

        try:
            count = import_legacy_arx_episode(args.source, args.directory, args.rate,
                                              tuple(args.cameras))
            print(json.dumps({"states": count, "cameras": args.cameras,
                              "action_source": "not_recorded"}))
        except (OSError, ValueError, ImportError, KeyError) as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
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
