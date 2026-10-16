"""Replay synthetic ROS2-shaped ARX messages without ROS2 or a robot."""

import json
import sys
import tempfile
from pathlib import Path

from robot_learning.apps.arx_capture import load_arx_config, replay_arx_messages


def main() -> None:
    destination = Path(sys.argv[1])
    config = load_arx_config(Path("configs/arx_x5_ros2.json"))
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / "messages.jsonl"
        with source.open("w", encoding="utf-8") as output:
            for index in range(3):
                timestamp = {"sec": 1, "nanosec": index * 100_000_000}
                for camera_id, topic in config.cameras.items():
                    output.write(json.dumps({"topic": topic, "message": {
                        "header": {"stamp": timestamp}, "width": 1, "height": 1,
                        "step": 3, "encoding": "rgb8", "data": [index, 0, 0],
                    }}) + "\n")
                output.write(json.dumps({"topic": config.follower_status_topic, "message": {
                    "header": {"stamp": timestamp}, "joint_pos": [float(index)] * 7,
                    "joint_vel": [0.0] * 7,
                }}) + "\n")
        summary = replay_arx_messages(config, source, destination)
    print(json.dumps({"attempts": summary.attempts, "written": summary.written}))


if __name__ == "__main__":
    main()
