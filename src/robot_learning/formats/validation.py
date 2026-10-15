"""Read-only integrity checks for offline episodes."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from robot_learning.core.models import ArmAction, ArmState, CameraFrame
from robot_learning.formats.annotation import load_annotation
from robot_learning.formats.episode import EpisodeReader, SCHEMA_VERSION


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    counts: Dict[str, int]
    errors: Tuple[str, ...]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def validate_episode(directory: Path) -> ValidationReport:
    directory = Path(directory)
    counts = {"state": 0, "action": 0, "frame": 0}
    errors: List[str] = []
    if directory.is_symlink() or not directory.is_dir():
        return ValidationReport(False, counts, ("episode must be a regular directory",))

    metadata_path = directory / "metadata.json"
    events_path = directory / "events.jsonl"
    frames_path = directory / "frames"
    for path in (metadata_path, events_path):
        if path.is_symlink() or not path.is_file():
            errors.append("{} must be a regular file".format(path.name))
    if frames_path.is_symlink() or not frames_path.is_dir():
        errors.append("frames must be a regular directory")
    if errors:
        return ValidationReport(False, counts, tuple(errors))

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or type(metadata.get("schema_version")) is not int or metadata["schema_version"] != SCHEMA_VERSION:
            errors.append("unsupported or missing schema_version")
        else:
            for key in ("robot_model", "clock_domain", "joint_units"):
                if not isinstance(metadata.get(key), str) or not metadata[key].strip():
                    errors.append("metadata.{} must be a non-empty string".format(key))
    except (OSError, UnicodeError, ValueError) as error:
        errors.append("metadata.json: {}".format(error))

    referenced_frames = set()
    timestamps: Dict[Tuple[str, str], int] = {}
    try:
        with events_path.open(encoding="utf-8") as events:
            for number, line in enumerate(events, start=1):
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict) or event.get("type") not in counts or not isinstance(event.get("data"), dict):
                        raise ValueError("expected an event with type and data")
                    kind = event["type"]
                    data = event["data"]
                    counts[kind] += 1
                    timestamp = data.get("timestamp_ns")
                    identity = data.get("camera_id" if kind == "frame" else "arm_id")
                    if type(timestamp) is not int or timestamp < 0 or not isinstance(identity, str) or not identity:
                        raise ValueError("invalid timestamp or stream identifier")
                    stream = (kind, identity)
                    if stream in timestamps and timestamp <= timestamps[stream]:
                        errors.append("events.jsonl line {}: non-increasing {} timestamp".format(number, kind))
                    timestamps[stream] = timestamp
                    if kind == "frame":
                        filename = data.get("file")
                        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".bin") or filename in (".", ".."):
                            raise ValueError("unsafe frame filename")
                        if filename in referenced_frames:
                            errors.append("events.jsonl line {}: duplicate frame reference {}".format(number, filename))
                        referenced_frames.add(filename)
                        frame_path = frames_path / filename
                        if frame_path.is_symlink() or not frame_path.is_file():
                            errors.append("events.jsonl line {}: missing or symlinked frame {}".format(number, filename))
                        elif frame_path.stat().st_size == 0:
                            errors.append("events.jsonl line {}: empty frame {}".format(number, filename))
                except (OSError, ValueError, TypeError) as error:
                    errors.append("events.jsonl line {}: {}".format(number, error))
    except (OSError, UnicodeError) as error:
        errors.append("events.jsonl: {}".format(error))

    try:
        for path in frames_path.iterdir():
            if path.name not in referenced_frames:
                errors.append("unreferenced frame file: {}".format(path.name))
    except OSError as error:
        errors.append("frames: {}".format(error))

    annotation_path = directory / "annotation.json"
    if annotation_path.is_symlink():
        errors.append("annotation.json must not be a symlink")
    elif annotation_path.exists():
        try:
            annotation = load_annotation(directory)
            if any(span.end_index > counts["frame"] for span in annotation.spans):
                errors.append("annotation span exceeds frame count")
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
            errors.append("annotation.json: {}".format(error))

    if not errors:
        try:
            for record in EpisodeReader(directory).records():
                if not isinstance(record, (ArmState, ArmAction, CameraFrame)):
                    errors.append("unsupported record")
        except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
            errors.append("episode reader: {}".format(error))
    return ValidationReport(not errors, counts, tuple(errors))
