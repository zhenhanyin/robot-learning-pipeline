import math
import unittest

from robot_learning.core.models import ArmState, CameraFrame
from robot_learning.policies import ModelPolicyClient, PolicySpec
from robot_learning.workflows.policy_preview import OfflinePolicyRunner, SafetyEnvelope, SafetyStop


class FakeModel:
    def __init__(self, result=None):
        self.result = [[0.1], [0.2]] if result is None else result
        self.observation = None

    def get_chunk(self, observation):
        self.observation = observation
        return self.result

    def predict_action(self, observation):
        self.observation = observation
        return self.result

    def infer(self, observation):
        self.observation = observation
        return {"actions": self.result}


class PolicyPreviewTests(unittest.TestCase):
    def setUp(self):
        self.state = ArmState("left", 100, (0.0,))
        self.frames = (CameraFrame("base", 100, "raw8", 1, 1, b"\x00"),)
        self.envelope = SafetyEnvelope("left", (-1.0,), (1.0,), (0.5,), 20, 5, 100)

    def runner(self, model="act", backend=None, clock_ns=None):
        spec = PolicySpec(model, {"head": "base"}, 1, prompt="pick" if model.startswith("pi") else None)
        policy = ModelPolicyClient(spec, backend or FakeModel(), lambda frame: frame.payload)
        return OfflinePolicyRunner(policy, self.envelope, clock_ns or (lambda: 0))

    def test_all_model_shapes_produce_same_candidate_chunk(self):
        for model in ("act", "hrdt", "pi0", "pi0.5"):
            with self.subTest(model=model):
                backend = FakeModel()
                runner = self.runner(model, backend)
                commands = runner.preview(self.state, self.frames, 110)
                self.assertEqual([command.joint_targets for command in commands], [(0.1,), (0.2,)])
                self.assertEqual(commands[0].timestamp_ns, 100)
                self.assertEqual(backend.observation["images"], {"head": b"\x00"})
                self.assertIn("qpos" if model == "act" else "puppet_left" if model == "hrdt" else "state",
                              backend.observation)

    def test_gripper_is_explicit_not_implicitly_sliced(self):
        state = ArmState("left", 100, (0.0,), 0.5)
        spec = PolicySpec("act", {"head": "base"}, 1, gripper_in_action=True)
        policy = ModelPolicyClient(spec, FakeModel([[0.1, 0.6]]), lambda frame: frame.payload)
        limits = SafetyEnvelope("left", (-1.0,), (1.0,), (0.5,), 20, 5, 100, 0.0, 1.0, 0.2)
        self.assertEqual(OfflinePolicyRunner(policy, limits, lambda: 0).preview(state, self.frames, 110)[0].gripper_target, 0.6)
        with self.assertRaises(SafetyStop):
            OfflinePolicyRunner(policy, limits, lambda: 0).preview(self.state, self.frames, 110)

    def test_stale_state_and_skewed_camera_latch_stop(self):
        runner = self.runner()
        with self.assertRaisesRegex(SafetyStop, "stale"):
            runner.preview(self.state, self.frames, 121)
        self.assertTrue(runner.stopped)
        with self.assertRaisesRegex(SafetyStop, "stopped"):
            runner.preview(self.state, self.frames, 110)
        runner = self.runner()
        with self.assertRaisesRegex(SafetyStop, "camera frame"):
            runner.preview(self.state, (CameraFrame("base", 94, "raw8", 1, 1, b"\x00"),), 110)

    def test_mismatched_camera_and_future_state_stop(self):
        with self.assertRaisesRegex(SafetyStop, "camera set"):
            self.runner().preview(self.state, (), 110)
        with self.assertRaisesRegex(SafetyStop, "future"):
            self.runner().preview(self.state, self.frames, 99)

    def test_late_prediction_is_discarded_and_stop_latched(self):
        ticks = iter((0, 101))
        runner = self.runner(clock_ns=lambda: next(ticks))
        with self.assertRaisesRegex(SafetyStop, "deadline"):
            runner.preview(self.state, self.frames, 110)
        self.assertTrue(runner.stopped)

    def test_disconnect_and_explicit_emergency_stop(self):
        class DisconnectedModel:
            def get_chunk(self, observation):
                raise ConnectionError("disconnected")

        runner = self.runner(backend=DisconnectedModel())
        with self.assertRaisesRegex(SafetyStop, "prediction failed"):
            runner.preview(self.state, self.frames, 110)
        self.assertTrue(runner.stopped)
        runner = self.runner()
        runner.emergency_stop()
        with self.assertRaisesRegex(SafetyStop, "stopped"):
            runner.preview(self.state, self.frames, 110)

    def test_timeout_exception_and_stop_during_inference(self):
        class TimeoutModel:
            def get_chunk(self, observation):
                raise TimeoutError("model request timed out")

        with self.assertRaisesRegex(SafetyStop, "prediction failed"):
            self.runner(backend=TimeoutModel()).preview(self.state, self.frames, 110)
        runner = self.runner()

        class StoppingModel:
            def get_chunk(self, observation):
                runner.emergency_stop()
                return [[0.1]]

        runner.policy.backend = StoppingModel()
        with self.assertRaisesRegex(SafetyStop, "stopped"):
            runner.preview(self.state, self.frames, 110)

    def test_missing_encoded_image_and_bad_openpi_response(self):
        spec = PolicySpec("act", {"head": "base"}, 1)
        policy = ModelPolicyClient(spec, FakeModel(), lambda frame: None)
        with self.assertRaisesRegex(SafetyStop, "prediction failed"):
            OfflinePolicyRunner(policy, self.envelope, lambda: 0).preview(self.state, self.frames, 110)

        class BadOpenPI:
            def infer(self, observation):
                return {"action": [[0.1]]}

        with self.assertRaisesRegex(SafetyStop, "prediction failed"):
            self.runner("pi0.5", BadOpenPI()).preview(self.state, self.frames, 110)

    def test_out_of_range_and_large_step_rejected(self):
        for result in ([[1.2]], [[0.6]], [[0.2], [-0.4]]):
            with self.subTest(result=result):
                runner = self.runner(backend=FakeModel(result))
                with self.assertRaisesRegex(SafetyStop, "joint exceeds"):
                    runner.preview(self.state, self.frames, 110)
                self.assertTrue(runner.stopped)

    def test_invalid_model_output_rejected(self):
        for result in ([], [[math.nan]], [[math.inf]], [[0.1, 0.2]], ["bad"], [0.1]):
            with self.subTest(result=result):
                with self.assertRaisesRegex(SafetyStop, "prediction failed"):
                    self.runner(backend=FakeModel(result)).preview(self.state, self.frames, 110)

    def test_oversized_chunk_is_rejected(self):
        runner = self.runner(backend=FakeModel([[0.1]] * 65))
        with self.assertRaisesRegex(SafetyStop, "prediction failed"):
            runner.preview(self.state, self.frames, 110)
        self.assertTrue(runner.stopped)

    def test_invalid_configuration_rejected_before_prediction(self):
        with self.assertRaises(ValueError):
            PolicySpec("pi0", {"head": "base"}, 1)
        with self.assertRaises(ValueError):
            PolicySpec("act", {"head": "base", "wrist": "base"}, 1)
        with self.assertRaises(ValueError):
            PolicySpec("act", {"head": "base"}, 1, max_chunk_steps=0)
        with self.assertRaises(ValueError):
            SafetyEnvelope("left", (1.0,), (-1.0,), (0.5,), 20, 5, 100)
        with self.assertRaises(ValueError):
            SafetyEnvelope("left", (-1.0,), (1.0,), (0.0,), 20, 5, 100)
        with self.assertRaises(ValueError):
            SafetyEnvelope("left", (-1.0,), (1.0,), (0.5,), 0, 5, 100)


if __name__ == "__main__":
    unittest.main()
