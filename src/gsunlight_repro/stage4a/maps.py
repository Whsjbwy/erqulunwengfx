"""Generate seeded independent scenes without planner-conditioned selection."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from ..collision_checker import validate_path
from ..scenarios import Scenario, generate_scenario, load_scenario

CONFIG = Path(__file__).resolve().parents[3] / "configs/stage4a_maps.json"


def specifications(document: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Read the frozen map list and its physical cell counts."""
    if document is None:
        document = json.loads(CONFIG.read_text(encoding="utf-8"))
    return [
        {**item, "shape": document[item["scale"] + "_shape"]}
        for item in document["maps"]
    ]


def recipe(spec: dict[str, Any]) -> dict[str, Any]:
    """Build geometry using only the map seed, never a planning result."""
    rng = np.random.default_rng(spec["seed"])
    nx, ny, nz = spec["shape"]
    start = [
        3.5 + int(rng.integers(2)),
        3.5 + int(rng.integers(3)),
        4.5 + int(rng.integers(3)),
    ]
    goal = [
        nx - 3.5 - int(rng.integers(2)),
        ny - 3.5 - int(rng.integers(3)),
        nz - 3.5 - int(rng.integers(3)),
    ]
    config: dict[str, Any] = {
        "scene_id": spec["id"],
        "map_seed": spec["seed"],
        "shape": spec["shape"],
        "origin": [0, 0, 0],
        "spacing": [1, 1, 1],
        "start": start,
        "goal": goal,
        "description": f"Stage4A {spec['family']} seed {spec['seed']}",
        "reachability": "certified_reachable",
        "boxes": [],
        "spheres": [],
        "designed_channel_width": None,
    }

    def box(lower: list[int], upper: list[int]) -> None:
        config["boxes"].append({"lower": lower, "upper": upper})

    family = spec["family"]
    if family in ("ordinary", "terrain"):
        top = nz - 2.5
        config["witness_path"] = [
            start,
            [start[0], start[1], top],
            [goal[0], goal[1], top],
            goal,
        ]
        if family == "ordinary":
            config["kind"] = "static_obstacles"
            middle = nx // 2
            fraction = (middle - start[0]) / (goal[0] - start[0])
            y = int(start[1] + fraction * (goal[1] - start[1]))
            box([middle - 3, y - 5, 0], [middle + 4, y + 6, int(0.72 * nz)])
            for _ in range(4):
                x = int(rng.integers(8, nx - 15))
                y = int(rng.integers(6, ny - 14))
                box(
                    [x, y, 0],
                    [
                        min(nx - 7, x + int(rng.integers(4, 9))),
                        min(ny - 2, y + int(rng.integers(5, 12))),
                        int(rng.uniform(0.3, 0.65) * nz),
                    ],
                )
        else:
            config["kind"] = "gaussian_seabed"
            middle = nx / 2
            fraction = (middle - start[0]) / (goal[0] - start[0])
            y = start[1] + fraction * (goal[1] - start[1])
            config["terrain"] = {
                "base_height": 1,
                "minimum_height": 1,
                "peaks": [
                    {"center": [middle, y], "amplitude": 0.62 * nz, "sigma": 0.13 * nx},
                    {
                        "center": [0.24 * nx, float(rng.uniform(0.25, 0.7) * ny)],
                        "amplitude": 0.1 * nz,
                        "sigma": 0.08 * nx,
                    },
                    {
                        "center": [0.76 * nx, float(rng.uniform(0.25, 0.7) * ny)],
                        "amplitude": 0.1 * nz,
                        "sigma": 0.08 * nx,
                    },
                ],
            }
        for fraction in (0.3, 0.7):
            config["spheres"].append(
                {
                    "center": [
                        fraction * nx,
                        float(rng.uniform(0.25, 0.75) * ny),
                        float(rng.uniform(0.4, 0.6) * nz),
                    ],
                    "radius": 3 if spec["scale"] == "small" else 5,
                }
            )
    elif family == "staggered":
        config["kind"] = "static_obstacles"
        witness = [start]
        widths = []
        for index, fraction in enumerate((0.25, 0.5, 0.75)):
            left = int(fraction * nx) + int(rng.integers(-1, 2))
            right = left + (2 if spec["scale"] == "small" else 3)
            if index % 2 == 0:
                cut = int(rng.uniform(0.59, 0.67) * ny)
                height = int(rng.uniform(0.4, 0.52) * nz)
                box([left, 0, 0], [right, cut, nz])
                box([left, cut, 0], [right, ny, height])
                y, z = (cut + ny) / 2, (height + nz) / 2
                widths.append(min(ny - cut, nz - height))
            else:
                cut = int(rng.uniform(0.31, 0.39) * ny)
                height = int(rng.uniform(0.52, 0.65) * nz)
                box([left, cut, 0], [right, ny, nz])
                box([left, 0, height], [right, cut, nz])
                y, z = cut / 2, height / 2
                widths.append(min(cut, height))
            witness.extend([[left - 2, y, z], [right + 2, y, z]])
        config["witness_path"] = [*witness, goal]
        config["designed_channel_width"] = min(widths)
    elif family == "narrow":
        config["kind"] = "narrow_concave"
        config["openings"] = []
        witness = [start]
        width = 6 if spec["scale"] == "small" else 8
        for index, fraction in enumerate((1 / 3, 2 / 3)):
            left = int(fraction * nx)
            right = left + (2 if spec["scale"] == "small" else 3)
            box([left, 0, 0], [right, ny, nz])
            y = (
                int(rng.uniform(0.22, 0.26) * ny)
                if index == 0
                else int(rng.uniform(0.68, 0.74) * ny)
            )
            z = (
                int(rng.uniform(0.29, 0.35) * nz)
                if index == 0
                else int(rng.uniform(0.65, 0.73) * nz)
            )
            yl, zl = y - width // 2, z - width // 2
            config["openings"].append(
                {"lower": [left, yl, zl], "upper": [right, yl + width, zl + width]}
            )
            witness.extend([[left - 2, y, z], [right + 2, y, z]])
        config["witness_path"] = [*witness, goal]
        config["designed_channel_width"] = width
    elif family == "sealed":
        config.update(
            kind="sealed_barrier",
            reachability="certified_unreachable",
            witness_path=None,
            certificate={
                "kind": "full_axis_barrier",
                "axis": 0,
                "lower": nx // 2 - 1,
                "upper": nx // 2 + 2,
            },
        )
        box([nx // 2 - 1, 0, 0], [nx // 2 + 2, ny, nz])
    else:
        raise ValueError(f"Unknown stage4a map family: {family}")
    return config


def load_map(scene_id: str, document: dict[str, Any] | None = None) -> Scenario:
    """Generate exactly one registered scene and verify its reachability evidence."""
    if scene_id == "S1":
        scene = load_scenario(CONFIG.with_name("stage2_maps.json"), "S1")
        scene.grid.occupancy.setflags(write=False)
        return replace(
            scene,
            metadata={
                **scene.metadata,
                "split": "legacy",
                "family": "legacy",
                "scale": "large",
            },
        )
    selected = next((s for s in specifications(document) if s["id"] == scene_id), None)
    if selected is None:
        raise ValueError(f"Unregistered scene: {scene_id}")
    configuration = recipe(selected)
    scene = generate_scenario(configuration)
    if validate_path([scene.start, scene.goal], scene.grid).valid:
        raise ValueError(
            f"Registered nontrivial map unexpectedly allows direct flight: {scene_id}"
        )
    scene.grid.occupancy.setflags(write=False)
    return replace(
        scene,
        metadata={
            **scene.metadata,
            **selected,
            "designed_channel_width": configuration["designed_channel_width"],
        },
    )


def map_features(scene: Scenario) -> dict[str, Any]:
    """Describe rasterized geometry, without claiming a global aperture minimum."""
    from ..metrics import path_length

    return {
        "scene": scene.scene_id,
        "map_seed": scene.map_seed,
        "split": scene.metadata["split"],
        "family": scene.metadata["family"],
        "scale": scene.metadata["scale"],
        "shape": scene.grid.shape,
        "origin": scene.grid.origin,
        "spacing": scene.grid.spacing,
        "start": scene.start,
        "goal": scene.goal,
        "occupied_fraction": float(scene.grid.occupancy.mean()),
        "designed_channel_width": scene.metadata.get("designed_channel_width"),
        "witness_length": path_length(scene.witness_path)
        if scene.witness_path
        else None,
        "reachability": scene.reachability,
    }
