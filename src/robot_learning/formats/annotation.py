"""Human annotations remain separate from raw observations."""

import json
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
        if self.start_index < 0 or self.end_index <= self.start_index or not self.text.strip():
            raise ValueError("annotation span must be non-empty and ordered")


@dataclass(frozen=True)
class EpisodeAnnotation:
    annotator: str
    spans: Tuple[AnnotationSpan, ...]

    def __post_init__(self) -> None:
        if not self.annotator.strip():
            raise ValueError("annotator is required")


def save_annotation(directory: Path, annotation: EpisodeAnnotation) -> None:
    path = Path(directory) / "annotation.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(asdict(annotation), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_annotation(directory: Path) -> EpisodeAnnotation:
    data = json.loads((Path(directory) / "annotation.json").read_text(encoding="utf-8"))
    return EpisodeAnnotation(data["annotator"], tuple(AnnotationSpan(**span) for span in data["spans"]))
