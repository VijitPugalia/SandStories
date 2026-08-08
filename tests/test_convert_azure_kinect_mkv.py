import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import convert_azure_kinect_mkv
from scripts import evaluate_session


class FakeCapture:
    def __init__(
        self,
        depth,
        transformed_color,
        *,
        depth_timestamp_usec,
        color_timestamp_usec,
        color=None,
    ):
        self.depth = depth
        self.transformed_color = transformed_color
        self.color = color
        self.depth_timestamp_usec = depth_timestamp_usec
        self.color_timestamp_usec = color_timestamp_usec
        self.temperature = 31.5


class FakeVideoSink:
    def __init__(self, path, width, height, fps):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.frames = []

    def write(self, frame):
        self.frames.append(np.array(frame, copy=True))

    def close(self):
        if self.frames:
            self.path.write_bytes(b"synthetic-rgb-video")


class AzureKinectConverterTests(unittest.TestCase):
    def test_native_depth_and_aligned_color_make_valid_v2_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session_azure_test"
            session.mkdir()
            (session / "conditions.json").write_text(
                json.dumps(
                    {
                        "sensorHeightCm": 80,
                        "lighting": "indoor",
                        "surfaceType": "dry",
                        "replicate": 1,
                    }
                ),
                encoding="utf-8",
            )
            audio = session / "audio.wav"
            audio.write_bytes(b"synthetic-audio")

            depth0 = np.array([[1000, 0], [1250, 2000]], dtype=np.uint16)
            depth1 = np.array([[1005, 1010], [1260, 2010]], dtype=np.uint16)
            color0 = np.full((2, 2, 4), [10, 20, 30, 255], dtype=np.uint8)
            color1 = np.full((2, 2, 4), [40, 50, 60, 255], dtype=np.uint8)
            captures = [
                FakeCapture(
                    depth0,
                    color0,
                    depth_timestamp_usec=1_000_000,
                    color_timestamp_usec=1_002_000,
                ),
                FakeCapture(
                    depth1,
                    color1,
                    depth_timestamp_usec=1_033_333,
                    color_timestamp_usec=1_035_000,
                ),
            ]
            intrinsics = np.array(
                [[500.0, 0.0, 1.0], [0.0, 501.0, 1.0], [0.0, 0.0, 1.0]],
                dtype=np.float64,
            )

            manifest = convert_azure_kinect_mkv.convert_capture_sequence(
                captures,
                session,
                session_id="azure_test",
                fps=30.0,
                depth_intrinsics=intrinsics,
                source_mkv="source/azure_kinect.mkv",
                recording_metadata={
                    "kinectStartedUtc": "2026-08-07T00:00:00+00:00",
                    "audioStartedUtc": "2026-08-06T23:59:59.950000+00:00",
                },
                audio_path=audio,
                audio_duration_seconds=1.0,
                video_sink_factory=FakeVideoSink,
            )

            depth_values = np.fromfile(session / "streams" / "depth.f32", dtype="<f4")
            records = [
                json.loads(line)
                for line in (session / "v2_frames.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            report = evaluate_session.evaluate_session(
                session,
                output_dir=session / "derived" / "evaluation",
            )

            self.assertEqual(manifest["captureDeviceFamily"], "azure_kinect_dk")
            self.assertEqual(manifest["azureKinect"]["sourceMkv"], "source/azure_kinect.mkv")
            self.assertEqual(
                manifest["azureKinect"]["rgbAlignmentMethods"],
                ["k4a_calibration_transformed_color_to_depth"],
            )
            self.assertAlmostEqual(manifest["azureKinect"]["audioStartOffsetSecondsExact"], -0.05)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["depthByteOffset"], 0)
            self.assertEqual(records[1]["depthByteOffset"], 16)
            self.assertEqual(records[1]["depthByteCount"], 16)
            self.assertEqual(len(records[0]["cameraTransformColumnMajor"]), 16)
            self.assertEqual(len(records[0]["cameraIntrinsicsColumnMajor"]), 9)
            self.assertAlmostEqual(float(depth_values[0]), 1.0)
            self.assertTrue(np.isnan(depth_values[1]))
            self.assertAlmostEqual(float(depth_values[-1]), 2.01, places=5)
            self.assertTrue(report["packageValid"], report["validationErrors"])

    def test_converter_refuses_uncalibrated_color_resize_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            capture = FakeCapture(
                np.ones((2, 2), dtype=np.uint16) * 1000,
                None,
                color=np.zeros((4, 4, 4), dtype=np.uint8),
                depth_timestamp_usec=1_000_000,
                color_timestamp_usec=1_000_000,
            )
            intrinsics = np.eye(3, dtype=np.float64)
            intrinsics[0, 0] = 500.0
            intrinsics[1, 1] = 500.0

            with self.assertRaisesRegex(RuntimeError, "Refusing an uncalibrated resize"):
                convert_azure_kinect_mkv.convert_capture_sequence(
                    [capture],
                    Path(tmp),
                    session_id="no_alignment",
                    fps=30.0,
                    depth_intrinsics=intrinsics,
                    video_sink_factory=FakeVideoSink,
                )


if __name__ == "__main__":
    unittest.main()
