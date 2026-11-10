"""Generate frozen synthetic scenarios without reading or changing author maps."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .collision_checker import validate_path
from .map_reader import OccupancyMap, Point


@dataclass(frozen=True, slots=True)
class Scenario:
    """One physical map, exact endpoints and a predeclared reachability claim."""

    scene_id: str
    grid: OccupancyMap
    start: Point
    goal: Point
    map_seed: int
    description: str
    witness_path: list[Point] | None
    reachability: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _point(values: Any, name: str) -> Point:
    point = np.asarray(values, dtype=float)
    if point.shape != (3,) or not np.all(np.isfinite(point)):
        raise ValueError(f"{name} must contain three finite coordinates")
    return tuple(float(value) for value in point)


def _box_slice(box: dict[str, Any], shape: tuple[int, ...]) -> tuple[slice, ...]:
    lower = np.asarray(box["lower"])
    upper = np.asarray(box["upper"])
    if lower.shape != (3,) or upper.shape != (3,):
        raise ValueError("Box bounds must have three cell indices")
    if not np.all(lower == lower.astype(int)) or not np.all(upper == upper.astype(int)):
        raise ValueError("Box bounds must be integer cell indices")
    if np.any(lower < 0) or np.any(upper > shape) or np.any(lower >= upper):
        raise ValueError("Box must be a nonempty range within the map")
    return tuple(
        slice(int(left), int(right)) for left, right in zip(lower, upper, strict=True)
    )


def _check_barrier(
    grid: OccupancyMap, start: Point, goal: Point, certificate: dict
) -> None:
    if certificate.get("kind") != "full_axis_barrier":
        raise ValueError("Unreachable maps require a full-axis barrier certificate")
    axis = int(certificate["axis"])
    lower = int(certificate["lower"])
    upper = int(certificate["upper"])
    if axis not in (0, 1, 2) or not 0 < lower < upper < grid.shape[axis]:
        raise ValueError("Barrier must separate two nonempty map regions")
    selection = [slice(None)] * 3
    selection[axis] = slice(lower, upper)
    if not np.all(grid.occupancy[tuple(selection)]):
        raise ValueError("Barrier certificate has an unoccupied gap")
    start_axis = (start[axis] - grid.origin[axis]) / grid.spacing[axis]
    goal_axis = (goal[axis] - grid.origin[axis]) / grid.spacing[axis]
    if not (
        (start_axis < lower and goal_axis > upper)
        or (goal_axis < lower and start_axis > upper)
    ):
        raise ValueError("Barrier must place the endpoints on opposite sides")


def generate_scenario(config: dict[str, Any]) -> Scenario:
    """Build a scenario from a merged profile and scene recipe.

    Boxes use half-open integer cell-index ranges; spheres and terrain use
    physical cell-center inclusion and become closed occupied voxel boxes.
    Explicit openings are part of the frozen recipe, never a planning repair.
    Invalid geometry, endpoint or reachability evidence raises ``ValueError``.
    """
    sizes = np.asarray(config["shape"])
    if (
        sizes.shape != (3,)
        or np.any(sizes < 1)
        or not np.all(sizes == sizes.astype(int))
    ):
        raise ValueError("Map shape must contain three positive cell counts")
    shape = tuple(int(value) for value in sizes)
    origin = _point(config.get("origin", (0, 0, 0)), "Origin")
    spacing = _point(config.get("spacing", (1, 1, 1)), "Spacing")
    if any(value <= 0 for value in spacing):
        raise ValueError("Map spacing must be positive")
    kind = config["kind"]
    if kind not in {
        "empty",
        "static_obstacles",
        "narrow_concave",
        "gaussian_seabed",
        "sealed_barrier",
    }:
        raise ValueError(f"Unknown scenario kind: {kind}")
    occupancy = np.zeros(shape, dtype=bool)
    centers = [
        origin[axis] + (np.arange(shape[axis]) + 0.5) * spacing[axis]
        for axis in range(3)
    ]
    x = centers[0][:, None, None]
    y = centers[1][None, :, None]
    z = centers[2][None, None, :]
    if kind == "gaussian_seabed":
        terrain = config["terrain"]
        height = np.full(shape[:2], float(terrain["base_height"]))
        for peak in terrain["peaks"]:
            sigma = float(peak["sigma"])
            if not np.isfinite(sigma) or sigma <= 0:
                raise ValueError("Gaussian sigma must be finite and positive")
            squared = (x[:, :, 0] - peak["center"][0]) ** 2 + (
                y[:, :, 0] - peak["center"][1]
            ) ** 2
            height += float(peak["amplitude"]) * np.exp(-squared / (2 * sigma**2))
        height = np.maximum(height, float(terrain["minimum_height"]))
        if not np.all(np.isfinite(height)):
            raise ValueError("Terrain heights must be finite")
        occupancy |= z <= height[:, :, None]
    for box in config.get("boxes", []):
        occupancy[_box_slice(box, shape)] = True
    for box in config.get("openings", []):
        occupancy[_box_slice(box, shape)] = False
    for box in config.get("additional_boxes", []):
        occupancy[_box_slice(box, shape)] = True
    for sphere in config.get("spheres", []):
        center = _point(sphere["center"], "Sphere center")
        radius = float(sphere["radius"])
        if not np.isfinite(radius) or radius <= 0:
            raise ValueError("Sphere radius must be finite and positive")
        occupancy |= (x - center[0]) ** 2 + (y - center[1]) ** 2 + (
            z - center[2]
        ) ** 2 <= radius**2
    grid = OccupancyMap(occupancy, origin, spacing)
    start = _point(config["start"], "Start")
    goal = _point(config["goal"], "Goal")
    for name, point in (("start", start), ("goal", goal)):
        if not validate_path([point, point], grid).valid:
            raise ValueError(f"Scenario has an invalid {name}")
    witness_config = config.get("witness_path")
    witness = (
        None
        if witness_config is None
        else [_point(point, "Witness point") for point in witness_config]
    )
    reachability = config["reachability"]
    if reachability == "certified_reachable":
        if (
            witness is None
            or len(witness) < 2
            or witness[0] != start
            or witness[-1] != goal
        ):
            raise ValueError("Reachable maps require an endpoint-matching witness")
        if not validate_path(witness, grid).valid:
            raise ValueError("Scenario witness is not strictly collision-free")
    elif reachability == "certified_unreachable":
        if witness is not None:
            raise ValueError("Unreachable maps must not supply a witness path")
        _check_barrier(grid, start, goal, config.get("certificate", {}))
    else:
        raise ValueError("Unknown reachability label")
    metadata = {
        "kind": kind,
        "world_z_offset": config.get("world_z_offset", 0),
        "certificate": config.get("certificate"),
        "generation": "deterministic_recipe_no_stochastic_draws",
        "rasterization": "physical_cell_center_inclusion_then_closed_voxel_boxes",
    }
    return Scenario(
        str(config["scene_id"]),
        grid,
        start,
        goal,
        int(config["map_seed"]),
        str(config["description"]),
        witness,
        reachability,
        metadata,
    )


def _read_configs(config_path: Path) -> list[dict[str, Any]]:
    document = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported scenario configuration schema")
    configs = [{**document["profile"], **scene} for scene in document["scenarios"]]
    ids = [config["scene_id"] for config in configs]
    if len(ids) != len(set(ids)):
        raise ValueError("Scenario identifiers must be unique")
    return configs


def load_scenarios(config_path: Path) -> list[Scenario]:
    """Generate all configured maps once; reject invalid reachability evidence."""
    return [generate_scenario(config) for config in _read_configs(config_path)]


def load_scenario(config_path: Path, scene_id: str) -> Scenario:
    """Generate one selected map without loading unrelated scenarios."""
    for config in _read_configs(config_path):
        if config["scene_id"] == scene_id:
            return generate_scenario(config)
    raise ValueError(f"Unknown scene identifier: {scene_id}")
