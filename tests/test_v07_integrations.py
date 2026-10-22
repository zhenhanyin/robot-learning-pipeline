import base64
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from robot_learning.core.models import ArmState, CameraFrame
from robot_learning.formats.training_plan import TrainingPlan
from robot_learning.integrations.http_services import (
    HttpPolicyBackend,
    SpeechToTextHttpClient,
    VisionTaskHttpClient,
    _validate_endpoint,
)
from robot_learning.policies.manifest import AffineTransform, PolicyManifest


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def post(self, url, payload, headers, timeout_seconds):
        self.requests.append((url, payload, headers, timeout_seconds))
        return self.response


class FakeBackend:
    def __init__(self):
        self.observation = None

    def get_chunk(self, observation):
        self.observation = observation
        return [[0.5, 0.25]]


def build_backend(**options):
    backend = FakeBackend()
    backend.options = options
    return backend


class PolicyManifestTests(unittest.TestCase):
    def manifest(self, **overrides):
        value = {
            "schema_version": 1,
            "model": "act",
            "backend": "tests.test_v07_integrations:build_backend",
            "joint_names": ["joint_1"],
            "joint_units": "rad",
            "action_units": "rad",
            "camera_map": {"head": "head_camera"},
            "gripper_in_action": True,
            "state_transform": {"offset": [0, 0], "scale": [2, 2]},
            "action_transform": {"offset": [10, 20], "scale": [2, 4]},
        }
        value.update(overrides)
        return PolicyManifest.from_mapping(value)

    def test_manifest_applies_checkpoint_transforms_and_includes_gripper_state(self):
        manifest = self.manifest()
        policy = manifest.build()
        state = ArmState("left", 10, (2.0,), 4.0)
        frame = CameraFrame("head_camera", 10, "raw8", 1, 1, b"\x01")
        commands = policy.predict(state, (frame,))
        self.assertEqual(policy.client.backend.observation["qpos"], (1.0, 2.0))
        self.assertEqual(commands[0].joint_targets, (11.0,))
        self.assertEqual(commands[0].gripper_target, 21.0)

    def test_manifest_rejects_unit_mismatch_and_depth_camera(self):
        manifest = self.manifest()
        plan = TrainingPlan("act", "trainer:run", "data.hdf5", "hdf5", "out", "pick", {},
                            "leader_command", "degree", "rad")
        with self.assertRaisesRegex(ValueError, "joint units"):
            manifest.validate_training_plan(plan)
        policy = manifest.build()
        depth = CameraFrame("head_camera", 10, "png16", 1, 1, b"\x01", modality="depth")
        with self.assertRaisesRegex(ValueError, "RGB"):
            policy.predict(ArmState("left", 10, (0.0,), 0.0), (depth,))

    def test_rejects_missing_units_wrong_stats_and_secret_options(self):
        with self.assertRaisesRegex(ValueError, "units"):
            self.manifest(action_units="")
        with self.assertRaisesRegex(ValueError, "dimension"):
            self.manifest(action_transform={"offset": [0], "scale": [1]})
        with self.assertRaisesRegex(ValueError, "credentials"):
            self.manifest(backend_options={"api_key": "not-allowed"})
        with self.assertRaisesRegex(ValueError, "variable names"):
            self.manifest(backend_options={"api_key_env": "not-a-variable-secret"})
        with self.assertRaisesRegex(ValueError, "unsupported fields"):
            PolicyManifest.from_mapping({"unknown": True})

    def test_checkpoint_is_resolved_only_from_environment(self):
        manifest = self.manifest(checkpoint_env="ROBOT_TEST_CHECKPOINT")
        with self.assertRaisesRegex(ValueError, "environment variable"):
            manifest.build()
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint"
            checkpoint.mkdir()
            with patch.dict(os.environ, {"ROBOT_TEST_CHECKPOINT": str(checkpoint)}):
                policy = manifest.build()
                self.assertEqual(policy.client.backend.options["checkpoint_path"], str(checkpoint.resolve()))


class HttpIntegrationTests(unittest.TestCase):
    def test_endpoint_requires_tls_except_loopback(self):
        _validate_endpoint("http://127.0.0.1:8000/infer")
        _validate_endpoint("https://model.example/infer")
        for endpoint in ("http://model.example/infer", "https://user:pass@model.example/x",
                         "https://model.example/x?token=secret", "file:///tmp/model"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                _validate_endpoint(endpoint)

    def test_speech_client_uses_environment_credentials_and_bounds_transcript(self):
        transport = FakeTransport({"text": "pick up the cup"})
        with patch.dict(os.environ, {"ROBOT_SPEECH_KEY": "example-secret"}):
            client = SpeechToTextHttpClient("https://speech.example/transcribe",
                                            api_key_env="ROBOT_SPEECH_KEY", transport=transport)
            self.assertEqual(client.transcribe(b"audio-bytes", "audio/wav"), "pick up the cup")
        _, payload, headers, _ = transport.requests[0]
        self.assertEqual(base64.b64decode(payload["audio_base64"]), b"audio-bytes")
        self.assertEqual(headers["Authorization"], "Bearer example-secret")
        self.assertNotIn("example-secret", json.dumps(payload))
        with self.assertRaises(ValueError):
            SpeechToTextHttpClient("https://speech.example/transcribe", transport=FakeTransport({"text": ""})).transcribe(b"a")

    def test_vision_service_receives_only_rgb_and_enforces_task_allowlist(self):
        transport = FakeTransport({"task_id": "pick"})
        client = VisionTaskHttpClient("https://vision.example/plan", ("pick", "place"), transport=transport)
        frame = CameraFrame("front", 1, "jpeg", 1, 1, b"rgb")
        depth = CameraFrame("depth", 1, "png16", 1, 1, b"depth", modality="depth")
        self.assertEqual(client.select_task("pick up", (frame, depth)), "pick")
        self.assertEqual(len(transport.requests[0][1]["frames"]), 1)
        self.assertNotIn("depth", json.dumps(transport.requests[0][1]))
        client = VisionTaskHttpClient("https://vision.example/plan", ("pick",),
                                      transport=FakeTransport({"task_id": "delete_all"}))
        with self.assertRaisesRegex(ValueError, "allowlist"):
            client.select_task("pick up", (frame,))

    def test_vision_service_rejects_oversized_frame_batch(self):
        client = VisionTaskHttpClient("https://vision.example/plan", ("pick",),
                                      transport=FakeTransport({"task_id": "pick"}))
        frame = CameraFrame("front", 1, "jpeg", 4096, 4096, b"x" * 8_388_609)
        with self.assertRaisesRegex(ValueError, "8 MiB"):
            client.select_task("pick up", (frame,))

    def test_policy_service_encodes_image_and_returns_action_chunk(self):
        transport = FakeTransport({"actions": [[0.1, 0.2]]})
        backend = HttpPolicyBackend("https://policy.example/infer", transport=transport)
        actions = backend.get_chunk({"qpos": (0.0,), "images": {"head": {
            "encoding": "jpeg", "payload": b"frame"}}})
        self.assertEqual(actions, [[0.1, 0.2]])
        payload = transport.requests[0][1]
        encoded = payload["observation"]["images"]["head"]["payload"]["payload_base64"]
        self.assertEqual(base64.b64decode(encoded), b"frame")


class TrainingPlanTests(unittest.TestCase):
    def test_validates_robot_plan_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "train.hdf5"
            dataset.write_bytes(b"dataset")
            value = {
                "schema_version": 1,
                "model": "act",
                "backend": "trainer:run",
                "dataset_path": "train.hdf5",
                "dataset_format": "hdf5",
                "output_path": "checkpoints/act",
                "task": "pick",
                "action_source": "leader_command",
                "joint_units": "rad",
                "action_units": "rad",
                "hyperparameters": {"epochs": 10, "learning_rate": 0.0001},
            }
            plan_path = root / "train-plan.json"
            plan_path.write_text(json.dumps(value), encoding="utf-8")
            plan = TrainingPlan.load(plan_path)
            with self.assertRaisesRegex(ValueError, "parent directory"):
                plan.validate_paths(root)
            (root / "checkpoints").mkdir()
            plan.validate_paths(root)

    def test_rejects_incompatible_training_data_and_credentials(self):
        base = {
            "schema_version": 1,
            "model": "act",
            "backend": "trainer:run",
            "dataset_path": "train.hdf5",
            "dataset_format": "hdf5",
            "output_path": "output",
            "task": "pick",
            "action_source": "leader_command",
            "joint_units": "rad",
            "action_units": "rad",
            "hyperparameters": {},
        }
        with self.assertRaisesRegex(ValueError, "credentials"):
            TrainingPlan(**dict(base, hyperparameters={"api_key": "secret"}))
        with self.assertRaisesRegex(ValueError, "LLaMA-Factory"):
            TrainingPlan(**dict(base, model="llama_factory"))


if __name__ == "__main__":
    unittest.main()
