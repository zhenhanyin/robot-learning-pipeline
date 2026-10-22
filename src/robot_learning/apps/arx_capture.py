"""Optional read-only ARX ROS2 collection and offline message replay."""

import importlib
import importlib.util
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from typing import Mapping, Optional

from robot_learning.adapters.arx_x5 import ArxRos2Stream
from robot_learning.formats import JsonlEpisodeWriter
from robot_learning.workflows import CollectionSummary, record_buffered_samples
from robot_learning.workflows.motion import NoopStateReader


@dataclass(frozen=True)
class ArxCaptureConfig:
    follower_status_topic: str
    cameras: Mapping[str, str]
    attempts: int
    sample_rate_hz: int
    tolerance_ns: int
    camera_wait_seconds: float
    joint_units: str
    gripper_units: str
    noop_joint_threshold: float = 0.0


def load_arx_config(path: Path) -> ArxCaptureConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "follower_status_topic", "cameras", "attempts", "sample_rate_hz",
        "sync_tolerance_ms", "camera_wait_ms", "joint_units", "gripper_units",
    }
    if not isinstance(data, dict) or set(data) not in (required, required | {"noop_joint_threshold"}):
        raise ValueError("invalid ARX capture config fields")
    threshold = data.get("noop_joint_threshold", 0.0)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not isfinite(threshold) or threshold < 0:
        raise ValueError("noop_joint_threshold must be non-negative and finite")
    cameras = data["cameras"]
    topics = [data["follower_status_topic"]]
    if not isinstance(cameras, dict) or not cameras or any(
        not isinstance(camera_id, str) or not camera_id
        or not isinstance(topic, str) or not topic.startswith("/")
        for camera_id, topic in cameras.items()
    ):
        raise ValueError("cameras must map IDs to absolute ROS2 topics")
    topics.extend(cameras.values())
    if any(not isinstance(topic, str) or not topic.startswith("/") for topic in topics):
        raise ValueError("follower status topic must be absolute")
    if len(set(topics)) != len(topics):
        raise ValueError("ROS2 topics must be distinct")
    for field in ("attempts", "sample_rate_hz"):
        if type(data[field]) is not int or data[field] <= 0:
            raise ValueError(field + " must be positive")
    for field in ("sync_tolerance_ms", "camera_wait_ms"):
        if type(data[field]) is not int or data[field] < 0:
            raise ValueError(field + " must be non-negative")
    for field in ("joint_units", "gripper_units"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError(field + " must be specified")
    return ArxCaptureConfig(
        data["follower_status_topic"], cameras, data["attempts"], data["sample_rate_hz"],
        data["sync_tolerance_ms"] * 1_000_000, data["camera_wait_ms"] / 1000,
        data["joint_units"], data["gripper_units"], float(threshold),
    )


def check_arx_environment() -> Mapping[str, bool]:
    checks = {}
    for module in ("rclpy", "sensor_msgs.msg", "arx5_arm_msg.msg"):
        try:
            checks[module] = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            checks[module] = False
    return checks


def _record(stream: ArxRos2Stream, config: ArxCaptureConfig, destination: Path, attempts: int) -> CollectionSummary:
    with JsonlEpisodeWriter(
        destination, "arx_x5", "ros2_header", config.joint_units, config.gripper_units,
    ) as writer:
        reader = NoopStateReader(stream, config.noop_joint_threshold) if config.noop_joint_threshold else stream
        return record_buffered_samples(
            reader, stream.cameras, writer, attempts, config.tolerance_ns,
            config.camera_wait_seconds,
        )


def capture_arx_ros2(
    config: ArxCaptureConfig, destination: Path, ros: Optional[object] = None,
    image_type: Optional[object] = None, status_type: Optional[object] = None,
) -> CollectionSummary:
    if ros is None:
        ros = importlib.import_module("rclpy")
    if image_type is None:
        image_type = importlib.import_module("sensor_msgs.msg").Image
    if status_type is None:
        status_type = importlib.import_module("arx5_arm_msg.msg").RobotStatus
    stream = ArxRos2Stream(config.cameras, 1 / config.sample_rate_hz)
    ros.init()
    node = None
    stop = Event()
    failures = []
    worker = None
    try:
        node = ros.create_node("robot_learning_arx_capture")
        node.create_subscription(status_type, config.follower_status_topic, stream.receive_status, 10)
        for camera_id, topic in sorted(config.cameras.items()):
            node.create_subscription(
                image_type, topic,
                lambda message, camera_id=camera_id: stream.receive_image(camera_id, message), 10,
            )

        def spin() -> None:
            while not stop.is_set():
                try:
                    ros.spin_once(node, timeout_sec=0.1)
                except Exception as error:
                    failures.append(error)
                    stop.set()

        worker = Thread(target=spin, daemon=True)
        worker.start()
        summary = _record(stream, config, destination, config.attempts)
        if failures:
            raise RuntimeError("ROS2 subscription failed: {}".format(failures[0]))
        return summary
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=1)
        if node is not None:
            node.destroy_node()
        ros.shutdown()


def _namespace(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _namespace(item) for key, item in value.items()})
    return value


def replay_arx_messages(config: ArxCaptureConfig, source: Path, destination: Path) -> CollectionSummary:
    events = []
    with Path(source).open(encoding="utf-8") as source_file:
        for number, line in enumerate(source_file, 1):
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or set(event) != {"topic", "message"} or not isinstance(event["message"], dict):
                    raise ValueError("expected topic and message")
                events.append(event)
            except ValueError as error:
                raise ValueError("message replay line {}: {}".format(number, error)) from error
    camera_topics = {topic: camera_id for camera_id, topic in config.cameras.items()}
    state_count = sum(event["topic"] == config.follower_status_topic for event in events)
    stream = ArxRos2Stream(config.cameras, 0, max(120, len(events)))
    for event in events:
        topic = event["topic"]
        message = _namespace(event["message"])
        if topic == config.follower_status_topic:
            stream.receive_status(message)
        elif topic in camera_topics:
            stream.receive_image(camera_topics[topic], message)
        else:
            raise ValueError("unconfigured ROS2 topic: {}".format(topic))
    if state_count == 0:
        raise ValueError("message replay contains no follower status")
    return _record(stream, config, destination, state_count)
