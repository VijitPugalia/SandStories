#!/usr/bin/env python3
"""Render reproducible top/oblique/side diagnostics for fused MANO meshes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
import numpy as np
from PIL import Image


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fusion-dir", type=Path, required=True)
    parser.add_argument("--rgb-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _equal_3d_axes(axis: plt.Axes, vertices: np.ndarray) -> None:
    minimum = vertices.min(axis=0)
    maximum = vertices.max(axis=0)
    center = (minimum + maximum) * 0.5
    radius = max(float(np.max(maximum - minimum)) * 0.55, 0.01)
    axis.set_xlim(center[0] - radius, center[0] + radius)
    axis.set_ylim(center[2] - radius, center[2] + radius)
    axis.set_zlim(center[1] - radius, center[1] + radius)


def _render_frame(
    npz_path: Path,
    rgb_path: Path,
    output_path: Path,
) -> None:
    arrays = np.load(npz_path)
    vertices = arrays["vertices_world"]
    faces = arrays["faces"]
    image_uv = arrays["image_uv"]
    lift_mm = arrays["fused_lift_meters"] * 1000.0
    supported = arrays["supported"]
    source = np.asarray(Image.open(rgb_path).convert("RGB"))

    figure = plt.figure(figsize=(14, 8), constrained_layout=True)
    grid = figure.add_gridspec(2, 2)

    image_axis = figure.add_subplot(grid[:, 0])
    image_axis.imshow(source)
    image_triangles = mtri.Triangulation(
        image_uv[:, 0], image_uv[:, 1], triangles=faces
    )
    image_axis.tripcolor(
        image_triangles,
        lift_mm,
        cmap="turbo",
        shading="gouraud",
        alpha=0.55,
    )
    image_axis.triplot(image_triangles, color="white", alpha=0.14, linewidth=0.25)
    image_axis.scatter(
        image_uv[~supported, 0],
        image_uv[~supported, 1],
        s=5,
        color="#ff2a52",
        label="nearest RGB-D support > 12 px",
    )
    image_axis.set_xlim(0, source.shape[1])
    image_axis.set_ylim(source.shape[0], 0)
    image_axis.set_title("RGB + fused MANO surface (colour = lift)")
    image_axis.axis("off")
    if np.any(~supported):
        image_axis.legend(loc="lower right", fontsize=8)

    top_axis = figure.add_subplot(grid[0, 1])
    world_triangles = mtri.Triangulation(
        vertices[:, 0], vertices[:, 2], triangles=faces
    )
    colour = top_axis.tripcolor(
        world_triangles,
        vertices[:, 1],
        cmap="viridis",
        shading="gouraud",
    )
    top_axis.triplot(world_triangles, color="black", alpha=0.10, linewidth=0.25)
    top_axis.set_aspect("equal", adjustable="box")
    top_axis.invert_yaxis()
    top_axis.set_xlabel("world X")
    top_axis.set_ylabel("world Z")
    top_axis.set_title("Godot top view (colour = world Y)")
    figure.colorbar(colour, ax=top_axis, shrink=0.8, label="world Y")

    mesh_axis = figure.add_subplot(grid[1, 1], projection="3d")
    mesh_axis.plot_trisurf(
        vertices[:, 0],
        vertices[:, 2],
        vertices[:, 1],
        triangles=faces,
        cmap="viridis",
        linewidth=0.08,
        antialiased=True,
        alpha=1.0,
    )
    mesh_axis.view_init(elev=15, azim=-70)
    _equal_3d_axes(mesh_axis, vertices)
    mesh_axis.set_xlabel("X")
    mesh_axis.set_ylabel("Z")
    mesh_axis.set_zlabel("Y")
    mesh_axis.set_title("Oblique mesh: closed MANO back surface retained")

    figure.suptitle(npz_path.stem, fontsize=14)
    figure.savefig(output_path, dpi=140)
    plt.close(figure)


def _contact_sheet(paths: list[Path], output_path: Path) -> None:
    images = [Image.open(path).convert("RGB") for path in paths]
    thumb_width = 700
    thumbs = [
        image.resize(
            (thumb_width, round(image.height * thumb_width / image.width)),
            Image.Resampling.LANCZOS,
        )
        for image in images
    ]
    columns = 3
    rows = (len(thumbs) + columns - 1) // columns
    cell_height = max(image.height for image in thumbs)
    sheet = Image.new(
        "RGB",
        (thumb_width * columns, cell_height * rows),
        color=(245, 245, 245),
    )
    for index, image in enumerate(thumbs):
        sheet.paste(
            image,
            ((index % columns) * thumb_width, (index // columns) * cell_height),
        )
    sheet.save(output_path)


def main() -> None:
    args = _parse_args()
    report = json.loads(
        (args.fusion_dir / "hamer_rgbd_fusion_report.json").read_text(
            encoding="utf-8"
        )
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for frame in report["frames"]:
        frame_index = int(frame["frameIndex"])
        output_path = args.output_dir / f"fused_diagnostic_{frame_index:06d}.png"
        _render_frame(
            args.fusion_dir / frame["npz"],
            args.rgb_dir / f"clean_rgb_{frame_index:06d}.png",
            output_path,
        )
        rendered.append(output_path)
        print(f"wrote {output_path}")
    sheet_path = args.output_dir / "hamer_rgbd_fused_hard9_contact.png"
    _contact_sheet(rendered, sheet_path)
    print(f"wrote {sheet_path}")


if __name__ == "__main__":
    main()
