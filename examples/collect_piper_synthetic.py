"""Exercise the Piper/ROS1 capture path without SDK, ROS, or hardware."""

import argparse
from pathlib import Path
from types import SimpleNamespace

from robot_learning.apps.piper_capture import PiperCaptureConfig, capture_piper_ros1
from robot_learning.formats.validation import validate_episode


START_NS = 1_000_000_000_000
PERIOD_NS = 100_000_000


def joints(value):
    return SimpleNamespace(**{"joint_{}".format(index): value for index in range(1, 7)})


def image(timestamp_ns):
    return SimpleNamespace(
        width=1, height=1, step=3, encoding="rgb8", data=b"\xff\x00\x00", is_bigendian=0,
        header=SimpleNamespace(stamp=SimpleNamespace(to_nsec=lambda: timestamp_ns)),
    )


class FakePiper:
    def __init__(self, can_name):
        self.can_name = can_name
        self.index = 0
        self.running = False

    def ConnectPort(self):
        self.running = True

    def timestamp_ns(self):
        return START_NS + self.index * PERIOD_NS

    def GetArmJointMsgs(self):
        return SimpleNamespace(time_stamp=self.timestamp_ns() / 1_000_000_000, joint_state=joints(self.index))

    def GetArmGripperMsgs(self):
        return SimpleNamespace(
            time_stamp=self.timestamp_ns(), gripper_state=SimpleNamespace(grippers_angle=self.index),
        )

    def GetArmJointCtrl(self):
        return SimpleNamespace(time_stamp=self.timestamp_ns() / 1_000_000_000, joint_ctrl=joints(self.index + 1))

    def GetArmGripperCtrl(self):
        result = SimpleNamespace(
            time_stamp=self.timestamp_ns(), gripper_ctrl=SimpleNamespace(grippers_angle=self.index + 1),
        )
        self.index += 1
        return result


class FakeSubscriber:
    def unregister(self):
        pass


class FakeRate:
    def sleep(self):
        pass


class FakeRos:
    def init_node(self, name, anonymous):
        pass

    def Subscriber(self, topic, image_type, callback, queue_size):
        for index in range(3):
            callback(image(START_NS + index * PERIOD_NS + 1_000_000))
        return FakeSubscriber()

    def Rate(self, sample_rate_hz):
        return FakeRate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    config = PiperCaptureConfig(
        "fake:FakePiper", "can0", {"base": "/base", "wrist_left": "/wrist"},
        3, 30, 5_000_000, 0.0, True,
    )
    summary = capture_piper_ros1(config, args.directory, ros=FakeRos(), image_type=object, sdk_type=FakePiper)
    report = validate_episode(args.directory)
    if not report.valid or summary.written != 3:
        raise RuntimeError("synthetic Piper capture failed")
    print(summary)


if __name__ == "__main__":
    main()
