"""Opt-in JSON service clients for speech, vision planning, and policy inference."""

import base64
import ipaddress
import json
import os
from numbers import Real
from typing import Mapping, Optional, Protocol, Sequence
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from robot_learning.core.models import CameraFrame


class JsonTransport(Protocol):
    def post(self, url: str, payload: Mapping[str, object], headers: Mapping[str, str],
             timeout_seconds: float) -> Mapping[str, object]:
        ...


class UrllibJsonTransport:
    def post(self, url: str, payload: Mapping[str, object], headers: Mapping[str, str],
             timeout_seconds: float) -> Mapping[str, object]:
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        if len(body) > 33_554_432:
            raise ValueError("service request exceeds 32 MiB")
        request_headers = {"Content-Type": "application/json", "Accept": "application/json"}
        request_headers.update(headers)
        request = Request(url, data=body, headers=request_headers, method="POST")
        opener = build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=timeout_seconds) as response:
            response_body = response.read(2_097_153)
        if len(response_body) > 2_097_152:
            raise ValueError("service response exceeds 2 MiB")
        result = json.loads(response_body.decode("utf-8"))
        if not isinstance(result, Mapping):
            raise ValueError("service response must be a JSON object")
        return result


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise HTTPError(request.full_url, code, "service redirects are not followed", headers, response)


class _JsonService:
    def __init__(self, endpoint: str, timeout_seconds: float = 10.0,
                 api_key_env: Optional[str] = None, transport: Optional[JsonTransport] = None):
        _validate_endpoint(endpoint)
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, Real) or not 0 < timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 0 and 120")
        self.endpoint = endpoint
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport or UrllibJsonTransport()
        self.headers = {}
        if api_key_env:
            api_key = os.environ.get(api_key_env)
            if not api_key:
                raise ValueError("API key environment variable is not set")
            self.headers["Authorization"] = "Bearer " + api_key

    def _post(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        return self.transport.post(self.endpoint, payload, self.headers, self.timeout_seconds)


class SpeechToTextHttpClient(_JsonService):
    def transcribe(self, audio: bytes, content_type: str = "application/octet-stream") -> str:
        if not isinstance(audio, bytes) or not 0 < len(audio) <= 5_242_880:
            raise ValueError("audio must contain at most 5 MiB")
        if not isinstance(content_type, str) or not content_type.startswith("audio/") and content_type != "application/octet-stream":
            raise ValueError("unsupported audio content type")
        response = self._post({"audio_base64": base64.b64encode(audio).decode("ascii"),
                               "content_type": content_type})
        transcript = response.get("text")
        if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 200:
            raise ValueError("speech service returned an invalid transcript")
        return transcript.strip()


class VisionTaskHttpClient(_JsonService):
    def __init__(self, endpoint: str, allowed_tasks: Sequence[str], timeout_seconds: float = 10.0,
                 api_key_env: Optional[str] = None, transport: Optional[JsonTransport] = None):
        super().__init__(endpoint, timeout_seconds, api_key_env, transport)
        self.allowed_tasks = tuple(allowed_tasks)
        if not self.allowed_tasks or any(not isinstance(task, str) or not task for task in self.allowed_tasks):
            raise ValueError("allowed_tasks must contain task IDs")
        if len(set(self.allowed_tasks)) != len(self.allowed_tasks):
            raise ValueError("allowed_tasks must be unique")

    def select_task(self, transcript: str, frames: Sequence[CameraFrame]) -> str:
        if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 200:
            raise ValueError("transcript is invalid")
        rgb_frames = [frame for frame in frames if frame.modality == "rgb"]
        if not rgb_frames:
            raise ValueError("vision planning requires at least one RGB frame")
        if len(rgb_frames) > 8:
            raise ValueError("vision planning accepts at most eight frames")
        if sum(len(frame.payload) for frame in rgb_frames) > 16_777_216:
            raise ValueError("vision planning image payload exceeds 16 MiB")
        response = self._post({"transcript": transcript, "allowed_tasks": list(self.allowed_tasks),
                               "frames": [_frame_payload(frame) for frame in rgb_frames]})
        task_id = response.get("task_id")
        if task_id not in self.allowed_tasks:
            raise ValueError("vision service selected a task outside the allowlist")
        return task_id


class HttpPolicyBackend(_JsonService):
    def get_chunk(self, observation: Mapping[str, object]):
        return self._infer("act", observation).get("actions")

    def predict_action(self, observation: Mapping[str, object]):
        return self._infer("hrdt", observation).get("actions")

    def infer(self, observation: Mapping[str, object]):
        return self._infer("openpi", observation)

    def _infer(self, model: str, observation: Mapping[str, object]) -> Mapping[str, object]:
        result = self._post({"model": model, "observation": _json_safe(observation)})
        if not isinstance(result.get("actions"), (list, tuple)):
            raise ValueError("policy service response must contain actions")
        return result


def _validate_endpoint(endpoint: str) -> None:
    if not isinstance(endpoint, str):
        raise ValueError("service endpoint must be a URL")
    parsed = urlsplit(endpoint)
    if parsed.scheme == "https":
        allowed = True
    elif parsed.scheme == "http" and parsed.hostname:
        host = parsed.hostname.lower()
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = host == "localhost"
    else:
        allowed = False
    if (not allowed or not parsed.hostname or parsed.username or parsed.password or
            parsed.fragment or parsed.query):
        raise ValueError("service endpoint must use HTTPS or explicit loopback HTTP")


def _frame_payload(frame: CameraFrame) -> Mapping[str, object]:
    if frame.modality != "rgb":
        raise ValueError("vision services do not accept depth frames as RGB")
    if len(frame.payload) > 8_388_608:
        raise ValueError("camera frame exceeds 8 MiB")
    return {"camera_id": frame.camera_id, "timestamp_ns": frame.timestamp_ns,
            "encoding": frame.encoding, "width": frame.width, "height": frame.height,
            "payload_base64": base64.b64encode(frame.payload).decode("ascii")}


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, bytes):
        return {"payload_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Real):
        number = float(value)
        if not -float("inf") < number < float("inf"):
            raise ValueError("policy observation contains a non-finite number")
        return number
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    raise ValueError("policy observation contains a non-JSON value")
