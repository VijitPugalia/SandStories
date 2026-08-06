import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import detect_objects_yolo_world


class DetectObjectsV2Tests(unittest.TestCase):
    def test_iter_session_frames_samples_manifest_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            streams = session / "streams"
            streams.mkdir()
            video_path = streams / "rgb.avi"
            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"MJPG"),
                10.0,
                (32, 24),
            )
            self.assertTrue(writer.isOpened())
            for index in range(10):
                writer.write(np.full((24, 32, 3), index * 10, dtype=np.uint8))
            writer.release()
            (session / "manifest.json").write_text(
                json.dumps({"v2Streams": {"rgbVideoPath": "streams/rgb.avi"}}),
                encoding="utf-8",
            )

            frames = list(detect_objects_yolo_world.iter_session_frames(session, sample_fps=2.0))

            self.assertEqual([frame[0] for frame in frames], [0, 5])
            self.assertAlmostEqual(frames[1][1], 0.5)
            self.assertEqual(frames[0][2].shape, (24, 32, 3))

    def test_get_frame_paths_supports_legacy_rgb_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            rgb_dir = session / "rgb"
            rgb_dir.mkdir()
            frame_path = rgb_dir / "r_000001.jpg"
            frame_path.write_bytes(b"test")
            self.assertEqual(detect_objects_yolo_world.get_frame_paths(session), [frame_path])


if __name__ == "__main__":
    unittest.main()
