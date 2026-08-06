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

    def test_media_probe_permission_error_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            media_path = Path(tmp) / "audio.m4a"
            media_path.write_bytes(b"test")
            with mock.patch("scripts.evaluate_session.subprocess.run", side_effect=PermissionError):
                self.assertEqual(evaluate_session.get_media_duration(media_path), 0.0)


if __name__ == "__main__":
    unittest.main()
