"""Loopback-only annotation server for offline episodes."""

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Type
from urllib.parse import unquote, urlsplit

from robot_learning.annotation import AnnotationStore
from robot_learning.apps.preview import frame_preview_png


MAX_BODY_BYTES = 65_536
LOCAL_HOST = re.compile(r"(?:localhost|127\.0\.0\.1)(?::[0-9]+)?\Z")
ASSETS = {
    "/": ("annotator.html", "text/html; charset=utf-8"),
    "/annotator.js": ("annotator.js", "text/javascript; charset=utf-8"),
    "/annotator.css": ("annotator.css", "text/css; charset=utf-8"),
}


def make_handler(store: AnnotationStore) -> Type[BaseHTTPRequestHandler]:
    class AnnotatorHandler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: object) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

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

        def _episode_name(self, path: str, annotation: bool = False) -> str:
            parts = path.split("/")
            expected_length = 5 if annotation else 4
            if len(parts) != expected_length or parts[:3] != ["", "api", "episodes"]:
                raise ValueError("unknown endpoint")
            if annotation and parts[4] != "annotation":
                raise ValueError("unknown endpoint")
            return parts[3]

        def do_GET(self) -> None:
            if not self._authorized():
                return
            path = unquote(urlsplit(self.path).path)
            if path in ASSETS:
                filename, content_type = ASSETS[path]
                self._send(200, Path(__file__).with_name(filename).read_bytes(), content_type)
                return
            try:
                if path == "/api/episodes":
                    self._json(200, {"episodes": store.list_episodes()})
                elif re.fullmatch(r"/api/episodes/[^/]+/frames/[0-9]+", path):
                    _, _, _, name, _, index = path.split("/")
                    frame = store.get_frame(name, int(index))
                    self._send(
                        200, frame_preview_png(frame.encoding, frame.width, frame.height, frame.payload), "image/png",
                    )
                else:
                    self._json(200, store.get_episode(self._episode_name(path)))
            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                self._json(404, {"error": str(error)})

        def do_PUT(self) -> None:
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
            path = unquote(urlsplit(self.path).path)
            try:
                name = self._episode_name(path, annotation=True)
                data = json.loads(self.rfile.read(length))
                self._json(200, store.set_annotation(name, data))
            except (FileNotFoundError, ValueError, TypeError, KeyError) as error:
                self._json(400, {"error": str(error)})

    return AnnotatorHandler


def serve(data_root: Path, port: int = 8765) -> None:
    store = AnnotationStore(data_root)
    with HTTPServer(("127.0.0.1", port), make_handler(store)) as server:
        print("Annotator: http://127.0.0.1:{}".format(server.server_port))
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
