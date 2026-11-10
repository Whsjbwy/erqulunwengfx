"""Export fixed-seed scientific path figures from actual trial evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .scenarios import load_scenarios
from .stage2_worker import METHODS

LABELS = {
    "author_original": "Author-Original",
    "paper_reimplementation": "Paper-Reimplementation",
    "safety_reference": "Safety-Reference",
    "astar": "3D A*",
    "rrt_connect": "RRT-Connect",
}


def plot_paths(
    map_config: Path, paths_file: Path, output_dir: Path, seed: int = 0
) -> list[Path]:
    """Render one five-method figure per scene using a preselected seed.

    Occupied cell centers are uniformly decimated solely for drawing; collision
    checking always uses the complete map. Invalid paths are drawn in red and
    missing paths are explicitly labeled, without replacing them by witnesses.
    """
    records = [
        json.loads(line) for line in paths_file.read_text(encoding="utf-8").splitlines()
    ]
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        if record["seed"] != seed:
            continue
        key = (record["scene_id"], record["method"])
        if key in selected:
            raise ValueError(f"Ambiguous duplicate trial in plotting input: {key}")
        selected[key] = record
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for scenario in load_scenarios(map_config):
        figure = plt.figure(figsize=(14, 8), layout="constrained")
        occupied = np.argwhere(scenario.grid.occupancy)
        stride = max(1, int(np.ceil(len(occupied) / 1800)))
        occupied = occupied[::stride]
        points = (
            np.asarray(scenario.grid.origin) + (occupied + 0.5) * scenario.grid.spacing
        )
        for index, method in enumerate(METHODS):
            axis = figure.add_subplot(2, 3, index + 1, projection="3d")
            record = selected.get((scenario.scene_id, method))
            if len(points):
                axis.scatter(*points.T, s=1, alpha=0.12, c="gray", rasterized=True)
            axis.scatter(*scenario.start, color="blue", s=20)
            axis.scatter(*scenario.goal, color="black", s=25, marker="*")
            if record is None:
                subtitle = "NOT RUN"
            else:
                path = record.get("raw_path")
                valid = record.get("raw_validation", {}).get("valid")
                subtitle = f"{record['status']} / strict={valid}"
                if path is not None:
                    vertices = np.asarray(path)
                    axis.plot(
                        *vertices.T, color="green" if valid else "red", linewidth=1.7
                    )
                elif record.get("reported_success"):
                    subtitle += " / NO COORDINATES"
            axis.set_title(f"{LABELS[method]}\n{subtitle}", fontsize=9)
            for setter, low, high in zip(
                (axis.set_xlim, axis.set_ylim, axis.set_zlim),
                scenario.grid.bounds[::2],
                scenario.grid.bounds[1::2],
                strict=True,
            ):
                setter(low, high)
            axis.set_box_aspect((100, 80, 80))
            axis.set_xlabel("x", fontsize=8)
            axis.set_ylabel("y", fontsize=8)
            axis.set_zlabel("z (map)", fontsize=8)
            axis.tick_params(labelsize=7)
            axis.view_init(elev=23, azim=-55)
        annotation = figure.add_subplot(2, 3, 6)
        annotation.axis("off")
        annotation.text(
            0,
            0.95,
            f"{scenario.scene_id}, map seed {scenario.map_seed}\n"
            f"Planning seed {seed} (fixed before trials)\n\n"
            "Blue: exact start; black star: exact goal\n"
            "Green: strictly valid raw path\nRed: invalid raw path\n"
            "Gray: occupied voxel centers (decimated)\n\n"
            "No path is substituted when a planner fails.\n"
            "Geometry: zero-radius polyline; closed voxels.\n"
            "Images illustrate results, not safety proofs.\n\n"
            f"Reachability: {scenario.reachability}\n"
            "S3 world display convention: z_world=z_map-80",
            va="top",
            fontsize=9,
            linespacing=1.6,
        )
        figure.suptitle(
            f"Stage 2 / {scenario.scene_id} / actual raw paths / seed {seed}"
        )
        target = output_dir / f"{scenario.scene_id}_seed{seed}.png"
        figure.savefig(target, dpi=110)
        plt.close(figure)
        outputs.append(target)
    return outputs


def main(argv: list[str] | None = None) -> int:
    """Export actual fixed-seed path figures without opening a GUI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map-config", type=Path, default=Path("configs/stage2_maps.json")
    )
    parser.add_argument("--paths-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    plot_paths(args.map_config, args.paths_file, args.output_dir, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
