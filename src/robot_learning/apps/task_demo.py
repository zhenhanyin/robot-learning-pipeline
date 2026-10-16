"""Loopback-only synthetic task dashboard with no robot command path."""

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import monotonic_ns
from typing import Type
from urllib.parse import urlsplit

from robot_learning.core.models import ArmState, CameraFrame
from robot_learning.policies import ModelPolicyClient, PolicySpec
from robot_learning.workflows.policy_preview import OfflinePolicyRunner, SafetyEnvelope
from robot_learning.workflows.task_orchestration import TaskDefinition, TaskError, TaskOrchestrator


LOCAL_HOST = re.compile(r"(?:localhost|127\.0\.0\.1)(?::[0-9]+)?\Z")
MAX_BODY_BYTES = 4096
ASSETS = {
    "/": ("task_demo.html", "text/html; charset=utf-8"),
    "/task_demo.js": ("task_demo.js", "text/javascript; charset=utf-8"),
    "/task_demo.css": ("task_demo.css", "text/css; charset=utf-8"),
}


class FakeSpeech:
    def transcribe(self, audio: bytes) -> str:
        return audio.decode("utf-8")


class FakeVision:
    def select_task(self, transcript: str, frames) -> str:
        if not frames:
            raise ValueError("synthetic image missing")
        if "pick" in transcript.lower() or "拾取" in transcript:
            return "pick_sample"
        if "clear" in transcript.lower() or "清理" in transcript:
            return "clear_table"
        raise ValueError("no synthetic task matches the transcript")


class FakePolicy:
    def get_chunk(self, observation):
        return [[0.1], [0.2]]

    def infer(self, observation):
        return {"actions": [[-0.1], [-0.2]]}


def create_demo_orchestrator() -> TaskOrchestrator:
    def observation():
        timestamp_ns = monotonic_ns()
        return (ArmState("left", timestamp_ns, (0.0,)),
                (CameraFrame("base", timestamp_ns, "raw8", 1, 1, b"\x00"),), timestamp_ns)

    envelope = SafetyEnvelope("left", (-1.0,), (1.0,), (0.5,), 1_000_000_000,
                              30_000_000, 1_000_000_000)
    fake_model = FakePolicy()
    pick = OfflinePolicyRunner(ModelPolicyClient(
        PolicySpec("act", {"head": "base"}, 1), fake_model, lambda frame: frame.payload), envelope)
    clear = OfflinePolicyRunner(ModelPolicyClient(
        PolicySpec("pi0.5", {"head": "base"}, 1, prompt="synthetic clear"),
        fake_model, lambda frame: frame.payload), envelope)
    return TaskOrchestrator(FakeSpeech(), FakeVision(), observation, {
        "pick_sample": TaskDefinition("pick_sample", "Pick synthetic sample", pick),
        "clear_table": TaskDefinition("clear_table", "Clear synthetic table", clear),
    })


def make_handler(orchestrator: TaskOrchestrator) -> Type[BaseHTTPRequestHandler]:
    class TaskDemoHandler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: object) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _authorized(self) -> bool:
            host = self.headers.get("Host", "")
            if not LOCAL_HOST.fullmatch(host):
                self._json(403, {"error": "local host required"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin != "http://" + host:
                self._json(403, {"error": "same origin required"})
                return False
            return True

        def do_GET(self) -> None:
            if not self._authorized():
                return
            path = urlsplit(self.path).path
            if path == "/api/status":
                self._json(200, orchestrator.status())
            elif path in ASSETS:
                filename, content_type = ASSETS[path]
                self._send(200, Path(__file__).with_name(filename).read_bytes(), content_type)
            else:
                self._json(404, {"error": "unknown endpoint"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(415, {"error": "application/json required"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json(400, {"error": "valid Content-Length required"})
                return
            if length < 0 or length > MAX_BODY_BYTES:
                self._json(413, {"error": "request body too large"})
                return
            try:
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("JSON object required")
                path = urlsplit(self.path).path
                if path == "/api/propose" and set(data) == {"utterance"}:
                    result = orchestrator.propose_text(data["utterance"])
                elif path == "/api/approve" and set(data) == {"proposal_id"}:
                    result = orchestrator.approve(data["proposal_id"])
                elif path == "/api/preview" and not data:
                    result = orchestrator.preview()
                elif path == "/api/stop" and not data:
                    result = orchestrator.stop()
                else:
                    self._json(404, {"error": "unknown endpoint or fields"})
                    return
                self._json(200, result)
            except ValueError as error:
                self._json(400, {"error": str(error)})
            except TaskError as error:
                self._json(409, {"error": str(error), "status": orchestrator.status()})

    return TaskDemoHandler


def serve(port: int = 8766) -> None:
    orchestrator = create_demo_orchestrator()
    with HTTPServer(("127.0.0.1", port), make_handler(orchestrator)) as server:
        print("Offline task demo: http://127.0.0.1:{}".format(server.server_port))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
