"""Append-only JSONL records with image bytes stored separately."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterator, Mapping, Optional, Union

from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame


Record = Union[ArmState, ArmAction, CameraFrame]
SCHEMA_VERSION = 1


class JsonlEpisodeWriter:
    def __init__(
        self, directory: Path, robot_model: str, clock_domain: str, joint_units: str,
        gripper_units: Optional[str] = None, extra_metadata: Optional[Mapping[str, object]] = None,
    ) -> None:
        if not robot_model or not clock_domain or not joint_units:
            raise ValueError("robot_model, clock_domain and joint_units are required")
        if gripper_units is not None and (not isinstance(gripper_units, str) or not gripper_units):
            raise ValueError("gripper_units must be non-empty when provided")
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "robot_model": robot_model,
            "clock_domain": clock_domain,
            "joint_units": joint_units,
        }
        if gripper_units is not None:
            metadata["gripper_units"] = gripper_units
        if extra_metadata is not None:
            if any(not isinstance(key, str) or not key or key in metadata for key in extra_metadata):
                raise ValueError("extra metadata keys must be non-empty and not reserved")
            metadata.update(extra_metadata)
        serialized_metadata = json.dumps(metadata, indent=2, allow_nan=False) + "\n"
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        (self.directory / "frames").mkdir()
        (self.directory / "metadata.json").write_text(
            serialized_metadata, encoding="utf-8"
        )
        self._events = (self.directory / "events.jsonl").open("w", encoding="utf-8")
        self._frame_count = 0
        self._closed = False

    def _append(self, kind: str, record: Record) -> None:
        if self._closed:
            raise ValueError("episode writer is closed")
        data = asdict(record)
        if isinstance(record, ArmAction):
            data["source"] = record.source.value
        if isinstance(record, CameraFrame):
            filename = "{:06d}.bin".format(self._frame_count)
            (self.directory / "frames" / filename).write_bytes(record.payload)
            self._frame_count += 1
            del data["payload"]
            data["file"] = filename
        self._events.write(json.dumps({"type": kind, "data": data}) + "\n")
        self._events.flush()

    def append_state(self, state: ArmState) -> None:
        self._append("state", state)

    def append_action(self, action: ArmAction) -> None:
        self._append("action", action)

    def append_frame(self, frame: CameraFrame) -> None:
        self._append("frame", frame)

    def close(self) -> None:
        if not self._closed:
            self._events.close()
            self._closed = True

    def __enter__(self) -> "JsonlEpisodeWriter":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


class EpisodeReader:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.metadata: Dict[str, object] = json.loads(
            (self.directory / "metadata.json").read_text(encoding="utf-8")
        )
        if self.metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported episode schema_version")

    def records(self) -> Iterator[Record]:
        with (self.directory / "events.jsonl").open(encoding="utf-8") as events:
            for line in events:
                event = json.loads(line)
                data = event["data"]
                if event["type"] == "state":
                    data["joint_positions"] = tuple(data["joint_positions"])
                    if data["joint_velocities"] is not None:
                        data["joint_velocities"] = tuple(data["joint_velocities"])
                    if data.get("end_effector_pose") is not None:
                        data["end_effector_pose"] = tuple(data["end_effector_pose"])
                    yield ArmState(**data)
                elif event["type"] == "action":
                    data["source"] = ActionSource(data["source"])
                    data["joint_targets"] = tuple(data["joint_targets"])
                    yield ArmAction(**data)
                elif event["type"] == "frame":
                    filename = data.pop("file")
                    if Path(filename).name != filename or not filename.endswith(".bin"):
                        raise ValueError("unsafe frame filename")
                    data["payload"] = (self.directory / "frames" / filename).read_bytes()
                    for name in ("intrinsic_cv", "extrinsic_cv", "cam2world_gl"):
                        if data.get(name) is not None:
                            data[name] = tuple(data[name])
                    yield CameraFrame(**data)
                else:
                    raise ValueError("unknown record type")
