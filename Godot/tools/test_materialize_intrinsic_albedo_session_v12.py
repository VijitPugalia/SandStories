from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from materialize_intrinsic_albedo_session_v12 import free_gib


class MaterializeIntrinsicAlbedoSessionV12Tests(unittest.TestCase):
    def test_free_space_probe_finds_existing_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "job" / "output" / "final_v12"

            self.assertGreater(free_gib(output), 0.0)


if __name__ == "__main__":
    unittest.main()
