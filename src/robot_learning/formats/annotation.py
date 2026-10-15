"""Human annotations remain separate from raw observations."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Tuple


@dataclass(frozen=True)
class AnnotationSpan:
    start_index: int
    end_index: int
    text: str
    used_for_vlm: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.start_index) is not int
            or type(self.end_index) is not int
            or self.start_index < 0
            or self.end_index <= self.start_index
            or not isinstance(self.text, str)
            or not self.text.strip()
            or type(self.used_for_vlm) is not bool
        ):
            raise ValueError("annotation span must be non-empty and ordered")


@dataclass(frozen=True)
class EpisodeAnnotation:
    annotator: str
    spans: Tuple[AnnotationSpan, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.annotator, str) or not self.annotator.strip():
            raise ValueError("annotator is required")


def save_annotation(directory: Path, annotation: EpisodeAnnotation) -> None:
    path = Path(directory) / "annotation.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(asdict(annotation), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def replace_annotation(directory: Path, annotation: EpisodeAnnotation) -> None:
    path = Path(directory) / "annotation.json"
    serialized = json.dumps(asdict(annotation), indent=2, ensure_ascii=False) + "\n"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
            temporary.write(serialized)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_annotation(directory: Path) -> EpisodeAnnotation:
    data = json.loads((Path(directory) / "annotation.json").read_text(encoding="utf-8"))
    return EpisodeAnnotation(data["annotator"], tuple(AnnotationSpan(**span) for span in data["spans"]))
