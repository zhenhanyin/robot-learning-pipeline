"""Optional ROS1/Piper process wiring for read-only episode capture."""

import importlib
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Type

from robot_learning.adapters.piper import PiperReadOnlyAdapter
from robot_learning.adapters.ros1 import map_ros1_image
from robot_learning.formats import JsonlEpisodeWriter
from robot_learning.workflows import CollectionSummary, FrameBuffer, record_buffered_samples


CAN_NAME = re.compile(r"[A-Za-z0-9_.-]+\Z")


@dataclass(frozen=True)
class PiperCaptureConfig:
    sdk_class: str
    can_name: str
    cameras: Mapping[str, str]
    attempts: int
    sample_rate_hz: int
    tolerance_ns: int
    camera_wait_seconds: float
    include_action: bool


def load_capture_config(path: Path) -> PiperCaptureConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {
        "sdk_class", "can_name", "cameras", "attempts", "sample_rate_hz",
        "sync_tolerance_ms", "camera_wait_ms", "include_action",
    }:
        raise ValueError("invalid Piper capture config fields")
    sdk_class = data["sdk_class"]
    can_name = data["can_name"]
    cameras = data["cameras"]
    if not isinstance(sdk_class, str) or len(sdk_class.split(":")) != 2 or not all(sdk_class.split(":")):
        raise ValueError("sdk_class must be module:Class")
    if not isinstance(can_name, str) or not CAN_NAME.fullmatch(can_name):
        raise ValueError("invalid can_name")
    if not isinstance(cameras, dict) or not cameras or any(
        not isinstance(camera_id, str) or not camera_id
        or not isinstance(topic, str) or not topic.startswith("/")
        for camera_id, topic in cameras.items()
    ) or len(set(cameras.values())) != len(cameras):
        raise ValueError("cameras must map distinct IDs to distinct absolute ROS topics")
    for field in ("attempts", "sample_rate_hz"):
        if type(data[field]) is not int or data[field] <= 0:
            raise ValueError(field + " must be positive")
    for field in ("sync_tolerance_ms", "camera_wait_ms"):
        if type(data[field]) is not int or data[field] < 0:
            raise ValueError(field + " must be non-negative")
    if type(data["include_action"]) is not bool:
        raise ValueError("include_action must be boolean")
    return PiperCaptureConfig(
        sdk_class, can_name, cameras, data["attempts"], data["sample_rate_hz"],
        data["sync_tolerance_ms"] * 1_000_000, data["camera_wait_ms"] / 1000,
        data["include_action"],
    )


def check_capture_environment(config: PiperCaptureConfig) -> Mapping[str, bool]:
    module_name = config.sdk_class.split(":", 1)[0]
    checks = {}
    for name, module in (("piper_sdk", module_name), ("rospy", "rospy"), ("sensor_msgs", "sensor_msgs.msg")):
        try:
            checks[name] = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            checks[name] = False
    checks["can_interface"] = (Path("/sys/class/net") / config.can_name).exists()
    return checks


def capture_piper_ros1(
    config: PiperCaptureConfig,
    destination: Path,
    ros: Optional[object] = None,
    image_type: Optional[object] = None,
    sdk_type: Optional[Type[object]] = None,
) -> CollectionSummary:
    if ros is None:
        ros = importlib.import_module("rospy")
    if image_type is None:
        image_type = importlib.import_module("sensor_msgs.msg").Image
    if sdk_type is None:
        module_name, class_name = config.sdk_class.split(":", 1)
        sdk_type = getattr(importlib.import_module(module_name), class_name)
    ros.init_node("robot_learning_piper_capture", anonymous=True)
    buffers = {camera_id: FrameBuffer(camera_id) for camera_id in config.cameras}
    subscribers = []
    sdk = None
    try:
        for camera_id, topic in sorted(config.cameras.items()):
            buffer = buffers[camera_id]

            def receive(message: object, camera_id: str = camera_id, buffer: FrameBuffer = buffer) -> None:
                buffer.add(map_ros1_image(camera_id, message))

            subscribers.append(ros.Subscriber(topic, image_type, receive, queue_size=1))
        sdk = sdk_type(can_name=config.can_name)
        sdk.ConnectPort()
        reader = PiperReadOnlyAdapter(sdk)
        rate = ros.Rate(config.sample_rate_hz)
        with JsonlEpisodeWriter(
            destination, "piper", "legacy_piper_epoch_assumed",
            "piper_raw_joint_tick", "piper_raw_gripper_tick",
        ) as writer:
            return record_buffered_samples(
                reader, buffers, writer, config.attempts, config.tolerance_ns,
                config.camera_wait_seconds, reader if config.include_action else None,
                pace=rate.sleep,
            )
    finally:
        for subscriber in subscribers:
            subscriber.unregister()
        if sdk is not None and hasattr(sdk, "running"):
            sdk.running = False
