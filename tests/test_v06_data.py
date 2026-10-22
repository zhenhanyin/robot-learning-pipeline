import json
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from io import BytesIO
from pathlib import Path

import h5py
import numpy as np
from PIL import Image

from robot_learning.adapters.arx_x5.legacy import import_legacy_arx_episode
from robot_learning.adapters.piper.legacy import import_legacy_run
from robot_learning.core.models import ActionSource, ArmAction, ArmState, CameraFrame
from robot_learning.formats.episode import EpisodeReader, JsonlEpisodeWriter
from robot_learning.formats.hdf5 import export_hdf5
from robot_learning.formats.images import depth_array, rgb_array
from robot_learning.formats.preprocessing import (
    action_statistics,
    denormalize_action,
    hdf5_action_statistics,
    normalize_action,
    smooth_gripper,
    smooth_hdf5_grippers,
)
from robot_learning.formats.training import load_training_episode
from robot_learning.formats.validation import validate_episode
from robot_learning.formats.video import preprocess_video, resample_indices, write_encoded_video_frames


def jpeg_bytes():
    output = BytesIO()
    Image.new("RGB", (2, 1), (20, 30, 40)).save(output, format="JPEG")
    return output.getvalue()


def png_bytes(mode="RGB"):
    output = BytesIO()
    if mode == "I;16":
        Image.fromarray(np.asarray([[1000, 2000]], dtype=np.uint16)).save(output, format="PNG")
    else:
        Image.new(mode, (2, 1), 20).save(output, format="PNG")
    return output.getvalue()


class ModelAndExportTests(unittest.TestCase):
    def test_pose_calibration_and_metadata_survive_hdf5_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            episode_dir = root / "episode"
            with JsonlEpisodeWriter(
                episode_dir, "arx_x5", "synthetic", "rad", "tick",
                {"end_effector_pose_units": "unknown", "source_format": "fixture"},
            ) as writer:
                for index in range(2):
                    timestamp = index * 100_000_000
                    writer.append_state(ArmState(
                        "left", timestamp, (float(index),) * 6, 0.2,
                        end_effector_pose=(0.1, 0.2, 0.3, 0.0, 0.0, 0.0, 1.0),
                        end_effector_pose_format="xyz_quaternion_xyzw",
                    ))
                    writer.append_action(ArmAction(
                        "left", timestamp, (float(index + 1),) * 6, ActionSource.LEADER_COMMAND, 0.3,
                    ))
                    writer.append_frame(CameraFrame(
                        "head", timestamp, "jpeg", 2, 1, jpeg_bytes(), "rgb",
                        (1.0, 0.0, 1.0, 0.0, 1.0, 0.5, 0.0, 0.0, 1.0),
                        (1.0,) * 12, (1.0,) * 16,
                    ))
            self.assertTrue(validate_episode(episode_dir).valid)
            episode = load_training_episode(episode_dir)
            output = root / "episode.hdf5"
            self.assertEqual(export_hdf5(episode, output), 2)
            with h5py.File(output, "r") as recording:
                self.assertEqual(recording["observation/end_effector_pose"].shape, (2, 7))
                self.assertEqual(recording["observation/images/head/intrinsic_cv"].shape, (2, 9))
                metadata = json.loads(recording.attrs["episode_metadata_json"])
                self.assertEqual(metadata["source_format"], "fixture")
                self.assertEqual(recording["observation/images/head/modality"].asstr()[0], "rgb")

    def test_camera_calibration_validation(self):
        with self.assertRaisesRegex(ValueError, "intrinsic_cv"):
            CameraFrame("head", 0, "rgb8", 1, 1, b"abc", intrinsic_cv=(1.0,))

    def test_depth_png_keeps_native_values_and_is_not_rgb(self):
        frame = CameraFrame("head_depth", 0, "png", 2, 1, png_bytes("I;16"), "depth")
        np.testing.assert_array_equal(depth_array(frame), np.asarray([[1000, 2000]], dtype=np.uint16))
        with self.assertRaisesRegex(ValueError, "depth frame"):
            rgb_array(frame)


class LegacyImportTests(unittest.TestCase):
    def test_arx_import_keeps_pose_calibration_and_empty_pointcloud_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy.hdf5"
            destination = root / "episode"
            payload = jpeg_bytes()
            with h5py.File(source, "w") as recording:
                recording.create_dataset("joint_action/left_arm", data=np.zeros((2, 6)))
                recording.create_dataset("joint_action/left_gripper", data=np.zeros(2))
                recording.create_dataset("endpose/left_endpose", data=np.ones((2, 7)))
                recording.create_dataset("pointcloud", shape=(2, 0), dtype=np.float32)
                for camera in ("head_camera", "left_camera"):
                    recording.create_dataset("observation/{}/rgb".format(camera),
                                             data=np.asarray([payload, payload], dtype="|S{}".format(len(payload))))
                    group = recording["observation/{}".format(camera)]
                    group.create_dataset("intrinsic_cv", data=np.tile(np.eye(3), (2, 1, 1)))
                    group.create_dataset("extrinsic_cv", data=np.tile(np.ones((3, 4)), (2, 1, 1)))
                    group.create_dataset("cam2world_gl", data=np.tile(np.eye(4), (2, 1, 1)))
            self.assertEqual(import_legacy_arx_episode(source, destination, 10), 2)
            reader = EpisodeReader(destination)
            self.assertEqual(reader.metadata["pointcloud"], {"source_shape": [2, 0], "stored": False})
            records = list(reader.records())
            self.assertEqual(records[0].end_effector_pose_format, "xyz_quaternion_xyzw")
            frames = [record for record in records if isinstance(record, CameraFrame)]
            self.assertEqual({frame.camera_id for frame in frames}, {"head", "left_wrist"})
            self.assertEqual(frames[0].intrinsic_cv, (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
            self.assertTrue(validate_episode(destination).valid)

    def test_piper_import_aligns_follower_endpose_and_depth(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "legacy"
            destination = root / "episode"
            image_root = source / "img"
            for directory in ("front_color", "wrist_color", "front_depth", "wrist_depth"):
                (image_root / directory).mkdir(parents=True)
            joint_record = struct.Struct(">ddiiiiii")
            gripper_record = struct.Struct(">ddiii")
            for name, values in (("follower_joint", 1), ("leader_joint", 2)):
                (source / name).write_bytes(b"".join(
                    joint_record.pack(10.0 + index * 0.1, 30.0, *([values + index] * 6))
                    for index in range(2)
                ))
            for name, value in (("follower_gripper", 100), ("leader_gripper", 200)):
                (source / name).write_bytes(b"".join(
                    gripper_record.pack((10.0 + index * 0.1) * 1_000_000_000, 30.0, value, 0, 0)
                    for index in range(2)
                ))
            (source / "follower_endpose").write_bytes(b"".join(
                joint_record.pack(10.0 + index * 0.1, 30.0, *([index + 10] * 6))
                for index in range(2)
            ))
            for index in range(2):
                timestamp = "{}_{}".format(10 + index // 10, (index % 10) * 100_000_000)
                (image_root / "front_color" / (timestamp + ".png")).write_bytes(png_bytes())
                (image_root / "wrist_color" / (timestamp + ".png")).write_bytes(png_bytes())
                for directory in ("front_depth", "wrist_depth"):
                    (image_root / directory / (timestamp + ".png")).write_bytes(png_bytes("I;16"))
            summary = import_legacy_run(source, destination, tolerance_ns=1_000_000)
            self.assertEqual(summary.written_samples, 2)
            reader = EpisodeReader(destination)
            state = next(record for record in reader.records() if isinstance(record, ArmState))
            self.assertEqual(state.end_effector_pose, (10.0,) * 6)
            self.assertEqual(state.end_effector_pose_format, "xyz_rpy")
            depth = next(record for record in reader.records()
                         if isinstance(record, CameraFrame) and record.modality == "depth")
            np.testing.assert_array_equal(depth_array(depth), np.asarray([[1000, 2000]], dtype=np.uint16))


class PreprocessingTests(unittest.TestCase):
    def test_statistics_normalization_and_gripper_smoothing(self):
        stats = action_statistics(((0, 5), (2, 5), (4, 5)))
        self.assertEqual(stats.mean, (2.0, 5.0))
        self.assertEqual(normalize_action((0, 5), stats), (-1.0, 0.0))
        self.assertEqual(denormalize_action((1, 0), stats), (4.0, 5.0))
        self.assertEqual(smooth_gripper((0, 0, 10, 10, 10), 3, 0, 1),
                         (0.0, 10 / 3, 20 / 3, 10.0, 10.0))
        with self.assertRaisesRegex(ValueError, "dimensions"):
            action_statistics(((1,), (1, 2)))

    def test_hdf5_statistics_and_atomic_gripper_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.hdf5"
            destination = root / "smoothed.hdf5"
            with h5py.File(source, "w") as recording:
                recording.create_dataset("action/joint_targets", data=np.asarray([[0.0, 1.0], [2.0, 3.0]]))
                recording.create_dataset("action/gripper_target", data=np.asarray([0.0, 1.0]))
                recording.create_dataset("endpose/left_gripper", data=np.asarray([0.0, 0.0, 10.0, 10.0, 10.0]))
                recording.create_dataset("joint_action/left_gripper", data=np.asarray([0.0, 0.0, 10.0, 10.0, 10.0]))
                recording.create_dataset("joint_action/vector", data=np.tile(np.asarray([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]), (5, 1)))
            self.assertEqual(hdf5_action_statistics(source).count, 2)
            self.assertEqual(smooth_hdf5_grippers(source, destination, 3, 0.0, 1), 3)
            with h5py.File(source, "r") as original, h5py.File(destination, "r") as updated:
                np.testing.assert_array_equal(original["endpose/left_gripper"][:], [0, 0, 10, 10, 10])
                self.assertNotEqual(updated["endpose/left_gripper"][1], 0.0)
                self.assertIn("robot_learning_gripper_smoothing", updated.attrs)

    def test_video_frame_resampling_and_hdf5_copy(self):
        self.assertEqual(resample_indices(5, 3), (0, 2, 4))
        self.assertEqual(resample_indices(2, 1), (0,))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.hdf5"
            destination = root / "video.hdf5"
            with h5py.File(source, "w") as recording:
                recording.create_dataset("joint_action/left_arm", data=np.zeros((2, 6)))
            payload = jpeg_bytes()
            self.assertEqual(write_encoded_video_frames(
                source, destination, "head_camera", (payload, payload), 90,
            ), 2)
            with h5py.File(destination, "r") as recording:
                self.assertEqual(len(recording["observation/head_camera/rgb"]), 2)
                self.assertEqual(recording.attrs["robot_learning_video_preprocessing"],
                                 '{"camera_id": "head_camera", "frame_selection": "uniform_endpoint_inclusive", "jpeg_quality": 90, "source_timestamps_preserved": false}')

    def test_video_preprocess_wires_decoder_sampling_and_atomic_hdf5_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "episode.mp4"
            source = root / "source.hdf5"
            destination = root / "output.hdf5"
            video.write_bytes(b"fixture")
            with h5py.File(source, "w") as recording:
                recording.create_dataset("joint_action/left_arm", data=np.zeros((3, 6)))
            read_positions = []

            class Capture:
                position = 0

                def isOpened(self):
                    return True

                def get(self, property_id):
                    return 5

                def set(self, property_id, value):
                    self.position = value
                    read_positions.append(value)

                def read(self):
                    return True, np.zeros((1, 1, 3), dtype=np.uint8)

                def release(self):
                    return None

            fake_cv2 = SimpleNamespace(
                VideoCapture=lambda path: Capture(),
                CAP_PROP_FRAME_COUNT=7,
                CAP_PROP_POS_FRAMES=1,
                IMWRITE_JPEG_QUALITY=2,
                imencode=lambda extension, image, options: (
                    True, np.frombuffer(jpeg_bytes(), dtype=np.uint8),
                ),
            )
            with patch.dict(sys.modules, {"cv2": fake_cv2}):
                self.assertEqual(preprocess_video(video, source, destination, "head_camera"), 3)
            self.assertEqual(read_positions, [0, 2, 4])
            with h5py.File(destination, "r") as recording:
                self.assertEqual(len(recording["observation/head_camera/rgb"]), 3)


if __name__ == "__main__":
    unittest.main()
