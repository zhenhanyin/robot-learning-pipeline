"""Build local LLaMA-Factory ShareGPT image samples from approved spans."""

import json
from pathlib import Path

from robot_learning.core.models import CameraFrame
from robot_learning.formats.annotation import load_annotation
from robot_learning.formats.episode import EpisodeReader
from robot_learning.formats.images import rgb_array
from robot_learning.formats.validation import validate_episode


def export_vlm(directory: Path, destination: Path, camera_id: str, instruction: str, stride: int = 1) -> int:
    if not isinstance(camera_id, str) or not camera_id:
        raise ValueError("camera_id is required")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("instruction is required")
    if type(stride) is not int or stride <= 0:
        raise ValueError("stride must be positive")
    destination = Path(destination)
    if destination.exists() or not destination.parent.is_dir():
        raise ValueError("VLM destination must not exist and its parent must exist")
    report = validate_episode(directory)
    if not report.valid:
        raise ValueError("invalid episode: {}".format("; ".join(report.errors)))
    annotation = load_annotation(directory)
    frames = [record for record in EpisodeReader(directory).records() if isinstance(record, CameraFrame)]
    examples = []
    selected_frames = []
    for span in annotation.spans:
        if not span.used_for_vlm:
            continue
        matches = [(index, frames[index]) for index in range(span.start_index, span.end_index)
                   if frames[index].camera_id == camera_id]
        for index, frame in matches[::stride]:
            image_array = rgb_array(frame)
            filename = "{:06d}.png".format(len(examples))
            examples.append({
                "messages": [
                    {"role": "user", "content": "<image>\n" + instruction},
                    {"role": "assistant", "content": span.text},
                ],
                "images": ["images/" + filename],
            })
            selected_frames.append((filename, image_array))
    if not examples:
        raise ValueError("no approved VLM frames for the selected camera")
    from PIL import Image

    destination.mkdir()
    (destination / "images").mkdir()
    for filename, image_array in selected_frames:
        Image.fromarray(image_array).save(destination / "images" / filename)
    (destination / "data.json").write_text(json.dumps(examples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dataset_info = {
        "robot_learning_vlm": {
            "file_name": "data.json",
            "formatting": "sharegpt",
            "columns": {"messages": "messages", "images": "images"},
            "tags": {"role_tag": "role", "content_tag": "content", "user_tag": "user", "assistant_tag": "assistant"},
        }
    }
    (destination / "dataset_info.json").write_text(
        json.dumps(dataset_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return len(examples)
