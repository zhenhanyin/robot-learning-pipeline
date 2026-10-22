import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from robot_learning.adapters.teleop import TeleoperationBridge, TeleoperationFrame
from robot_learning.annotation import AnnotationStore
from robot_learning.apps.operations import CaptureProfile, CaptureSupervisor, load_capture_profiles, make_handler
from robot_learning.apps.task_demo import create_demo_orchestrator
from robot_learning.cli import write_sample
from robot_learning.core.models import ArmState, RobotCommand
from robot_learning.workflows.policy_preview import SafetyEnvelope, SafetyStop


class FakeProcess:
    def __init__(self):
        self.pid = 12345
        self.running = True
        self.return_code = 0

    def poll(self):
        return None if self.running else self.return_code

    def wait(self, timeout=None):
        self.running = False
        return self.return_code


class CaptureSupervisorTests(unittest.TestCase):
    def test_profiles_are_loaded_and_capture_process_is_allowlisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "piper.json"
            config.write_text(json.dumps({
                "sdk_class": "optional_sdk:Piper",
                "can_name": "can0",
                "cameras": {"head": "/camera/image"},
                "attempts": 10,
                "sample_rate_hz": 10,
                "sync_tolerance_ms": 30,
                "camera_wait_ms": 20,
                "include_action": False,
            }), encoding="utf-8")
            profiles_file = root / "profiles.json"
            profiles_file.write_text(json.dumps({"profiles": [{
                "profile_id": "piper_lab", "robot": "piper", "config_path": "piper.json",
            }]}), encoding="utf-8")
            profiles = load_capture_profiles(profiles_file)
            processes = []
            commands = []

            def spawn(command, **options):
                commands.append((command, options))
                process = FakeProcess()
                processes.append(process)
                return process

            signals = []
            supervisor = CaptureSupervisor(root, profiles, spawn,
                                           lambda pid, sig: signals.append((pid, sig)))
            session = supervisor.start("piper_lab")
            self.assertEqual(session["state"], "running")
            self.assertEqual(commands[0][0][3], "collect-piper")
            self.assertTrue(commands[0][1]["start_new_session"])
            self.assertTrue(session["output"].startswith("recordings/"))
            with self.assertRaisesRegex(ValueError, "unknown capture profile"):
                supervisor.start("../../other")
            stopped = supervisor.stop(session["session_id"])
            self.assertEqual(stopped["state"], "exited")
            self.assertEqual(len(signals), 1)

    def test_profile_loader_rejects_unknown_fields_and_symlink_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_file = root / "profiles.json"
            profile_file.write_text(json.dumps({"profiles": [], "command": "anything"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "profiles list"):
                load_capture_profiles(profile_file)

    def test_capture_output_cannot_escape_data_root_through_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "data"
            root.mkdir()
            outside = Path(directory) / "outside"
            outside.mkdir()
            config = Path(directory) / "capture.json"
            config.write_text("{}", encoding="utf-8")
            (root / "recordings").symlink_to(outside, target_is_directory=True)
            profile = CaptureProfile("local", "piper", config)
            supervisor = CaptureSupervisor(root, {"local": profile}, lambda *args, **kwargs: None)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                supervisor.start("local")


class TeleoperationTests(unittest.TestCase):
    def setUp(self):
        self.envelope = SafetyEnvelope("left", (-1.0,), (1.0,), (0.5,), 1_000_000_000,
                                       30_000_000, 1_000_000_000, 0.0, 1.0, 0.2)
        self.state = ArmState("left", 100, (0.0,), 0.0)
        self.sent = []
        self.adapter = type("FakeAdapter", (), {"send_command": lambda adapter, command: self.sent.append(command)})()

    def frame(self, sequence=1, deadman=True, reset=False, timestamp=100):
        return TeleoperationFrame("quest-session", "left", timestamp, sequence,
                                  (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0),
                                  deadman, 0.5, reset)

    def bridge(self):
        return TeleoperationBridge(
            "quest-session", self.envelope,
            lambda frame, state: RobotCommand(state.arm_id, state.timestamp_ns, (0.1,), 0.1),
            self.adapter, max_frame_age_ns=100_000_000,
        )

    def test_deadman_preview_and_explicit_publish(self):
        bridge = self.bridge()
        released = bridge.process(self.frame(deadman=False), self.state, 100, enabled=True)
        self.assertEqual(released.status, "deadman_released")
        self.assertEqual(self.sent, [])
        preview = bridge.process(self.frame(sequence=2), self.state, 100)
        self.assertEqual(preview.status, "preview")
        self.assertFalse(preview.published)
        published = bridge.process(self.frame(sequence=3), self.state, 100, enabled=True)
        self.assertEqual(published.status, "published")
        self.assertEqual(len(self.sent), 1)

    def test_stale_replayed_arm_mismatch_and_reset_never_publish(self):
        bridge = self.bridge()
        with self.assertRaisesRegex(SafetyStop, "stale"):
            bridge.process(self.frame(timestamp=0), self.state, 100_000_001, enabled=True)
        with self.assertRaisesRegex(SafetyStop, "replayed"):
            bridge.process(self.frame(timestamp=100), self.state, 100, enabled=True)
        with self.assertRaisesRegex(SafetyStop, "arm mismatch"):
            self.bridge().process(
                TeleoperationFrame("quest-session", "right", 100, 1, (0, 0, 0), (0, 0, 0, 1), True),
                self.state, 100, enabled=True)
        reset = self.bridge().process(self.frame(reset=True), self.state, 100, enabled=True)
        self.assertEqual(reset.status, "reset_requested")
        self.assertEqual(self.sent, [])

    def test_pose_requires_normalized_quaternion(self):
        with self.assertRaisesRegex(ValueError, "normalized"):
            TeleoperationFrame("quest", "left", 1, 1, (0, 0, 0), (0, 0, 0, 2), True)


class OperationsHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        write_sample(self.root / "episode-demo")
        self.store = AnnotationStore(self.root)
        self.capture = CaptureSupervisor(self.root, {})
        self.orchestrator = create_demo_orchestrator()
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(self.store, self.capture, self.orchestrator))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:{}".format(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, path, method="GET", payload=None, headers=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(self.base + path, data=body, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=2) as response:
                content = response.read()
                if "application/json" in response.headers.get("Content-Type", ""):
                    content = json.loads(content.decode("utf-8"))
                return response.status, content
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read().decode("utf-8"))

    def request_raw(self, path, body, content_type):
        request = Request(self.base + path, data=body,
                          headers={"Content-Type": content_type}, method="POST")
        try:
            with urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read().decode("utf-8"))

    def test_unified_console_catalog_annotation_and_task_approval_preview(self):
        status, html = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Robot Learning", html)
        status, data = self.request("/api/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(data["episodes"][0]["frame_count"], 3)
        status, data = self.request("/api/episodes")
        self.assertEqual(data["episodes"], ["episode-demo"])
        status, data = self.request("/api/episodes/episode-demo/annotation", method="PUT",
                                    payload={"annotator": "tester", "spans": []})
        self.assertEqual(status, 200)
        status, data = self.request("/api/tasks/propose", method="POST", payload={"utterance": "pick sample"})
        self.assertEqual(data["phase"], "awaiting_approval")
        proposal_id = data["proposal_id"]
        status, data = self.request("/api/tasks/approve", method="POST", payload={"proposal_id": proposal_id})
        self.assertEqual(data["phase"], "approved")
        status, data = self.request("/api/tasks/preview", method="POST", payload={})
        self.assertEqual(data["phase"], "completed")
        status, data = self.request("/api/tasks/execute", method="POST", payload={})
        self.assertEqual(status, 404)

    def test_audio_is_bounded_and_passes_media_type_to_speech_adapter(self):
        seen = []

        class Speech:
            def transcribe_with_content_type(self, audio, content_type):
                seen.append((audio, content_type))
                return "pick sample"

        self.orchestrator.speech = Speech()
        status, data = self.request_raw("/api/tasks/audio", b"audio", "audio/webm")
        self.assertEqual(status, 200)
        self.assertEqual(data["phase"], "awaiting_approval")
        self.assertEqual(seen, [(b"audio", "audio/webm")])

    def test_api_checks_local_host_and_hides_unconfigured_capture_profiles(self):
        status, data = self.request("/api/status")
        self.assertEqual(status, 200)
        self.assertFalse(data["captures"]["enabled"])
        status, data = self.request("/api/status", headers={"Host": "attacker.example"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
