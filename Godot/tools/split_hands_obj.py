from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "models" / "hands.obj"
OUT_DIR = ROOT / "assets" / "models"


def face_vertex_index(token: str) -> int:
    return int(token.split("/")[0])


def rewrite_face(line: str, remap: dict[int, int]) -> str:
    parts = line.split()
    rewritten = ["f"]
    for token in parts[1:]:
        bits = token.split("/")
        bits[0] = str(remap[int(bits[0])])
        rewritten.append("/".join(bits))
    return " ".join(rewritten)


def write_side(
    name: str,
    vertex_indices: set[int],
    faces: list[str],
    vertices: list[tuple[float, float, float]],
    vt_lines: list[str],
    vn_lines: list[str],
) -> None:
    ordered = sorted(vertex_indices)
    remap = {old: new for new, old in enumerate(ordered, start=1)}
    side_vertices = [vertices[i - 1] for i in ordered]
    min_x = min(v[0] for v in side_vertices)
    max_x = max(v[0] for v in side_vertices)
    min_y = min(v[1] for v in side_vertices)
    max_y = max(v[1] for v in side_vertices)
    min_z = min(v[2] for v in side_vertices)
    max_z = max(v[2] for v in side_vertices)
    center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)

    out_path = OUT_DIR / f"hand_{name}.obj"
    with out_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write("# Split from hands.obj for Sand Stories runtime hand tracks.\n")
        out.write("# Local vertices are recentered so a MediaPipe track can place each hand independently.\n")
        out.write("mtllib hands.mtl\n")
        out.write(f"o hand_{name}\n")
        for x, y, z in side_vertices:
            out.write(f"v {x - center[0]:.6f} {y - center[1]:.6f} {z - center[2]:.6f}\n")
        for line in vt_lines:
            out.write(line)
        for line in vn_lines:
            out.write(line)
        out.write("usemtl Hand_Tex\n")
        out.write("s 1\n")
        for line in faces:
            out.write(rewrite_face(line, remap) + "\n")

    print(f"{out_path.name}: {len(ordered)} vertices, {len(faces)} faces")


def main() -> None:
    vertices: list[tuple[float, float, float]] = []
    vt_lines: list[str] = []
    vn_lines: list[str] = []
    left_faces: list[str] = []
    right_faces: list[str] = []
    left_vertices: set[int] = set()
    right_vertices: set[int] = set()

    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("v "):
            _, x, y, z = line.split()[:4]
            vertices.append((float(x), float(y), float(z)))
        elif line.startswith("vt "):
            vt_lines.append(raw + "\n")
        elif line.startswith("vn "):
            vn_lines.append(raw + "\n")

    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("f "):
            continue
        indices = [face_vertex_index(token) for token in line.split()[1:]]
        centroid_x = sum(vertices[i - 1][0] for i in indices) / len(indices)
        if centroid_x < 0.0:
            left_faces.append(line)
            left_vertices.update(indices)
        else:
            right_faces.append(line)
            right_vertices.update(indices)

    write_side("left", left_vertices, left_faces, vertices, vt_lines, vn_lines)
    write_side("right", right_vertices, right_faces, vertices, vt_lines, vn_lines)


if __name__ == "__main__":
    main()
