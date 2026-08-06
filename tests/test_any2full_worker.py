import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import any2full_worker, db


class Any2FullWorkerTests(unittest.TestCase):
    def make_session(self, root: Path) -> Path:
        session = root / "session_test"
        streams = session / "streams"
        streams.mkdir(parents=True)
        depth = np.array([[1.0, 0.0, 1.2], [1.3, 1.4, 1.5]], dtype="<f4")
        (streams / "depth.f32").write_bytes(depth.tobytes())

        video_path = streams / "rgb.mp4"
        writer = cv2.VideoWriter(
            str(video_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            5.0,
            (12, 8),
        )
        self.assertTrue(writer.isOpened())
        writer.write(np.full((8, 12, 3), 90, dtype=np.uint8))
        writer.release()

        manifest = {
            "captureFormat": "v2_streams",
            "v2Streams": {
                "frameMetadataFile": "v2_frames.jsonl",
                "rgbVideoPath": "streams/rgb.mp4",
                "depthStreamPath": "streams/depth.f32",
            },
        }
        (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        entry = {
            "frameIndex": 1,
            "arTimestamp": 0.0,
            "monotonicElapsedSeconds": 0.0,
            "rgbPresentationTimeSeconds": 0.0,
            "selectedDepthSource": "sceneDepth",
            "width": 3,
            "height": 2,
            "depthByteOffset": 0,
            "depthByteCount": 24,
        }
        (session / "v2_frames.jsonl").write_text(
            json.dumps(entry) + "\n", encoding="utf-8"
        )
        return session

    def make_fake_any2full(self, root: Path) -> tuple[Path, Path]:
        repository = root / "Any2Full"
        repository.mkdir()
        runner = repository / "run_any2full.py"
        runner.write_text(
            """
import argparse
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--rgb_dir")
parser.add_argument("--depth_dir")
parser.add_argument("--checkpoint")
parser.add_argument("--encoder")
parser.add_argument("--out_dir")
parser.add_argument("--denoise", action="store_true")
args = parser.parse_args()
out = Path(args.out_dir)
out.mkdir(parents=True, exist_ok=True)
for source in Path(args.depth_dir).glob("*.npy"):
    depth = np.load(source).astype(np.float32)
    prediction = np.where(depth > 0, depth, 1.25).astype(np.float32)
    np.save(out / source.name, prediction)
""".strip()
            + "\n",
            encoding="utf-8",
        )
        checkpoint = repository / "Any2Full_vits.pth.tar"
        checkpoint.write_bytes(b"fake")
        return repository, checkpoint

    def config(self, repository: Path, checkpoint: Path) -> any2full_worker.Any2FullConfig:
        return any2full_worker.Any2FullConfig(
            enabled=True,
            python_executable=sys.executable,
            repository_dir=repository,
            checkpoint=checkpoint,
            encoder="auto",
            depth_source="selected",
            target_resolution="depth",
            stride=1,
            max_frames=1,
            denoise=False,
            timeout_seconds=60,
        )

    def test_worker_runs_completion_and_archives_derived_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = self.make_session(root)
            any2full_dir, checkpoint = self.make_fake_any2full(root)
            repository_root = Path(__file__).resolve().parents[1]
            artifacts = root / "artifacts"
            package = {"id": "package-test", "extracted_path": str(session)}

            result = any2full_worker.run_completion(
                package,
                self.config(any2full_dir, checkpoint),
                repository_root,
                artifacts,
            )

            self.assertTrue(Path(result["artifactPath"]).is_file())
            self.assertTrue(Path(result["reportPath"]).is_file())
            self.assertEqual(result["pairCount"], 1)
            self.assertEqual(
                result["aggregateAnchorMetrics"]["anchorMAEMeters"], 0.0
            )
            raw = np.fromfile(session / "streams" / "depth.f32", dtype="<f4")
            self.assertEqual(float(raw[1]), 0.0)

    def test_database_completion_queue_is_restart_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_data_dir = os.environ.get("SANDSTORIES_DATA_DIR")
            os.environ["SANDSTORIES_DATA_DIR"] = tmp
            try:
                db.init_db()
                db.insert_package(
                    {
                        "id": "package-1",
                        "filename": "session.zip",
                        "zip_path": str(Path(tmp) / "session.zip"),
                        "size_bytes": 10,
                        "sha256": "abc",
                        "uploaded_at": 1.0,
                        "validation_status": "valid",
                    }
                )
                db.queue_package_completion("package-1")
                claimed = db.claim_next_completion_package()
                self.assertIsNotNone(claimed)
                self.assertEqual(claimed["completion_status"], "running")

                db.reset_running_completion_jobs()
                claimed_again = db.claim_next_completion_package()
                self.assertIsNotNone(claimed_again)
                self.assertEqual(claimed_again["id"], "package-1")

                db.finish_package_completion(
                    "package-1",
                    output_path=Path(tmp) / "output",
                    report_path=Path(tmp) / "report.json",
                    artifact_path=Path(tmp) / "artifact.zip",
                )
                package = db.get_package("package-1")
                self.assertEqual(package["completion_status"], "completed")
            finally:
                if old_data_dir is None:
                    os.environ.pop("SANDSTORIES_DATA_DIR", None)
                else:
                    os.environ["SANDSTORIES_DATA_DIR"] = old_data_dir


if __name__ == "__main__":
    unittest.main()
