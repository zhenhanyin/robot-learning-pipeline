import json
import threading
import unittest
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from robot_learning.apps.task_demo import create_demo_orchestrator, make_handler
from robot_learning.core.models import ArmState, CameraFrame
from robot_learning.workflows.task_orchestration import TaskError


class TaskOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.orchestrator = create_demo_orchestrator()

    def test_voice_vision_policy_two_task_replay(self):
        for utterance, task_id in ((b"pick sample", "pick_sample"), (b"clear table", "clear_table")):
            proposed = self.orchestrator.propose_audio(utterance)
            self.assertEqual(proposed["phase"], "awaiting_approval")
            self.assertEqual(proposed["task_id"], task_id)
            self.assertEqual(proposed["candidate_count"], 0)
            with self.assertRaises(TaskError):
                self.orchestrator.preview()
            approved = self.orchestrator.approve(proposed["proposal_id"])
            self.assertEqual(approved["phase"], "approved")
            completed = self.orchestrator.preview()
            self.assertEqual(completed["phase"], "completed")
            self.assertEqual(completed["candidate_count"], 2)
            self.assertFalse(completed["command_published"])
        self.assertEqual(self.orchestrator.status()["proposal_id"], 2)

    def test_wrong_approval_and_repeated_preview_do_not_run_policy(self):
        proposed = self.orchestrator.propose_text("pick sample")
        with self.assertRaises(TaskError):
            self.orchestrator.approve(proposed["proposal_id"] + 1)
        self.assertEqual(self.orchestrator.status()["phase"], "awaiting_approval")
        self.orchestrator.approve(proposed["proposal_id"])
        self.orchestrator.preview()
        with self.assertRaises(TaskError):
            self.orchestrator.preview()

    def test_unknown_or_failing_vision_stops(self):
        class UnknownVision:
            def select_task(self, transcript, frames):
                return "unapproved_task"

        self.orchestrator.vision = UnknownVision()
        with self.assertRaisesRegex(TaskError, "planning failed"):
            self.orchestrator.propose_text("pick sample")
        self.assertEqual(self.orchestrator.status()["phase"], "stopped")
        with self.assertRaises(TaskError):
            self.orchestrator.propose_text("pick sample")

    def test_stop_during_vision_cannot_resurrect_proposal(self):
        orchestrator = self.orchestrator

        class StoppingVision:
            def select_task(self, transcript, frames):
                orchestrator.stop()
                return "pick_sample"

        orchestrator.vision = StoppingVision()
        with self.assertRaises(TaskError):
            orchestrator.propose_text("pick sample")
        self.assertEqual(orchestrator.status()["phase"], "stopped")
        self.assertIsNone(orchestrator.status()["proposal_id"])

    def test_invalid_voice_input_and_transcription_stop(self):
        with self.assertRaises(ValueError):
            self.orchestrator.propose_audio(b"")

        class EmptySpeech:
            def transcribe(self, audio):
                return ""

        self.orchestrator.speech = EmptySpeech()
        with self.assertRaisesRegex(TaskError, "invalid transcript"):
            self.orchestrator.propose_audio(b"voice")
        self.assertEqual(self.orchestrator.status()["phase"], "stopped")

    def test_stale_vision_frame_and_policy_failure_stop(self):
        def stale_observation():
            return ArmState("left", 0, (0.0,)), (CameraFrame("base", 0, "raw8", 1, 1, b"\x00"),), 1_000_000_000

        self.orchestrator.observation = stale_observation
        with self.assertRaisesRegex(TaskError, "planning failed"):
            self.orchestrator.propose_text("pick sample")
        self.assertEqual(self.orchestrator.status()["phase"], "stopped")

        orchestrator = create_demo_orchestrator()
        proposal = orchestrator.propose_text("pick sample")
        orchestrator.approve(proposal["proposal_id"])

        class DisconnectedModel:
            def get_chunk(self, observation):
                raise ConnectionError("fake disconnect")

        orchestrator.tasks["pick_sample"].runner.policy.backend = DisconnectedModel()
        with self.assertRaisesRegex(TaskError, "preview failed"):
            orchestrator.preview()
        self.assertEqual(orchestrator.status()["phase"], "stopped")

    def test_stop_is_latched_and_not_hardware_emergency(self):
        proposed = self.orchestrator.propose_text("pick sample")
        stopped = self.orchestrator.stop()
        self.assertEqual(stopped["phase"], "stopped")
        self.assertFalse(stopped["command_published"])
        with self.assertRaises(TaskError):
            self.orchestrator.approve(proposed["proposal_id"])
        self.assertTrue(all(task.runner.stopped for task in self.orchestrator.tasks.values()))


class TaskDemoHttpTests(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(create_demo_orchestrator()))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = "http://127.0.0.1:{}".format(self.server.server_port)

    def request(self, path, payload=None, headers=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        method = "GET" if payload is None else "POST"
        request = Request(self.base_url + path, data=body, method=method, headers=headers or {})
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, response.read(), response.headers
        except HTTPError as error:
            with error:
                return error.code, error.read(), error.headers

    def test_page_and_complete_http_task(self):
        for path in ("/", "/task_demo.js", "/task_demo.css"):
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(json.loads(self.request("/api/status")[1])["phase"], "idle")
        headers = {"Content-Type": "application/json", "Origin": self.base_url}
        proposed = self.request("/api/propose", {"utterance": "pick sample"}, headers)
        self.assertEqual(proposed[0], 200)
        proposal_id = json.loads(proposed[1])["proposal_id"]
        self.assertEqual(self.request("/api/preview", {}, headers)[0], 409)
        self.assertEqual(self.request("/api/approve", {"proposal_id": proposal_id}, headers)[0], 200)
        completed = json.loads(self.request("/api/preview", {}, headers)[1])
        self.assertEqual((completed["phase"], completed["candidate_count"]), ("completed", 2))
        self.assertFalse(completed["command_published"])
        self.assertEqual(self.request("/api/execute", {}, headers)[0], 404)
        self.assertEqual(json.loads(self.request("/api/stop", {}, headers)[1])["phase"], "stopped")

    def test_rejects_cross_origin_host_and_malformed_payload(self):
        data = {"utterance": "pick sample"}
        self.assertEqual(self.request("/api/propose", data, {"Content-Type": "application/json", "Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.request("/api/propose", data, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/propose", {"unexpected": "pick"}, {"Content-Type": "application/json"})[0], 404)
        self.assertEqual(self.request("/api/propose", {"utterance": ""}, {"Content-Type": "application/json"})[0], 400)
        oversized = Request(self.base_url + "/api/propose", data=b"x" * 4097, method="POST",
                            headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(oversized, timeout=3)
        self.assertEqual(error.exception.code, 413)
        error.exception.close()
        malformed = Request(self.base_url + "/api/propose", data=b"{", method="POST",
                            headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as error:
            urlopen(malformed, timeout=3)
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        request = Request(self.base_url + "/api/status", headers={"Host": "example.org"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=3)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
