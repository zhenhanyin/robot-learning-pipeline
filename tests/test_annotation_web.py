import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from robot_learning.annotation import AnnotationStore
from robot_learning.apps.annotator import make_handler
from robot_learning.cli import write_sample
from robot_learning.formats.annotation import load_annotation


class AnnotationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_sample(self.root / "demo")
        self.store = AnnotationStore(self.root)

    def test_list_read_and_replace_annotation(self):
        self.assertEqual(self.store.list_episodes(), ["demo"])
        self.assertEqual(self.store.get_episode("demo")["frame_count"], 3)
        data = {"annotator": "tester", "spans": [{"start_index": 0, "end_index": 2, "text": "pick"}]}
        self.assertEqual(self.store.set_annotation("demo", data)["spans"][0]["text"], "pick")
        self.assertEqual(self.store.get_episode("demo")["annotation"]["annotator"], "tester")
        data["spans"][0]["text"] = "place"
        self.store.set_annotation("demo", data)
        self.assertEqual(load_annotation(self.root / "demo").spans[0].text, "place")
        self.assertEqual(len(list((self.root / "demo").iterdir())), 4)

    def test_rejects_invalid_spans_without_overwriting(self):
        valid = {"annotator": "tester", "spans": [{"start_index": 0, "end_index": 1, "text": "pick"}]}
        self.store.set_annotation("demo", valid)
        for span in (
            {"start_index": 0, "end_index": 4, "text": "too long"},
            {"start_index": True, "end_index": 1, "text": "boolean"},
            {"start_index": 1, "end_index": 1, "text": "empty"},
            {"start_index": 0, "end_index": 1, "text": " "},
            "not an object",
        ):
            with self.subTest(span=span), self.assertRaises(ValueError):
                self.store.set_annotation("demo", {"annotator": "tester", "spans": [span]})
        self.assertEqual(load_annotation(self.root / "demo").spans[0].text, "pick")

    def test_rejects_traversal_and_symlinked_files(self):
        with self.assertRaises(ValueError):
            self.store.get_episode("../demo")
        outside = self.root / "outside.txt"
        outside.write_text("private", encoding="utf-8")
        (self.root / "alias").symlink_to(self.root / "demo", target_is_directory=True)
        with self.assertRaises(ValueError):
            self.store.get_episode("alias")
        (self.root / "demo" / "annotation.json").symlink_to(outside)
        with self.assertRaises(ValueError):
            self.store.get_episode("demo")
        with self.assertRaises(ValueError):
            self.store.set_annotation("demo", {"annotator": "tester", "spans": []})
        self.assertEqual(outside.read_text(encoding="utf-8"), "private")


class AnnotationHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_sample(self.root / "demo")
        self.store = AnnotationStore(self.root)
        self.server = HTTPServer(("127.0.0.1", 0), make_handler(self.store))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = "http://127.0.0.1:{}".format(self.server.server_port)

    def request(self, path, method="GET", data=None, headers=None):
        payload = None if data is None else json.dumps(data).encode("utf-8")
        request = Request(self.base_url + path, data=payload, method=method, headers=headers or {})
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, response.read()
        except HTTPError as error:
            with error:
                return error.code, error.read()

    def test_page_assets_and_api_round_trip(self):
        for path in ("/", "/annotator.js", "/annotator.css"):
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(json.loads(self.request("/api/episodes")[1]), {"episodes": ["demo"]})
        self.assertEqual(json.loads(self.request("/api/episodes/demo")[1])["frame_count"], 3)
        annotation = {"annotator": "tester", "spans": [{"start_index": 1, "end_index": 3, "text": "place"}]}
        status, body = self.request(
            "/api/episodes/demo/annotation", "PUT", annotation,
            {"Content-Type": "application/json", "Origin": self.base_url},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["spans"][0]["text"], "place")
        self.assertEqual(load_annotation(self.root / "demo").spans[0].end_index, 3)

    def test_rejects_invalid_input_and_cross_origin(self):
        annotation = {"annotator": "tester", "spans": []}
        self.assertEqual(self.request("/api/episodes/../demo")[0], 404)
        self.assertEqual(self.request("/api/episodes/demo/annotation", "PUT", annotation, {"Content-Type": "application/json", "Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.request("/api/episodes/demo/annotation", "PUT", annotation, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/episodes/demo/annotation", "PUT", {"annotator": "", "spans": []}, {"Content-Type": "application/json"})[0], 400)
        request = Request(self.base_url + "/", headers={"Host": "example.org"})
        with self.assertRaises(HTTPError) as error:
            urlopen(request, timeout=3)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()


if __name__ == "__main__":
    unittest.main()
