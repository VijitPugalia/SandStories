import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import analyze_depth_diagnostic
from scripts import visualize_sandstories_session


class V2StreamToolTests(unittest.TestCase):
    def make_v2_session(self, root: Path) -> tuple[dict, dict]:
        session = root / "session_test"
        streams = session / "streams"
        streams.mkdir(parents=True)

        raw0 = np.array([[1.0, 1.1], [1.2, 1.3]], dtype="<f4")
        raw1 = np.array([[1.0, 1.1], [1.25, 1.4]], dtype="<f4")
        smoothed0 = np.array([[1.0, 1.1], [1.2, 1.3]], dtype="<f4")
        smoothed1 = np.array([[1.0, 1.1], [1.22, 1.32]], dtype="<f4")
        (streams / "depth.f32").write_bytes(raw0.tobytes() + raw1.tobytes())
        (streams / "smoothed_depth.f32").write_bytes(smoothed0.tobytes() + smoothed1.tobytes())
        (streams / "confidence.bin").write_bytes(bytes([2, 2, 1, 0, 2, 2, 2, 1]))

        manifest = {
            "schemaVersion": 1,
            "captureFormat": "v2_streams",
            "sessionId": "test",
            "v2Streams": {
                "formatVersion": 2,
                "frameMetadataFile": "v2_frames.jsonl",
                "rgbVideoPath": "streams/rgb.mp4",
                "rgbVideoCodec": "h264_mp4",
                "depthStreamPath": "streams/depth.f32",
                "depthFormat": "float32_little_endian_meters_contiguous",
                "smoothedDepthStreamPath": "streams/smoothed_depth.f32",
                "confidenceStreamPath": "streams/confidence.bin",
                "note": "test",
            },
            "diagnostic": {
                "enabled": True,
                "profile": "depth_diagnostic_raw_plus_smoothed",
                "durationSeconds": 20,
                "capturesSmoothedDepth": True,
                "forcedDeltaThresholdU16": 0,
                "enabledFrameSemantics": ["sceneDepth", "smoothedSceneDepth"],
                "counters": {"framesWritten": 2, "confidenceFramesAvailable": 2},
            },
        }
        frame0 = {
            "frameIndex": 1,
            "arTimestamp": 0.0,
            "monotonicElapsedSeconds": 0.0,
            "selectedDepthSource": "sceneDepth",
            "width": 2,
            "height": 2,
            "sourceDepthPixelFormat": "DepthFloat32",
            "depthBytesPerRow": 8,
            "storedDepthFormat": "float32_little_endian_meters",
            "depthByteOffset": 0,
            "depthByteCount": 16,
            "smoothedDepthByteOffset": 0,
            "smoothedDepthByteCount": 16,
            "smoothedDepthPixelFormat": "DepthFloat32",
            "smoothedDepthWidth": 2,
            "smoothedDepthHeight": 2,
            "smoothedDepthBytesPerRow": 8,
            "confidenceByteOffset": 0,
            "confidenceByteCount": 4,
            "confidencePixelFormat": "OneComponent8",
            "confidenceWidth": 2,
            "confidenceHeight": 2,
            "confidenceBytesPerRow": 2,
            "rgbDisplayZoomFactor": 0.5,
            "rgbDeviceZoomFactor": 1.0,
            "rgbActiveLens": "Ultra Wide",
            "cameraTransformColumnMajor": [0.0] * 16,
            "cameraIntrinsicsColumnMajor": [0.0] * 9,
            "cameraImageResolutionWidth": 4,
            "cameraImageResolutionHeight": 4,
        }
        frame1 = dict(frame0)
        frame1.update(
            {
                "frameIndex": 2,
                "arTimestamp": 1.0,
                "monotonicElapsedSeconds": 1.0,
                "depthByteOffset": 16,
                "smoothedDepthByteOffset": 16,
                "confidenceByteOffset": 4,
            }
        )
        (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        with (session / "v2_frames.jsonl").open("w", encoding="utf-8") as f:
            f.write(json.dumps(frame0) + "\n")
            f.write(json.dumps(frame1) + "\n")
        return manifest, frame1

    def test_visualizer_reads_v2_depth_and_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, frame = self.make_v2_session(root)
            session = root / "session_test"

            raw = visualize_sandstories_session.read_v2_depth(session, manifest, frame, "raw")
            smoothed = visualize_sandstories_session.read_v2_depth(session, manifest, frame, "smoothed")
            confidence = visualize_sandstories_session.read_v2_confidence(session, manifest, frame)

            self.assertAlmostEqual(float(raw[1, 1]), 1.4)
            self.assertAlmostEqual(float(smoothed[1, 1]), 1.32, places=5)
            self.assertEqual(confidence.tolist(), [[2, 2], [2, 1]])

    def test_analyzer_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_v2_session(root)
            session = root / "session_test"

            report = analyze_depth_diagnostic.analyze(session)

            self.assertEqual(report["v2FrameCount"], 2)
            self.assertTrue((session / "depth_diagnostic_report.json").is_file())
            self.assertTrue((session / "depth_diagnostic_contactsheet.png").is_file())

    def test_smoothed_primary_payload_is_not_reported_as_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, _ = self.make_v2_session(root)
            session = root / "session_test"
            metadata_path = session / "v2_frames.jsonl"
            frames = [json.loads(line) for line in metadata_path.read_text(encoding="utf-8").splitlines()]
            for frame in frames:
                frame["selectedDepthSource"] = "smoothedSceneDepth"
                for key in (
                    "smoothedDepthByteOffset",
                    "smoothedDepthByteCount",
                    "smoothedDepthPixelFormat",
                    "smoothedDepthWidth",
                    "smoothedDepthHeight",
                    "smoothedDepthBytesPerRow",
                ):
                    frame.pop(key, None)
            metadata_path.write_text("\n".join(json.dumps(frame) for frame in frames) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "raw sceneDepth is unavailable"):
                visualize_sandstories_session.read_v2_depth(session, manifest, frames[1], "raw")
            smoothed = visualize_sandstories_session.read_v2_depth(session, manifest, frames[1], "smoothed")
            self.assertAlmostEqual(float(smoothed[1, 1]), 1.4)

            report = analyze_depth_diagnostic.analyze(session)
            self.assertEqual(report["classification"], "raw_depth_unavailable_smoothed_only")
            self.assertIsNone(report["sampledFrames"][0]["rawDepth"])
            self.assertIsNotNone(report["sampledFrames"][0]["smoothedDepth"])


if __name__ == "__main__":
    unittest.main()
