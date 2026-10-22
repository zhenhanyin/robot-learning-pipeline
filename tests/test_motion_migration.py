import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from robot_learning.adapters.arx_x5 import ArxCommandAdapter, import_legacy_arx_episode, read_legacy_arx_commands, read_legacy_arx_frame
from robot_learning.adapters.piper import PiperCommandAdapter
from robot_learning.apps.arx_replay import ArxReplayConfig, load_replay_config, publish_arx_ros2, publish_replay, replay_plan
from robot_learning.apps.control_web import PiperRos1ControlBackend, TOPICS, make_handler
from robot_learning.core.models import ArmState, RobotCommand
from robot_learning.formats.images import rgb_array
from robot_learning.formats.episode import EpisodeReader
from robot_learning.formats.validation import validate_episode
from robot_learning.apps.preview import frame_preview_png
from robot_learning.policies import PolicySpec, load_component, load_policy
from robot_learning.workflows.task_orchestration import TaskDefinition, TaskError, TaskOrchestrator
from robot_learning.workflows.policy_preview import OfflinePolicyRunner
from robot_learning.workflows.motion import NoopStateReader, dispatch_commands, interpolate, is_noop
from robot_learning.workflows.policy_preview import SafetyEnvelope, SafetyStop


class FakePiper:
    def __init__(self):
        self.calls = []
        self.motor_enabled = False

    def EnableArm(self, motor_number):
        self.calls.append(("enable", motor_number))
        self.motor_enabled = True

    def GetArmLowSpdInfoMsgs(self):
        motor = SimpleNamespace(foc_status=SimpleNamespace(driver_enable_status=self.motor_enabled))
        return SimpleNamespace(**{"motor_{}".format(index): motor for index in range(1, 7)})

    def MotionCtrl_2(self, *values):
        self.calls.append(("mode", values))

    def JointCtrl(self, *values):
        self.calls.append(("joints", values))

    def GripperCtrl(self, *values):
        self.calls.append(("gripper", values))

    def MotionCtrl_1(self, *values):
        self.calls.append(("stop", values))


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeNode:
    def __init__(self):
        self.publisher = FakePublisher()

    def create_publisher(self, message_type, topic, queue_size):
        self.topic = topic
        return self.publisher

    def get_clock(self):
        return SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: "stamp"))


class FakeRobotCmd:
    def __init__(self):
        self.header = SimpleNamespace(stamp=None)


class MigrationMotionTests(unittest.TestCase):
    def setUp(self):
        self.envelope = SafetyEnvelope("left", (-2.0,) * 6, (2.0,) * 6,
                                       (0.2,) * 6, 100, 10, 100,
                                       0.0, 1.0, 0.2)
        self.state = ArmState("left", 100, (0.0,) * 6, 0.2)

    def test_piper_write_is_explicit_and_scaled(self):
        sdk = FakePiper()
        adapter = PiperCommandAdapter(sdk, "left", 1000, 1000)
        command = RobotCommand("left", 100, (0.1,) * 6, 0.3)
        with self.assertRaisesRegex(RuntimeError, "not enabled"):
            adapter.send_command(command)
        adapter.enable()
        adapter.send_command(command)
        adapter.stop()
        self.assertEqual(sdk.calls, [("enable", 7), ("mode", (1, 1, 30)),
                                     ("joints", (100,) * 6),
                                     ("gripper", (300, 1000, 1, 0)),
                                     ("stop", (1, 0, 0))])
        with self.assertRaisesRegex(RuntimeError, "not enabled"):
            adapter.send_command(command)
        with self.assertRaises(ValueError):
            PiperCommandAdapter(sdk, "left", 0, 1000)

    def test_piper_enable_rejects_unconfirmed_motors(self):
        sdk = FakePiper()
        sdk.EnableArm = lambda motor_number: None
        adapter = PiperCommandAdapter(sdk, "left", 1000, 1000)
        with self.assertRaises(TimeoutError):
            adapter.enable(timeout_seconds=0)
        self.assertFalse(adapter.enabled)
        self.assertEqual(sdk.calls, [])

    def test_arx_command_mapping_and_limits(self):
        node = FakeNode()
        adapter = ArxCommandAdapter(node, FakeRobotCmd)
        command = RobotCommand("left", 100, (0.1,) * 6, 0.3)
        with self.assertRaisesRegex(SafetyStop, "explicit enable"):
            dispatch_commands(adapter, self.state, (command,), self.envelope, 110)
        self.assertEqual(dispatch_commands(adapter, self.state, (command,), self.envelope, 110, True), 1)
        message = node.publisher.messages[0]
        self.assertEqual((node.topic, message.mode, message.header.stamp), ("/arm_cmd", 5, "stamp"))
        self.assertEqual((message.joint_pos, message.gripper), ([0.1] * 6, 0.3))
        with self.assertRaisesRegex(SafetyStop, "maximum step"):
            dispatch_commands(adapter, self.state, (RobotCommand("left", 100, (0.5,) * 6, 0.3),),
                              self.envelope, 110, True)
        self.assertEqual(len(node.publisher.messages), 1)
        with self.assertRaisesRegex(SafetyStop, "stale"):
            dispatch_commands(adapter, self.state, (command,), self.envelope, 201, True)

    def test_interpolation_and_noop_preserve_gripper_changes(self):
        target = RobotCommand("left", 100, (0.2,) * 6, 0.4)
        points = interpolate(self.state, target, 2)
        self.assertEqual(points[0].joint_targets, (0.1,) * 6)
        self.assertEqual(points[-1], target)
        self.assertTrue(is_noop(target, RobotCommand("left", 200, (0.2,) * 6, 0.4), 0.01))
        self.assertFalse(is_noop(target, RobotCommand("left", 200, (0.2,) * 6, 0.5), 0.01))

    def test_state_filter_preserves_gripper_change(self):
        from robot_learning.core.errors import StaleSampleError

        states = iter((self.state, ArmState("left", 200, (0.0,) * 6, 0.2),
                       ArmState("left", 300, (0.0,) * 6, 0.3)))
        reader = NoopStateReader(SimpleNamespace(read_state=lambda: next(states)), 0.01)
        self.assertEqual(reader.read_state().timestamp_ns, 100)
        with self.assertRaises(StaleSampleError):
            reader.read_state()
        self.assertEqual(reader.read_state().gripper_position, 0.3)

    def test_legacy_hdf5_and_fake_replay(self):
        import h5py
        import numpy as np

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "old.hdf5"
            with h5py.File(source, "w") as recording:
                group = recording.create_group("joint_action")
                group.create_dataset("left_arm", data=np.array([[0.1] * 6, [0.1] * 6, [0.2] * 6]))
                group.create_dataset("left_gripper", data=np.array([0.3, 0.3, 0.4]))
            commands = read_legacy_arx_commands(source, 10)
            self.assertEqual(len(commands), 3)
            self.assertEqual(len(replay_plan(source, 10, 0.01)), 2)
            adapter = ArxCommandAdapter(FakeNode(), FakeRobotCmd)
            sleeps = []
            states = iter((self.state, ArmState("left", 100, (0.1,) * 6, 0.3)))
            count = publish_replay(replay_plan(source, 10, 0.01), adapter,
                                   lambda: next(states), lambda: 110, self.envelope, 10,
                                   sleeps.append)
            self.assertEqual((count, sleeps), (2, [0.2]))
            self.assertEqual(len(adapter.publisher.messages), 2)
            with h5py.File(source, "r+") as recording:
                recording["joint_action/left_arm"][0, 0] = np.nan
            with self.assertRaisesRegex(ValueError, "non-finite"):
                read_legacy_arx_commands(source, 10)

    def test_legacy_jpeg_camera_mapping(self):
        import h5py
        import numpy as np
        from io import BytesIO
        from PIL import Image

        output = BytesIO()
        Image.new("RGB", (2, 1), (20, 30, 40)).save(output, format="JPEG")
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "old.hdf5"
            with h5py.File(source, "w") as recording:
                payload = output.getvalue()
                recording.create_dataset("observation/head_camera/rgb",
                                         data=np.asarray([payload], dtype="|S{}".format(len(payload))))
            frame = read_legacy_arx_frame(source, "head", 0, 30)
            self.assertEqual((frame.encoding, frame.width, frame.height), ("jpeg", 2, 1))
            self.assertEqual(rgb_array(frame).shape, (1, 2, 3))
            self.assertTrue(frame_preview_png(frame.encoding, frame.width, frame.height,
                                              frame.payload).startswith(b"\x89PNG"))
            with self.assertRaisesRegex(ValueError, "missing"):
                read_legacy_arx_frame(source, "left_wrist", 0, 30)

    def test_import_legacy_arx_as_state_only_episode(self):
        import h5py
        import numpy as np
        from io import BytesIO
        from PIL import Image

        image = BytesIO()
        Image.new("RGB", (1, 1), (4, 5, 6)).save(image, format="JPEG")
        payload = image.getvalue()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "old.hdf5"
            destination = Path(temporary) / "episode"
            with h5py.File(source, "w") as recording:
                recording.create_dataset("joint_action/left_arm", data=np.zeros((2, 6)))
                recording.create_dataset("joint_action/left_gripper", data=np.zeros(2))
                recording.create_dataset("observation/head_camera/rgb",
                                         data=np.asarray([payload, payload], dtype="|S{}".format(len(payload))))
            self.assertEqual(import_legacy_arx_episode(source, destination, 10, ("head",)), 2)
            self.assertTrue(validate_episode(destination).valid)
            self.assertEqual(EpisodeReader(destination).metadata["clock_domain"],
                             "synthetic_index_from_rate")
            self.assertEqual(len(list(EpisodeReader(destination).records())), 4)
            with h5py.File(source, "r+") as recording:
                recording["observation/head_camera/rgb"][1] = b"bad"
            failed_destination = Path(temporary) / "failed"
            with self.assertRaisesRegex(ValueError, "JPEG"):
                import_legacy_arx_episode(source, failed_destination, 10, ("head",))
            self.assertFalse(failed_destination.exists())

    def test_replay_config_requires_verified_units(self):
        data = {"topic": "/arm_cmd", "status_topic": "/arm_status", "rate_hz": 10,
                "joint_units": "rad", "gripper_units": "m", "joint_min": [-2] * 6,
                "joint_max": [2] * 6, "max_joint_step": [0.2] * 6,
                "gripper_min": 0, "gripper_max": 1, "max_gripper_step": 0.2,
                "max_observation_age_ms": 100}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "limits.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(load_replay_config(path).envelope.joint_min, (-2,) * 6)
            data["joint_units"] = "arx_raw_joint_unit_unverified"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "verified"):
                load_replay_config(path)

    def test_fake_ros2_wires_status_and_robot_command(self):
        class RosNode(FakeNode):
            def create_subscription(self, message_type, topic, callback, queue_size):
                self.callback = callback

            def get_clock(self):
                return SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=110,
                                                                    to_msg=lambda: "stamp"))

            def destroy_node(self):
                self.destroyed = True

        class RosRuntime:
            def __init__(self):
                self.node = RosNode()
                self.stopped = False

            def init(self):
                pass

            def create_node(self, name):
                return self.node

            def spin_once(self, node, timeout_sec):
                node.callback(SimpleNamespace(
                    header=SimpleNamespace(stamp=SimpleNamespace(sec=0, nanosec=100)),
                    joint_pos=[0.0] * 6 + [0.2], joint_vel=[0.0] * 7))

            def shutdown(self):
                self.stopped = True

        ros = RosRuntime()
        config = ArxReplayConfig("/arm_cmd", "/arm_status", 10, "rad", "m", self.envelope)
        command = RobotCommand("left", 100, (0.1,) * 6, 0.3)
        self.assertEqual(publish_arx_ros2((command,), config, ros=ros,
                                          message_type=FakeRobotCmd, status_type=object), 1)
        self.assertEqual(ros.node.publisher.messages[0].joint_pos, [0.1] * 6)
        self.assertTrue(ros.node.destroyed)
        self.assertTrue(ros.stopped)


class ControlBridgeTests(unittest.TestCase):
    def test_legacy_ros_service_and_topic_mapping(self):
        class FakeRos:
            def __init__(self):
                self.publishers = {}
                self.calls = []

            def init_node(self, name, anonymous):
                self.node_name = name

            def ServiceProxy(self, path, service_type):
                def call(*args):
                    self.calls.append((path, args))
                    return SimpleNamespace(success=True, message='{"count": 2}' if path.endswith("record_num") else "ok")
                return call

            def Publisher(self, topic, message_type, queue_size):
                publisher = FakePublisher()
                self.publishers[topic] = publisher
                return publisher

        ros = FakeRos()
        messages = SimpleNamespace(Bool=lambda data: SimpleNamespace(data=data),
                                   String=lambda data: SimpleNamespace(data=data))
        backend = PiperRos1ControlBackend(ros, SimpleNamespace(SetBool=object, Trigger=object), messages)
        self.assertEqual(backend.query("query_record_num")["message"], {"count": 2})
        self.assertTrue(backend.set_switch(True)["success"])
        with self.assertRaises(ValueError):
            backend.set_switch("true")
        backend.action("sweep")
        backend.action("vla")
        backend.action("obj", "Water COFFEE")
        self.assertTrue(ros.publishers[TOPICS["sweep"]].messages[0].data)
        self.assertEqual(ros.publishers["/change_mode_vla_or_return/"].messages[0].data, "use_vla")
        self.assertEqual(ros.publishers["/arm_control/franka_msg"].messages[0].data, "water coffee")


class ControlHttpTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls

        class Backend:
            def query(self, name):
                calls.append(("query", name))
                return {"success": True, "message": "ok"}

            def set_switch(self, enabled):
                calls.append(("switch", enabled))
                return {"success": True}

            def action(self, name, value):
                calls.append((name, value))
                return {"success": True}

        self.server = HTTPServer(("127.0.0.1", 0), make_handler(Backend()))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = "http://127.0.0.1:{}".format(self.server.server_port)

    def request(self, path, payload=None, origin=None):
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path,
                          data=None if payload is None else json.dumps(payload).encode("utf-8"),
                          headers=headers, method="GET" if payload is None else "POST")
        try:
            with urlopen(request, timeout=3) as response:
                return response.status
        except HTTPError as error:
            with error:
                return error.code

    def test_read_and_write_routes_and_origin(self):
        self.assertEqual(self.request("/api/query_switch"), 200)
        self.assertEqual(self.request("/api/set_switch"), 404)
        self.assertEqual(self.request("/api/set_switch", {"switch_state": True}, self.base_url), 200)
        self.assertEqual(self.request("/api/sweep", {}, self.base_url), 200)
        self.assertEqual(self.request("/api/obj", {"text": "cup"}, self.base_url), 200)
        self.assertEqual(self.request("/api/sweep", {}, "https://example.org"), 403)
        self.assertEqual(self.request("/api/obj", {"wrong": "cup"}, self.base_url), 400)
        self.assertEqual(self.calls, [("query", "query_switch"), ("switch", True),
                                      ("sweep", ""), ("obj", "cup")])


class PolicyAndTaskMigrationTests(unittest.TestCase):
    def test_load_external_backend_without_vendoring(self):
        backend = load_component("types:SimpleNamespace", {"get_chunk": lambda observation: [[0.1]]})
        self.assertTrue(callable(backend.get_chunk))
        spec = PolicySpec("act", {"head": "head"}, 1)
        policy = load_policy(spec, "test_motion_migration:FakePolicyFactory", image_format="bytes")
        state = ArmState("left", 100, (0.0,))
        from robot_learning.core.models import CameraFrame
        commands = policy.predict(state, (CameraFrame("head", 100, "raw8", 1, 1, b"\x00"),))
        self.assertEqual(commands[0].joint_targets, (0.1,))
        with self.assertRaisesRegex(ValueError, "implement"):
            load_policy(spec, "types:SimpleNamespace")

    def test_approved_task_can_dispatch_to_injected_adapter(self):
        from robot_learning.core.models import CameraFrame

        state = ArmState("left", 100, (0.0,))
        frame = CameraFrame("head", 100, "raw8", 1, 1, b"\x00")
        envelope = SafetyEnvelope("left", (-1.0,), (1.0,), (0.5,), 100, 10, 100)
        runner = OfflinePolicyRunner(load_policy(
            PolicySpec("act", {"head": "head"}, 1),
            "test_motion_migration:FakePolicyFactory", image_format="bytes"),
            envelope, lambda: 0)
        vision = SimpleNamespace(select_task=lambda transcript, frames: "pick")
        orchestrator = TaskOrchestrator(None, vision, lambda: (state, (frame,), 110),
                                        {"pick": TaskDefinition("pick", "Pick", runner)})
        adapter = SimpleNamespace(send_command=lambda command: commands.append(command))
        commands = []
        proposal = orchestrator.propose_text("pick")
        with self.assertRaises(TaskError):
            orchestrator.execute(adapter, proposal["proposal_id"])
        orchestrator.approve(proposal["proposal_id"])
        result = orchestrator.execute(adapter, proposal["proposal_id"])
        self.assertTrue(result["command_published"])
        self.assertEqual(len(commands), 1)
        self.assertEqual(result["phase"], "completed")

    def test_stop_during_execution_remains_stopped(self):
        from robot_learning.core.models import CameraFrame

        state = ArmState("left", 100, (0.0,))
        frame = CameraFrame("head", 100, "raw8", 1, 1, b"\x00")
        envelope = SafetyEnvelope("left", (-1.0,), (1.0,), (0.5,), 100, 10, 100)
        runner = OfflinePolicyRunner(load_policy(
            PolicySpec("act", {"head": "head"}, 1),
            "test_motion_migration:FakePolicyFactory", image_format="bytes"),
            envelope, lambda: 0)
        orchestrator = TaskOrchestrator(None, SimpleNamespace(select_task=lambda text, frames: "pick"),
                                        lambda: (state, (frame,), 110),
                                        {"pick": TaskDefinition("pick", "Pick", runner)})
        proposal = orchestrator.propose_text("pick")
        orchestrator.approve(proposal["proposal_id"])
        adapter = SimpleNamespace(send_command=lambda command: orchestrator.stop())
        with self.assertRaisesRegex(TaskError, "execution failed"):
            orchestrator.execute(adapter, proposal["proposal_id"])
        self.assertEqual(orchestrator.status()["phase"], "stopped")


def FakePolicyFactory():
    return SimpleNamespace(get_chunk=lambda observation: [[0.1]])


if __name__ == "__main__":
    unittest.main()
