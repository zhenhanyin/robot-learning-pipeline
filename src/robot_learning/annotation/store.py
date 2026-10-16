"""Validated access to local episode annotations."""

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

from robot_learning.formats.annotation import (
    AnnotationSpan,
    EpisodeAnnotation,
    load_annotation,
    replace_annotation,
)
from robot_learning.formats.episode import EpisodeReader
from robot_learning.core.models import CameraFrame


EPISODE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class AnnotationStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root).resolve(strict=True)
        if not self.data_root.is_dir():
            raise ValueError("data_root must be a directory")

    def _directory(self, name: str) -> Path:
        if not isinstance(name, str) or not EPISODE_NAME.fullmatch(name):
            raise ValueError("invalid episode name")
        if (self.data_root / name).is_symlink():
            raise ValueError("episode directory must not be a symlink")
        directory = (self.data_root / name).resolve(strict=True)
        if directory.parent != self.data_root or not directory.is_dir():
            raise ValueError("episode must be a direct child of data_root")
        return directory

    def _file(self, directory: Path, filename: str, required: bool = True) -> Path:
        path = directory / filename
        if path.is_symlink() or (required and not path.is_file()):
            raise ValueError("episode file must be a regular file")
        return path

    def list_episodes(self) -> List[str]:
        return sorted(
            child.name
            for child in self.data_root.iterdir()
            if child.is_dir()
            and not child.is_symlink()
            and EPISODE_NAME.fullmatch(child.name)
            and (child / "metadata.json").is_file()
            and not (child / "metadata.json").is_symlink()
        )

    def get_episode(self, name: str) -> Dict[str, object]:
        directory = self._directory(name)
        self._file(directory, "metadata.json")
        self._file(directory, "events.jsonl")
        annotation_path = self._file(directory, "annotation.json", required=False)
        metadata = EpisodeReader(directory).metadata
        with (directory / "events.jsonl").open(encoding="utf-8") as events:
            frame_count = sum(json.loads(line).get("type") == "frame" for line in events)
        annotation = asdict(load_annotation(directory)) if annotation_path.exists() else None
        return {"name": name, "metadata": metadata, "frame_count": frame_count, "annotation": annotation}

    def set_annotation(self, name: str, data: object) -> Dict[str, object]:
        if not isinstance(data, dict) or not isinstance(data.get("spans"), list):
            raise ValueError("annotation must contain a spans list")
        directory = self._directory(name)
        frame_count = self.get_episode(name)["frame_count"]
        if any(not isinstance(span, dict) for span in data["spans"]):
            raise ValueError("each annotation span must be an object")
        spans = tuple(AnnotationSpan(**span) for span in data["spans"])
        if any(span.end_index > frame_count for span in spans):
            raise ValueError("annotation span exceeds frame count")
        annotation = EpisodeAnnotation(data.get("annotator"), spans)
        replace_annotation(directory, annotation)
        return asdict(annotation)

    def get_frame(self, name: str, index: int) -> CameraFrame:
        if type(index) is not int or index < 0:
            raise ValueError("frame index must be non-negative")
        directory = self._directory(name)
        events_path = self._file(directory, "events.jsonl")
        frame_data = None
        with events_path.open(encoding="utf-8") as events:
            for line in events:
                event = json.loads(line)
                if event.get("type") == "frame":
                    if index == 0:
                        frame_data = event["data"]
                        break
                    index -= 1
        if frame_data is None:
            raise ValueError("frame index exceeds frame count")
        filename = frame_data.get("file")
        if not isinstance(filename, str) or not re.fullmatch(r"[0-9]{6}\.bin", filename):
            raise ValueError("unsafe frame filename")
        frames_directory = directory / "frames"
        if frames_directory.is_symlink() or not frames_directory.is_dir():
            raise ValueError("frames directory must be regular")
        frame_path = self._file(frames_directory, filename)
        if frame_path.stat().st_size > 32_000_000:
            raise ValueError("preview exceeds size limit")
        return CameraFrame(
            frame_data["camera_id"], frame_data["timestamp_ns"], frame_data["encoding"],
            frame_data["width"], frame_data["height"], frame_path.read_bytes(),
        )
