from __future__ import annotations

import unittest

import numpy as np

from audit_hand_edge_terraces import profile_metrics, sample_profiles


class AuditHandEdgeTerracesTests(unittest.TestCase):
    def test_concentric_depressions_are_detected_as_repeated_hand_edge_troughs(self) -> None:
        height = width = 192
        yy, xx = np.mgrid[:height, :width].astype(np.float32)
        radius = np.sqrt((xx - 96.0) ** 2 + (yy - 96.0) ** 2)
        hand_mask = radius <= 40.0
        surface = np.ones((height, width), dtype=bool)
        excluded = np.zeros((height, width), dtype=bool)
        plane = 0.520 + (xx - 96.0) * 0.00001
        terraced = plane.copy()
        for ring_radius, amplitude, sigma in (
            (46.0, 0.0012, 1.4),
            (54.0, 0.0009, 1.6),
            (62.0, 0.0007, 1.8),
        ):
            terraced -= amplitude * np.exp(
                -0.5 * ((radius - ring_radius) / sigma) ** 2
            )

        flat_profiles = sample_profiles(
            plane.astype(np.float32),
            surface,
            hand_mask,
            excluded,
            radius=30,
            maximum_profiles=500,
        )
        terraced_profiles = sample_profiles(
            terraced.astype(np.float32),
            surface,
            hand_mask,
            excluded,
            radius=30,
            maximum_profiles=500,
        )
        flat = profile_metrics(flat_profiles, prominence_mm=0.20)
        rings = profile_metrics(terraced_profiles, prominence_mm=0.20)

        self.assertLess(flat["multiTroughFraction"], 0.05)
        self.assertGreater(rings["multiTroughFraction"], 0.90)
        self.assertGreater(rings["prominenceP95Mm"], 0.50)
        self.assertGreater(rings["coherentRingPeakMm"], 0.30)


if __name__ == "__main__":
    unittest.main()
