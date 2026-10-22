"""ROS2 RobotCmd publisher with external message classes injected at runtime."""

from math import isfinite

from robot_learning.core.models import RobotCommand


class ArxCommandAdapter:
    def __init__(self, node: object, message_type: type, topic: str = "/arm_cmd",
                 arm_id: str = "left", mode: int = 5):
        if not topic.startswith("/") or not arm_id or type(mode) is not int or mode < 0:
            raise ValueError("absolute topic, arm ID and mode are required")
        self.node = node
        self.message_type = message_type
        self.publisher = node.create_publisher(message_type, topic, 10)
        self.arm_id = arm_id
        self.mode = mode

    def send_command(self, command: RobotCommand) -> None:
        if command.arm_id != self.arm_id or len(command.joint_targets) != 6:
            raise ValueError("ARX command requires the configured arm and six joints")
        if command.gripper_target is None or not all(isfinite(value) for value in
                                                      command.joint_targets + (command.gripper_target,)):
            raise ValueError("ARX command requires finite joints and gripper")
        message = self.message_type()
        message.header.stamp = self.node.get_clock().now().to_msg()
        message.joint_pos = list(command.joint_targets)
        message.gripper = command.gripper_target
        message.mode = self.mode
        self.publisher.publish(message)
