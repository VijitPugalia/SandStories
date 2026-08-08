import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import evaluate_session


class EvaluateSessionTests(unittest.TestCase):
    def test_v2_metrics_use_declared_metadata_and_media_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            metadata_dir = session / "metadata"
            metadata_dir.mkdir()
            frames = [
                {"frameIndex": index + 1, "monotonicElapsedSeconds": index / 15.0}
                for index in range(30)
            ]
            (metadata_dir / "frames.jsonl").write_text(
                "\n".join(json.dumps(frame) for frame in frames) + "\n",
                encoding="utf-8",
            )
            derived_dir = session / "derived"
            derived_dir.mkdir()
            (session / "objects.jsonl").write_text("", encoding="utf-8")
            (derived_dir / "objects_yolo_world.jsonl").write_text(
                json.dumps(
                    {
                        "frame_index": 0,
                        "detections": [
                            {"class": "figurine", "confidence": 0.5},
                            {"class": "cup", "confidence": 0.9},
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (session / "strokes.json").write_text("[]", encoding="utf-8")
            (session / "boundary_samples.jsonl").write_text(
                json.dumps({"monotonicElapsedSeconds": 1.0, "confidence": 0.5}) + "\n",
                encoding="utf-8",
            )
            (session / "audio.m4a").write_bytes(b"test")
            manifest = {
                "sessionId": "v2-test",
                "captureFormat": "v2_streams",
                "monotonicSessionEndElapsedSeconds": 2.0,
                "depthFrames": [],
                "v2Streams": {"frameMetadataFile": "metadata/frames.jsonl"},
                "objectDetectionsFile": "objects.jsonl",
                "strokesFile": "strokes.json",
                "boundarySamplesFile": "boundary_samples.jsonl",
                "audio": {
                    "relativePath": "audio.m4a",
                    "startMonotonicElapsedSeconds": 0.5,
                    "durationSeconds": 0.0,
                },
            }
            (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            with mock.patch.object(evaluate_session, "get_media_duration", return_value=1.4):
                report = evaluate_session.evaluate_session(session)

            self.assertEqual(report["metrics"]["depthRetention"], 1.0)
            self.assertAlmostEqual(report["metrics"]["objectDetectionConfidence"], 0.7)
            self.assertAlmostEqual(report["metrics"]["audioContinuity"], 1.4 / 1.5)
            self.assertEqual(report["observations"]["depthFrameCount"], 30)
            self.assertEqual(report["observations"]["objectDetectionCount"], 2)
            self.assertEqual(report["observations"]["objectDetectionSource"], "derived/objects_yolo_world.jsonl")
            self.assertEqual(report["dropoutCount"], 0)
            self.assertEqual(report["metrics"]["gestureContinuity"], 0.0)

    def test_media_probe_permission_error_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_path = Path(tmp) / "audio.m4a"
            media_path.write_bytes(b"test")
            with mock.patch("scripts.evaluate_session.subprocess.run", side_effect=PermissionError):
                self.assertEqual(evaluate_session.get_media_duration(media_path), 0.0)


    def test_zero_confidence_boundary_stays_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            (session / "strokes.json").write_text("[]", encoding="utf-8")
            (session / "boundary_samples.jsonl").write_text(
                json.dumps({"monotonicElapsedSeconds": 0.5, "confidence": 0.0}) + "\n",
                encoding="utf-8",
            )
            manifest = {
                "sessionId": "zero-boundary",
                "monotonicSessionEndElapsedSeconds": 1.0,
                "depthFrames": [],
                "strokesFile": "strokes.json",
                "boundarySamplesFile": "boundary_samples.jsonl",
            }
            (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            report = evaluate_session.evaluate_session(session, output_dir=session / "derived-evaluation")
            self.assertEqual(report["metrics"]["boundaryDetection"], 0.0)

    def test_invalid_stream_offset_fails_package_without_mutating_raw_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "session"
            streams = session / "streams"
            streams.mkdir(parents=True)
            (streams / "depth.f32").write_bytes(b"1234")
            (streams / "rgb.mp4").write_bytes(b"rgb")
            (session / "audio.m4a").write_bytes(b"audio")
            (session / "strokes.json").write_text("[]", encoding="utf-8")
            (session / "boundary_samples.jsonl").write_text("", encoding="utf-8")
            frame = {
                "frameIndex": 1,
                "monotonicElapsedSeconds": 0.1,
                "depthByteOffset": 2,
                "depthByteCount": 4,
            }
            (session / "v2_frames.jsonl").write_text(json.dumps(frame) + "\n", encoding="utf-8")
            (session / "conditions.json").write_text(
                json.dumps(
                    {
                        "sensorHeightCm": 80,
                        "lighting": "shade",
                        "surfaceType": "dry",
                        "replicate": 1,
                    }
                ),
                encoding="utf-8",
            )
            (session / "sync_check.json").write_text(
                json.dumps(
                    {
                        "rgbTimeSeconds": 0.10,
                        "depthTimeSeconds": 0.20,
                        "audioTimeSeconds": 0.25,
                    }
                ),
                encoding="utf-8",
            )
            manifest = {
                "sessionId": "bad-offset",
                "captureFormat": "v2_streams",
                "monotonicSessionEndElapsedSeconds": 1.0,
                "depthFrames": [],
                "v2Streams": {
                    "frameMetadataFile": "v2_frames.jsonl",
                    "depthStreamPath": "streams/depth.f32",
                    "rgbVideoPath": "streams/rgb.mp4",
                },
                "strokesFile": "strokes.json",
                "boundarySamplesFile": "boundary_samples.jsonl",
                "audio": {
                    "relativePath": "audio.m4a",
                    "startMonotonicElapsedSeconds": 0.0,
                    "durationSeconds": 1.0,
                },
            }
            (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            output_dir = Path(tmp) / "derived" / "bad-offset"

            report = evaluate_session.evaluate_session(session, output_dir=output_dir)

            self.assertFalse(report["packageValid"])
            self.assertTrue(any("exceeds depth.f32 size" in error for error in report["validationErrors"]))
            self.assertTrue(report["observations"]["sync"]["within250ms"])
            self.assertTrue((output_dir / "evaluation_report.json").is_file())
            self.assertFalse((session / "evaluation_report.json").exists())
            self.assertFalse((session / "dropouts.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
