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
