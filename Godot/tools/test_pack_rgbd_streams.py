from __future__ import annotations

import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

import pack_rgbd_streams


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def write_png(path: Path, width: int, height: int, color_type: int, bit_depth: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\0" + row for row in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class StreamBundleTest(unittest.TestCase):
    def test_lossless_depth_round_trip_and_variable_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            session = root / "session"
            rgb_root = session / "clean_rgb"
            depth_root = session / "clean_depth"
            rgb_root.mkdir(parents=True)
            depth_root.mkdir()
            frames = []
            for index, timestamp in enumerate((0.0, 0.04, 0.11), start=1):
                rgb_name = f"clean_rgb/clean_rgb_{index:06d}.png"
                depth_name = f"clean_depth/clean_depth_{index:06d}.png"
                write_png(
                    session / rgb_name,
                    8,
                    6,
                    2,
                    8,
                    [b"".join(bytes((index * 20, x, y)) for x in range(8)) for y in range(6)],
                )
                depth_rows = [
                    b"".join(struct.pack(">H", index * 100 + y * 8 + x) for x in range(8))
                    for y in range(6)
                ]
                write_png(session / depth_name, 8, 6, 0, 16, depth_rows)
                frames.append(
                    {
                        "frameIndex": index,
                        "time": timestamp,
                        "cleanRgb": rgb_name,
                        "cleanDepth": depth_name,
                    }
                )
            (session / "processed_manifest.json").write_text(
                json.dumps({"frameSize": {"width": 8, "height": 6}, "frames": frames}),
                encoding="utf-8",
            )
            bundle = root / "bundle.zip"
            result = pack_rgbd_streams.pack(
                session, bundle, "lossless", "native", 30.0, "ffmpeg", "ffprobe"
            )
            self.assertEqual(result["frameCount"], 3)
            self.assertTrue(result["rgb"]["pixelLossless"])
            restored = root / "restored"
            capture = pack_rgbd_streams.unpack(bundle, restored, "ffmpeg", "ffprobe")
            self.assertEqual(capture["frameCount"], 3)
            records = [
                json.loads(line)
                for line in (restored / "capture_frames.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record["timeSeconds"] for record in records], [0.0, 0.04, 0.11])
            original_raw = subprocess.check_output(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-framerate", "1", "-i", str(depth_root / "clean_depth_%06d.png"), "-f", "rawvideo", "-pix_fmt", "gray16le", "-"]
            )
            restored_raw = subprocess.check_output(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-framerate", "1", "-i", str(restored / "depth" / "depth_%06d.png"), "-f", "rawvideo", "-pix_fmt", "gray16le", "-"]
            )
            self.assertEqual(restored_raw, original_raw)


if __name__ == "__main__":
    unittest.main()
