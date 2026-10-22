"""Loopback HTTP facade for the old Piper ROS1 service and task topic contracts."""

import importlib
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Type
from urllib.parse import urlsplit


LOCAL_HOST = re.compile(r"(?:localhost|127\.0\.0\.1)(?::[0-9]+)?\Z")
TOPICS = {
    "sweep": "/arm_control/table_sweep",
    "clean": "/arm_control/table_clean",
    "vllm": "/arm_control/vllm_mode",
    "move_left": "/arm_control/move_left",
    "move_right": "/arm_control/move_right",
    "dump": "/arm_control/dump",
    "put_plate": "/arm_control/put_plate",
    "sweep_all": "/arm_control/sweep_all",
    "return_initial_position": "/arm_control/return_initial_position",
    "pick_up_the_plate": "/arm_control/pick_up_the_plate",
}


class PiperRos1ControlBackend:
    def __init__(self, ros: object = None, std_srvs: object = None, std_msgs: object = None):
        self.ros = ros or importlib.import_module("rospy")
        services = std_srvs or importlib.import_module("std_srvs.srv")
        messages = std_msgs or importlib.import_module("std_msgs.msg")
        self.ros.init_node("robot_learning_control_web", anonymous=True)
        self.proxies = {
            name: self.ros.ServiceProxy("/piper_collect_data/" + name,
                                        services.SetBool if name == "set_switch" else services.Trigger)
            for name in ("query_switch", "set_switch", "query_status", "query_record_num")
        }
        self.publishers = {name: self.ros.Publisher(topic, messages.Bool, queue_size=10)
                           for name, topic in TOPICS.items()}
        self.publishers["vla"] = self.ros.Publisher("/change_mode_vla_or_return/", messages.String, queue_size=10)
        self.publishers["return_to_init_pos"] = self.ros.Publisher("/is_stop/", messages.Bool, queue_size=10)
        self.publishers["obj"] = self.ros.Publisher("/arm_control/franka_msg", messages.String, queue_size=10)
        self.messages = messages

    def query(self, name: str) -> dict:
        if name not in ("query_switch", "query_status", "query_record_num"):
            raise ValueError("unknown query")
        response = self.proxies[name]()
        message = response.message
        if name != "query_switch":
            message = json.loads(message)
        return {"success": bool(response.success), "message": message}

    def set_switch(self, enabled: bool) -> dict:
        if type(enabled) is not bool:
            raise ValueError("switch_state must be boolean")
        response = self.proxies["set_switch"](enabled)
        return {"success": bool(response.success), "message": response.message}

    def action(self, name: str, value: str = "") -> dict:
        if name not in self.publishers:
            raise ValueError("unknown action")
        if name == "obj":
            if not isinstance(value, str) or not 0 < len(value.strip()) <= 200:
                raise ValueError("obj requires nonempty text up to 200 characters")
            message = self.messages.String(data=value.strip().lower())
        elif name == "vla":
            message = self.messages.String(data="use_vla")
        else:
            message = self.messages.Bool(data=True)
        self.publishers[name].publish(message)
        return {"success": True, "message": name}


def make_handler(backend: object) -> Type[BaseHTTPRequestHandler]:
    class ControlHandler(BaseHTTPRequestHandler):
        def _json(self, status: int, data: object) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if not LOCAL_HOST.fullmatch(host) or (origin is not None and origin != "http://" + host):
                self._json(403, {"error": "loopback same-origin request required"})
                return False
            return True

        def do_GET(self) -> None:
            if not self._authorized():
                return
            path = urlsplit(self.path).path
            name = path[5:] if path.startswith("/api/") else ""
            if name not in ("query_switch", "query_status", "query_record_num"):
                self._json(404, {"error": "unknown read endpoint"})
                return
            try:
                self._json(200, backend.query(name))
            except Exception as error:
                self._json(502, {"error": str(error)})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(415, {"error": "application/json required"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
                if not 0 <= length <= 4096:
                    raise ValueError("request body too large")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("JSON object required")
                path = urlsplit(self.path).path
                name = path[5:] if path.startswith("/api/") else ""
                if name == "set_switch" and set(data) == {"switch_state"}:
                    result = backend.set_switch(data["switch_state"])
                elif name in TOPICS or name in ("vla", "return_to_init_pos", "obj"):
                    if set(data) != ({"text"} if name == "obj" else set()):
                        raise ValueError("unexpected action fields")
                    result = backend.action(name, data.get("text", ""))
                else:
                    self._json(404, {"error": "unknown write endpoint"})
                    return
                self._json(200, result)
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                self._json(400, {"error": str(error)})
            except Exception as error:
                self._json(502, {"error": str(error)})

    return ControlHandler


def serve(port: int = 8767) -> None:
    with HTTPServer(("127.0.0.1", port), make_handler(PiperRos1ControlBackend())) as server:
        server.serve_forever()
