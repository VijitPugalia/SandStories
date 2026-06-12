from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION_PATH = ROOT / "data" / "sample_session" / "session.json"


def make_hand(center, angle, scale=1.0, mirror=False):
    # MediaPipe Hands order:
    # wrist, thumb 1-4, index 5-8, middle 9-12, ring 13-16, pinky 17-20.
    local = [
        (0.00, 0.00, 0.00),
        (-0.13, 0.03, 0.05), (-0.22, 0.06, 0.12), (-0.30, 0.09, 0.19), (-0.37, 0.11, 0.26),
        (-0.10, 0.06, 0.20), (-0.12, 0.10, 0.34), (-0.13, 0.12, 0.47), (-0.14, 0.13, 0.58),
        (0.00, 0.07, 0.22), (0.00, 0.12, 0.38), (0.00, 0.15, 0.53), (0.00, 0.16, 0.66),
        (0.10, 0.06, 0.20), (0.12, 0.10, 0.34), (0.13, 0.12, 0.46), (0.14, 0.13, 0.57),
        (0.20, 0.04, 0.16), (0.25, 0.07, 0.28), (0.29, 0.09, 0.38), (0.32, 0.10, 0.47),
    ]
    ca, sa = math.cos(angle), math.sin(angle)
    out = []
    for x, y, z in local:
        if mirror:
            x = -x
        x *= scale
        y *= scale
        z *= scale
        rx = x * ca - z * sa
        rz = x * sa + z * ca
        out.append([round(center[0] + rx, 3), round(center[1] + y, 3), round(center[2] + rz, 3)])
    return out


def main() -> None:
    data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))

    times = [0.0, 3.0, 6.0, 9.0, 12.0]
    right_centers = [(-1.25, 0.34, -0.62), (-0.78, 0.36, -0.42), (-0.22, 0.37, -0.12), (0.35, 0.37, 0.16), (0.82, 0.36, 0.36)]
    right_angles = [0.95, 0.85, 0.72, 0.58, 0.48]
    left_centers = [(1.15, 0.36, -0.95), (1.20, 0.36, -0.86), (1.24, 0.37, -0.76), (1.18, 0.37, -0.66), (1.05, 0.36, -0.58)]
    left_angles = [-0.12, -0.08, -0.04, 0.02, 0.10]

    data["hand_tracks"] = [
        {
            "id": "right_hand",
            "label": "Right hand / drawing gesture",
            "handedness": "right",
            "model_path": "res://assets/models/hand_right.obj",
            "model_scale": 0.9,
            "model_rotation_degrees": [-90.0, 12.0, 0.0],
            "model_follow_orientation": True,
            "virtual_hand": False,
            "show_landmarks": False,
            "show_skeleton": False,
            "show_mesh_ghost": True,
            "interpolation": "cubic",
            "color": "#57c7d4",
            "mesh_color": "#57c7d4",
            "joint_count": 21,
            "samples": [
                {"time": t, "landmarks": make_hand(c, a, 0.55, mirror=True)}
                for t, c, a in zip(times, right_centers, right_angles)
            ],
        },
        {
            "id": "left_hand",
            "label": "Left hand / pointing gesture",
            "handedness": "left",
            "model_path": "res://assets/models/hand_left.obj",
            "model_scale": 0.85,
            "model_rotation_degrees": [-90.0, -10.0, 0.0],
            "model_follow_orientation": True,
            "virtual_hand": False,
            "show_landmarks": False,
            "show_skeleton": False,
            "show_mesh_ghost": True,
            "interpolation": "cubic",
            "color": "#f2a65e",
            "mesh_color": "#f2a65e",
            "joint_count": 21,
            "samples": [
                {"time": t, "landmarks": make_hand(c, a, 0.52, mirror=False)}
                for t, c, a in zip(times, left_centers, left_angles)
            ],
        },
    ]

    for ref in data.get("references", []):
        if ref.get("id") == "gesture_to_route":
            ref["source"] = "right_hand"
        elif ref.get("id") == "gesture_to_water":
            ref["source"] = "left_hand"

    SESSION_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Updated {SESSION_PATH}")


if __name__ == "__main__":
    main()
