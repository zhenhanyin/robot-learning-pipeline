import unittest

from robot_learning.core import ActionSource, ArmAction, ArmState, CameraFrame, RobotCommand


class ContractTests(unittest.TestCase):
    def test_state_keeps_single_arm_dimensions(self):
        state = ArmState("left", 100, (0.1, 0.2), joint_velocities=(0.0, 0.0))
        self.assertEqual(len(state.joint_positions), 2)

    def test_velocity_dimension_mismatch_fails(self):
        with self.assertRaises(ValueError):
            ArmState("left", 100, (0.1, 0.2), joint_velocities=(0.0,))

    def test_action_requires_explicit_source(self):
        action = ArmAction("left", 100, (0.1, 0.2), ActionSource.LEADER_COMMAND)
        self.assertEqual(action.source, ActionSource.LEADER_COMMAND)
        with self.assertRaises(ValueError):
            ArmAction("left", 100, (0.1, 0.2), "leader_command")

    def test_camera_frame_rejects_missing_payload(self):
        with self.assertRaises(ValueError):
            CameraFrame("base", 100, "rgb8", 640, 360, b"")

    def test_camera_frame_rejects_invalid_dimensions(self):
        with self.assertRaises(ValueError):
            CameraFrame("base", 100, "rgb8", 0, 360, b"pixels")

    def test_negative_timestamps_are_rejected(self):
        with self.assertRaises(ValueError):
            ArmState("left", -1, (0.1,))
        with self.assertRaises(ValueError):
            ArmAction("left", -1, (0.1,), ActionSource.LEADER_COMMAND)
        with self.assertRaises(ValueError):
            RobotCommand("left", -1, (0.1,))

    def test_empty_joint_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            ArmAction("left", 100, (), ActionSource.LEADER_COMMAND)
        with self.assertRaises(ValueError):
            RobotCommand("left", 100, ())

    def test_robot_command_is_distinct_from_training_action(self):
        action = ArmAction("left", 100, (0.1,), ActionSource.NEXT_STATE)
        command = RobotCommand("left", 100, (0.1,))
        self.assertNotIsInstance(action, RobotCommand)
        self.assertEqual(command.joint_targets, action.joint_targets)


if __name__ == "__main__":
    unittest.main()
