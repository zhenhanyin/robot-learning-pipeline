"""Legacy ARX HDF5 replay, preview first and ROS2 publish only when enabled."""

import importlib
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from time import sleep
from typing import Callable, Optional, Sequence, Tuple

from robot_learning.adapters.arx_x5 import ArxCommandAdapter, map_robot_status, read_legacy_arx_commands
from robot_learning.core.models import ArmState, RobotCommand
from robot_learning.workflows.motion import dispatch_commands, interpolate, is_noop
from robot_learning.workflows.policy_preview import SafetyEnvelope, SafetyStop


@dataclass(frozen=True)
class ArxReplayConfig:
    topic: str
    status_topic: str
    rate_hz: float
    joint_units: str
    gripper_units: str
    envelope: SafetyEnvelope


def load_replay_config(path: Path) -> ArxReplayConfig:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {"topic", "status_topic", "rate_hz", "joint_units", "gripper_units",
                "joint_min", "joint_max", "max_joint_step", "gripper_min", "gripper_max",
                "max_gripper_step", "max_observation_age_ms"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("ARX replay config must specify all command limits and units")
    if not all(isinstance(data[key], str) and data[key].startswith("/") for key in ("topic", "status_topic")):
        raise ValueError("ARX replay topics must be absolute")
    if any(not isinstance(data[key], str) or not data[key].strip() or "unverified" in data[key].lower()
           for key in ("joint_units", "gripper_units")):
        raise ValueError("verified command units must be specified")
    if isinstance(data["rate_hz"], bool) or not isinstance(data["rate_hz"], (int, float)) or not isfinite(data["rate_hz"]) or data["rate_hz"] <= 0:
        raise ValueError("rate_hz must be positive")
    if type(data["max_observation_age_ms"]) is not int or data["max_observation_age_ms"] <= 0:
        raise ValueError("max_observation_age_ms must be positive")
    for key in ("joint_min", "joint_max", "max_joint_step"):
        if not isinstance(data[key], list) or len(data[key]) != 6 or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) for value in data[key]):
            raise ValueError(key + " requires six numeric values")
    for key in ("gripper_min", "gripper_max", "max_gripper_step"):
        if isinstance(data[key], bool) or not isinstance(data[key], (int, float)):
            raise ValueError(key + " must be numeric")
    envelope = SafetyEnvelope(
        "left", tuple(data["joint_min"]), tuple(data["joint_max"]),
        tuple(data["max_joint_step"]), data["max_observation_age_ms"] * 1_000_000,
        1_000_000_000, 1_000_000_000,
        data["gripper_min"], data["gripper_max"], data["max_gripper_step"],
    )
    return ArxReplayConfig(data["topic"], data["status_topic"], float(data["rate_hz"]),
                           data["joint_units"], data["gripper_units"], envelope)


def replay_plan(source: Path, rate_hz: float, noop_threshold: float = 0) -> Tuple[RobotCommand, ...]:
    commands = read_legacy_arx_commands(source, rate_hz)
    if not isfinite(noop_threshold) or noop_threshold < 0:
        raise ValueError("noop threshold must be non-negative")
    if not noop_threshold:
        return commands
    selected = [commands[0]]
    for command in commands[1:]:
        if not is_noop(selected[-1], command, noop_threshold):
            selected.append(command)
    return tuple(selected)


def publish_replay(commands: Sequence[RobotCommand], adapter: ArxCommandAdapter,
                   read_state: Callable[[], ArmState], now_ns: Callable[[], int],
                   envelope: SafetyEnvelope, rate_hz: float, sleep_seconds: Callable[[float], None] = sleep,
                   interpolation_steps: int = 0) -> int:
    if not commands or not isfinite(rate_hz) or rate_hz <= 0:
        raise ValueError("nonempty replay and positive rate are required")
    if type(interpolation_steps) is not int or interpolation_steps < 0:
        raise ValueError("interpolation_steps must be non-negative")
    if interpolation_steps:
        initial = read_state()
        sequence = interpolate(initial, commands[0], interpolation_steps) + tuple(commands[1:])
    else:
        sequence = tuple(commands)
    for index, command in enumerate(sequence):
        state = read_state()
        dispatch_commands(adapter, state, (command,), envelope, now_ns(), enabled=True)
        if index + 1 < len(sequence):
            gap_ns = sequence[index + 1].timestamp_ns - command.timestamp_ns
            sleep_seconds(max(1 / rate_hz, gap_ns / 1_000_000_000))
    return len(sequence)


def publish_arx_ros2(commands: Sequence[RobotCommand], config: ArxReplayConfig,
                     interpolation_steps: int = 0, ros: Optional[object] = None,
                     message_type: Optional[type] = None, status_type: Optional[type] = None) -> int:
    if ros is None:
        ros = importlib.import_module("rclpy")
    if message_type is None or status_type is None:
        module = importlib.import_module("arx5_arm_msg.msg")
        message_type = message_type or module.RobotCmd
        status_type = status_type or module.RobotStatus
    ros.init()
    node = None
    latest = []
    try:
        node = ros.create_node("robot_learning_arx_replay")
        node.create_subscription(status_type, config.status_topic,
                                 lambda message: latest.__setitem__(slice(None), [map_robot_status(message)]), 10)
        adapter = ArxCommandAdapter(node, message_type, config.topic)

        def read_state() -> ArmState:
            latest.clear()
            for _ in range(10):
                ros.spin_once(node, timeout_sec=0.1)
                if latest:
                    return latest[0]
            raise SafetyStop("ARX status not received")

        return publish_replay(commands, adapter, read_state,
                              lambda: node.get_clock().now().nanoseconds,
                              config.envelope, config.rate_hz,
                              interpolation_steps=interpolation_steps)
    finally:
        if node is not None:
            node.destroy_node()
        ros.shutdown()
