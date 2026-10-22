"""Loopback-only operator console for episodes, capture processes, and task preview."""

import json
import os
import re
import signal
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import RLock
from typing import Mapping, Optional, Type
from urllib.parse import unquote, urlsplit

from robot_learning.annotation import AnnotationStore
from robot_learning.apps.preview import frame_preview_png
from robot_learning.formats.validation import validate_episode
from robot_learning.workflows.task_orchestration import TaskError


LOCAL_HOST = re.compile(r"(?:localhost|127\.0\.0\.1)(?::[0-9]+)?\Z")
PROFILE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
MAX_JSON_BYTES = 65_536
MAX_AUDIO_BYTES = 1_048_576
MAX_CATALOG_EPISODES = 200
ASSETS = {
    "/": ("operations.html", "text/html; charset=utf-8"),
    "/operations.js": ("operations.js", "text/javascript; charset=utf-8"),
    "/operations.css": ("operations.css", "text/css; charset=utf-8"),
    "/annotate": ("annotator.html", "text/html; charset=utf-8"),
    "/annotator.js": ("annotator.js", "text/javascript; charset=utf-8"),
    "/annotator.css": ("annotator.css", "text/css; charset=utf-8"),
}


@dataclass(frozen=True)
class CaptureProfile:
    profile_id: str
    robot: str
    config_path: Path

    def __post_init__(self):
        if not PROFILE_ID.fullmatch(self.profile_id):
            raise ValueError("invalid capture profile_id")
        if self.robot not in ("piper", "arx_x5"):
            raise ValueError("capture robot must be piper or arx_x5")
        config = Path(self.config_path)
        if config.is_symlink() or not config.is_file():
            raise ValueError("capture config must be a regular file")
        object.__setattr__(self, "config_path", config.resolve())


def load_capture_profiles(path: Path) -> Mapping[str, CaptureProfile]:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("profile file must be a regular file under 64 KiB")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"profiles"} or not isinstance(data["profiles"], list):
        raise ValueError("profile file must contain a profiles list")
    if len(data["profiles"]) > 32:
        raise ValueError("at most 32 capture profiles are allowed")
    profiles = {}
    for value in data["profiles"]:
        if not isinstance(value, dict) or set(value) != {"profile_id", "robot", "config_path"}:
            raise ValueError("invalid capture profile fields")
        config_path = Path(value["config_path"])
        if not config_path.is_absolute():
            config_path = path.parent / config_path
        profile = CaptureProfile(value["profile_id"], value["robot"], config_path)
        if profile.profile_id in profiles:
            raise ValueError("capture profile IDs must be unique")
        if profile.robot == "piper":
            from robot_learning.apps.piper_capture import load_capture_config

            load_capture_config(profile.config_path)
        else:
            from robot_learning.apps.arx_capture import load_arx_config

            load_arx_config(profile.config_path)
        profiles[profile.profile_id] = profile
    return profiles


class CaptureSupervisor:
    def __init__(self, data_root: Path, profiles: Mapping[str, CaptureProfile],
                 popen_factory=None, kill_process_group=None):
        self.data_root = Path(data_root).resolve(strict=True)
        if not self.data_root.is_dir():
            raise ValueError("data_root must be a directory")
        self.profiles = dict(profiles)
        if any(key != profile.profile_id for key, profile in self.profiles.items()):
            raise ValueError("capture profile keys must match profile IDs")
        self.popen_factory = popen_factory or subprocess.Popen
        self.kill_process_group = kill_process_group or os.killpg
        self.sessions = {}
        self.lock = RLock()

    def status(self) -> dict:
        with self.lock:
            return {"enabled": bool(self.profiles),
                    "profiles": [{"profile_id": profile.profile_id, "robot": profile.robot}
                                 for profile in self.profiles.values()],
                    "sessions": [self._session_status(session_id, session)
                                 for session_id, session in self.sessions.items()]}

    def start(self, profile_id: str) -> dict:
        with self.lock:
            if len(self.sessions) >= 256:
                for session_id, session in tuple(self.sessions.items()):
                    if session["process"].poll() is not None:
                        del self.sessions[session_id]
                    if len(self.sessions) < 256:
                        break
            if len(self.sessions) >= 256:
                raise ValueError("too many capture session records; restart the console")
            profile = self.profiles.get(profile_id)
            if profile is None:
                raise ValueError("unknown capture profile")
            if any(session["profile_id"] == profile_id and session["process"].poll() is None
                   for session in self.sessions.values()):
                raise ValueError("capture profile is already running")
            session_id = uuid.uuid4().hex
            recordings = self.data_root / "recordings"
            logs = self.data_root / "operations-logs"
            for directory in (recordings, logs):
                if directory.is_symlink():
                    raise ValueError("capture output directories must not be symlinks")
                directory.mkdir(exist_ok=True)
                if not directory.is_dir() or directory.resolve(strict=True).parent != self.data_root:
                    raise ValueError("capture output directories must remain inside data_root")
            output = recordings / ("{}-{}".format(profile_id, session_id))
            log_path = logs / (session_id + ".log")
            if profile.robot == "piper":
                command = [sys.executable, "-m", "robot_learning.cli", "collect-piper",
                           "--config", str(profile.config_path), str(output)]
            else:
                command = [sys.executable, "-m", "robot_learning.cli", "collect-arx",
                           "--config", str(profile.config_path), str(output)]
            with log_path.open("xb") as log_file:
                process = self.popen_factory(command, stdin=subprocess.DEVNULL, stdout=log_file,
                                             stderr=subprocess.STDOUT, start_new_session=True,
                                             close_fds=True)
            session = {"profile_id": profile_id, "robot": profile.robot,
                       "process": process, "output": output, "log": log_path,
                       "started_at": datetime.now(timezone.utc).isoformat()}
            self.sessions[session_id] = session
            return self._session_status(session_id, session)

    def stop(self, session_id: str, grace_seconds: float = 3.0) -> dict:
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise ValueError("unknown capture session")
            process = session["process"]
            if process.poll() is None:
                try:
                    self.kill_process_group(process.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=grace_seconds)
                except subprocess.TimeoutExpired:
                    try:
                        self.kill_process_group(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=grace_seconds)
                    except subprocess.TimeoutExpired:
                        try:
                            self.kill_process_group(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
            return self._session_status(session_id, session)

    def _session_status(self, session_id: str, session: dict) -> dict:
        process = session["process"]
        return {"session_id": session_id, "profile_id": session["profile_id"],
                "robot": session["robot"], "state": "running" if process.poll() is None else "exited",
                "exit_code": process.poll(), "output": str(session["output"].relative_to(self.data_root)),
                "log": str(session["log"].relative_to(self.data_root)),
                "started_at": session["started_at"]}


def make_handler(store: AnnotationStore, captures: CaptureSupervisor,
                 orchestrator: Optional[object] = None) -> Type[BaseHTTPRequestHandler]:
    class OperationsHandler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; connect-src 'self'; media-src 'self' blob:; "
                             "object-src 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: object) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8"),
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

        def _body(self, limit: int = MAX_JSON_BYTES) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError as error:
                raise ValueError("valid Content-Length required") from error
            if length < 0 or length > limit:
                raise OverflowError("request body too large")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("request body is incomplete")
            return body

        def _json_body(self) -> dict:
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                raise TypeError("application/json required")
            data = json.loads(self._body())
            if not isinstance(data, dict):
                raise ValueError("JSON object required")
            return data

        def _task(self):
            if orchestrator is None:
                self._json(503, {"error": "task services are not configured"})
                return None
            return orchestrator

        def do_GET(self) -> None:
            if not self._authorized():
                return
            path = unquote(urlsplit(self.path).path)
            if path in ASSETS:
                filename, content_type = ASSETS[path]
                self._send(200, Path(__file__).with_name(filename).read_bytes(), content_type)
                return
            try:
                if path == "/api/status":
                    task_status = orchestrator.status() if orchestrator is not None else {"available": False}
                    self._json(200, {"captures": captures.status(), "tasks": task_status})
                elif path == "/api/episodes":
                    self._json(200, {"episodes": store.list_episodes()})
                elif path == "/api/catalog":
                    all_names = store.list_episodes()
                    names = all_names[:MAX_CATALOG_EPISODES]
                    episodes = []
                    for name in names:
                        report = validate_episode(store.data_root / name)
                        annotation = store.get_episode(name).get("annotation")
                        episodes.append({"name": name, "valid": report.valid,
                                         "frame_count": report.counts.get("frame", 0),
                                         "annotation_count": len(annotation["spans"]) if annotation else 0,
                                         "errors": report.errors[:5]})
                    self._json(200, {"episodes": episodes,
                                     "truncated": len(all_names) > MAX_CATALOG_EPISODES})
                elif re.fullmatch(r"/api/episodes/[^/]+/frames/[0-9]+", path):
                    _, _, _, name, _, index = path.split("/")
                    frame = store.get_frame(name, int(index))
                    self._send(200, frame_preview_png(frame.encoding, frame.width, frame.height,
                                                      frame.payload), "image/png")
                elif re.fullmatch(r"/api/episodes/[^/]+", path):
                    name = path.rsplit("/", 1)[1]
                    self._json(200, store.get_episode(name))
                else:
                    self._json(404, {"error": "unknown endpoint"})
            except (FileNotFoundError, ValueError, KeyError, TypeError, OSError) as error:
                self._json(404, {"error": str(error)})

        def do_PUT(self) -> None:
            if not self._authorized():
                return
            path = unquote(urlsplit(self.path).path)
            match = re.fullmatch(r"/api/episodes/([^/]+)/annotation", path)
            if not match:
                self._json(404, {"error": "unknown endpoint"})
                return
            try:
                data = self._json_body()
                self._json(200, store.set_annotation(match.group(1), data))
            except TypeError as error:
                self._json(415, {"error": str(error)})
            except OverflowError as error:
                self._json(413, {"error": str(error)})
            except (FileNotFoundError, ValueError, KeyError, OSError) as error:
                self._json(400, {"error": str(error)})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            path = unquote(urlsplit(self.path).path)
            try:
                if path == "/api/captures/start":
                    data = self._json_body()
                    if set(data) != {"profile_id"}:
                        raise ValueError("profile_id is required")
                    self._json(200, captures.start(data["profile_id"]))
                    return
                if path == "/api/captures/stop":
                    data = self._json_body()
                    if set(data) != {"session_id"}:
                        raise ValueError("session_id is required")
                    self._json(200, captures.stop(data["session_id"]))
                    return
                if path == "/api/tasks/audio":
                    task = self._task()
                    if task is None:
                        return
                    content_type = self.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
                    if not (content_type.startswith("audio/") or content_type == "application/octet-stream"):
                        raise TypeError("audio content type required")
                    self._json(200, task.propose_audio(self._body(MAX_AUDIO_BYTES), content_type))
                    return
                data = self._json_body()
                task = self._task() if path.startswith("/api/tasks/") else None
                if path.startswith("/api/tasks/") and task is None:
                    return
                if path == "/api/tasks/propose" and set(data) == {"utterance"}:
                    result = task.propose_text(data["utterance"])
                elif path == "/api/tasks/approve" and set(data) == {"proposal_id"}:
                    result = task.approve(data["proposal_id"])
                elif path == "/api/tasks/preview" and not data:
                    result = task.preview()
                elif path == "/api/tasks/stop" and not data:
                    result = task.stop()
                else:
                    self._json(404, {"error": "unknown endpoint or fields"})
                    return
                self._json(200, result)
            except TypeError as error:
                self._json(415, {"error": str(error)})
            except OverflowError as error:
                self._json(413, {"error": str(error)})
            except TaskError as error:
                self._json(409, {"error": str(error),
                                 "status": orchestrator.status() if orchestrator is not None else None})
            except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
                self._json(400, {"error": str(error)})

    return OperationsHandler


def serve(data_root: Path, port: int = 8768, profiles_path: Optional[Path] = None,
          task_factory_reference: Optional[str] = None) -> None:
    store = AnnotationStore(data_root)
    profiles = load_capture_profiles(profiles_path) if profiles_path else {}
    captures = CaptureSupervisor(data_root, profiles)
    orchestrator = None
    if task_factory_reference:
        from robot_learning.policies.factory import load_component

        orchestrator = load_component(task_factory_reference)
    with HTTPServer(("127.0.0.1", port), make_handler(store, captures, orchestrator)) as server:
        print("Robot operations console: http://127.0.0.1:{}".format(server.server_port))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            for session in captures.status()["sessions"]:
                if session["state"] == "running":
                    captures.stop(session["session_id"])
