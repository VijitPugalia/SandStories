import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import complete_depth_any2full


class Any2FullIntegrationTests(unittest.TestCase):
    def make_session(self, root: Path) -> Path:
        session = root / "session_test"
        streams = session / "streams"
        streams.mkdir(parents=True)

        frame0 = np.array([[1.0, 0.0, 1.2], [np.nan, 1.4, 1.5]], dtype="<f4")
        frame1 = np.array([[1.1, 1.2, 0.0], [1.3, 1.4, 1.6]], dtype="<f4")
        (streams / "depth.f32").write_bytes(frame0.tobytes() + frame1.tobytes())
        (streams / "rgb.mp4").write_bytes(b"test-placeholder")

        manifest = {
            "captureFormat": "v2_streams",
            "v2Streams": {
                "frameMetadataFile": "v2_frames.jsonl",
                "rgbVideoPath": "streams/rgb.mp4",
                "depthStreamPath": "streams/depth.f32",
            },
        }
        (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        entries = []
        for row in range(2):
            entries.append(
                {
                    "frameIndex": row + 1,
                    "arTimestamp": float(row),
                    "monotonicElapsedSeconds": float(row),
                    "rgbPresentationTimeSeconds": float(row),
                    "selectedDepthSource": "sceneDepth",
                    "width": 3,
                    "height": 2,
                    "depthByteOffset": row * 24,
                    "depthByteCount": 24,
                }
            )
        with (session / "v2_frames.jsonl").open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry) + "\n")
        return session

    @staticmethod
    def fake_rgb_reader(_session: Path, _manifest: dict, entry: dict):
        value = 50 * int(entry["frameIndex"])
        return np.full((4, 6, 3), value, dtype=np.uint8)

    def test_prepare_inputs_writes_aligned_pairs_without_modifying_raw_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self.make_session(root)
            output = session / "derived" / "any2full"
            raw_before = (session / "streams" / "depth.f32").read_bytes()

            result = complete_depth_any2full.prepare_inputs(
                session,
                output,
                rgb_reader=self.fake_rgb_reader,
            )

            self.assertEqual(result["status"], "prepared")
            self.assertEqual(result["pairCount"], 2)
            self.assertFalse(result["rawDataModified"])
            self.assertEqual((session / "streams" / "depth.f32").read_bytes(), raw_before)

            depth = np.load(output / result["pairs"][0]["inputDepth"])
            with Image.open(output / result["pairs"][0]["inputRGB"]) as image:
                rgb = np.asarray(image.convert("RGB"))
            self.assertEqual(depth.shape, (2, 3))
            self.assertEqual(rgb.shape, (2, 3, 3))
            self.assertEqual(float(depth[0, 1]), 0.0)
            self.assertEqual(float(depth[1, 0]), 0.0)

    def test_quality_report_measures_known_lidar_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self.make_session(root)
            output = session / "derived" / "any2full"
            completion = complete_depth_any2full.prepare_inputs(
                session,
                output,
                max_frames=1,
                rgb_reader=self.fake_rgb_reader,
            )
            pair = completion["pairs"][0]
            source = np.load(output / pair["inputDepth"])
            prediction = np.where(source > 0, source, 1.25).astype(np.float32)
            np.save(output / pair["predictionDepth"], prediction)

            report = complete_depth_any2full.compute_quality_report(output, completion)

            self.assertEqual(report["aggregate"]["anchorMAEMeters"], 0.0)
            self.assertEqual(report["frames"][0]["completedValidPixelRatio"], 1.0)
            self.assertIn("unvalidated estimates", report["scope"])

    def test_selected_depth_uses_smoothed_primary_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self.make_session(root)
            metadata_path = session / "v2_frames.jsonl"
            entries = [
                json.loads(line)
                for line in metadata_path.read_text(encoding="utf-8").splitlines()
            ]
            entries[0]["selectedDepthSource"] = "smoothedSceneDepth"
            metadata_path.write_text(
                "\n".join(json.dumps(entry) for entry in entries) + "\n",
                encoding="utf-8",
            )

            result = complete_depth_any2full.prepare_inputs(
                session,
                session / "derived" / "any2full",
                max_frames=1,
                rgb_reader=self.fake_rgb_reader,
            )

            depth = np.load(
                session / "derived" / "any2full" / result["pairs"][0]["inputDepth"]
            )
            self.assertAlmostEqual(float(depth[0, 0]), 1.0)
            self.assertEqual(
                result["pairs"][0]["selectedDepthSource"], "smoothedSceneDepth"
            )

    def test_encoder_is_inferred_from_official_checkpoint_name(self):
        checkpoint = Path("Any2Full_vits.pth.tar")
        self.assertEqual(complete_depth_any2full.infer_encoder(checkpoint, "auto"), "vits")


if __name__ == "__main__":
    unittest.main()
