"""Prospective seeded metre-scale scenes, independent of all historical maps."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..map_reader import OccupancyMap, Point
from .geometry import TOLERANCE, Geometry

ROOT = Path(__file__).resolve().parents[3]


def read_config(name: str) -> dict:
    """Read a repository-relative frozen UTF-8 configuration."""
    return json.loads((ROOT / "configs" / name).read_text(encoding="utf-8"))


def body_radius(protocol: dict) -> float:
    """Circumscribe the full assumed cylindrical body at every orientation."""
    vehicle = protocol["vehicle"]
    return math.hypot(vehicle["length_m"] / 2, vehicle["diameter_m"] / 2)


def mode_radius(mode: str, protocol: dict) -> float:
    """Return the explicitly named planning envelope radius."""
    radii = {
        "point": 0.0,
        "body": body_radius(protocol),
        "margin": body_radius(protocol) + protocol["vehicle"]["safety_margin_m"],
    }
    return radii[mode]


@dataclass(slots=True)
class Scene:
    """Physical seabed/obstacles and a separately labelled mission ceiling."""

    specification: dict
    grid: OccupancyMap
    ceiling: OccupancyMap | None
    start: Point
    goal: Point
    witness: list[Point] | None
    heights: np.ndarray | None = None

    def geometry(self, radius: float) -> Geometry:
        """Construct a fresh counted validator without modifying voxel data."""
        return Geometry(self.grid, radius, self.ceiling)

    def reachability(self, radius: float) -> str:
        """Use a geometric witness or analytic separating-wall aperture proof."""
        if self.specification["family"] == "sealed":
            return "certified_unreachable_full_barrier"
        width = self.specification.get("opening_m")
        if width is not None and 2 * (radius + TOLERANCE) >= width:
            return "certified_unreachable_aperture"
        if self.witness is not None and self.geometry(radius).path(self.witness).valid:
            return "certified_reachable_geometry_only"
        return "unknown"


def load_scene(scene_id: str, document: dict | None = None) -> Scene:
    """Generate only the listed scene; no rejection based on planner outcomes."""
    config = document or read_config("stage5a_maps.json")
    spec = next(item for item in config["maps"] if item["id"] == scene_id)
    rng = np.random.default_rng(spec["seed"])
    extent = np.asarray(config[spec["scale"] + "_extent_m"], dtype=float)
    spacing = np.asarray(config["spacing"], dtype=float)
    shape = tuple(np.rint(extent / spacing).astype(int))
    values = np.zeros(shape, dtype=bool)
    family = spec["family"]
    start = (3.5, 3.5, 4.0)
    goal = (float(extent[0] - 3.5), float(extent[1] - 3.5), 4.0)
    ceiling = None
    heights = None
    witness: list[Point] | None = None

    def box(lower: list[float], upper: list[float], occupied: bool = True) -> None:
        lo, hi = (
            np.rint(np.asarray(lower) / spacing).astype(int),
            np.rint(np.asarray(upper) / spacing).astype(int),
        )
        if np.any(lo < 0) or np.any(hi > shape) or np.any(lo >= hi):
            raise ValueError("New map box is outside its declared workspace")
        values[
            tuple(
                slice(int(left), int(right)) for left, right in zip(lo, hi, strict=True)
            )
        ] = occupied

    if family == "empty":
        witness = [start, goal]
    elif family == "ordinary":
        middle = extent[0] / 2 + float(rng.integers(-1, 2)) * 0.5
        if spec.get("ordinary_variant") == "offset_blocks":
            # Prospective O2 correction; all other map recipes stay unchanged.
            middle = 0.55 * extent[0]
            box([middle - 2, 8, 0], [middle + 2, float(extent[1] - 7), 16])
            box([11, 3, 0], [16, 12, 9])
            box([35, 23, 0], [41, 34, 11])
        else:
            box(
                [middle - 2, 2 if spec["scale"] == "small" else 10, 0],
                [
                    middle + 2,
                    float(extent[1] - 5),
                    7 if spec["scale"] == "small" else 14,
                ],
            )
            if spec["scale"] == "main":
                box([10, 2, 0], [15, 10, 8])
                box([35, 25, 0], [40, 34, 10])
        top = float(extent[2] - 1.5)
        witness = [start, (start[0], start[1], top), (goal[0], goal[1], top), goal]
    elif family in ("narrow", "sealed"):
        left = float(extent[0] / 2)
        right = left + (1 if spec["scale"] == "small" else 2)
        box([left, 0, 0], [right, float(extent[1]), float(extent[2])])
        if family == "narrow":
            width = spec["opening_m"]
            yl, zl = (
                (11.0, 5.0)
                if spec["scale"] == "small"
                else (23.0, 5.0 if width == 3.5 else 5.5)
            )
            box([left, yl, zl], [right, yl + width, zl + width], False)
            z = zl + width / 2
            start, goal = (
                (3.5, 3.5, z),
                (float(extent[0] - 3.5), float(extent[1] - 3.5), z),
            )
            witness = [
                start,
                (left - 2, yl + width / 2, z),
                (right + 2, yl + width / 2, z),
                goal,
            ]
    elif family == "near_seabed":
        x = (np.arange(shape[0]) + 0.5) * spacing[0]
        y = (np.arange(shape[1]) + 0.5) * spacing[1]
        xx, yy = np.meshgrid(x, y, indexing="ij")
        sigma = 4 if spec["scale"] == "small" else 8
        amplitude = 3 if spec["scale"] == "small" else 8
        cx, cy = extent[:2] / 2 + rng.uniform(-1, 1, 2)
        surface = 2 + amplitude * np.exp(
            -((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma**2)
        )
        if spec["seed"] % 2 == 0:
            heading = math.atan2(goal[1] - start[1], goal[0] - start[0])
            along = (xx - cx) * math.cos(heading) + (yy - cy) * math.sin(heading)
            cross = -(xx - cx) * math.sin(heading) + (yy - cy) * math.cos(heading)
            # Two elongated flanks form a canyon around the diagonal valley.
            for side in (-1, 1):
                surface += (
                    0.4
                    * amplitude
                    * np.exp(
                        -0.5
                        * (
                            (along / (1.3 * sigma)) ** 2
                            + ((cross - side * 0.85 * sigma) / (0.23 * sigma)) ** 2
                        )
                    )
                )
            surface += 2 * np.exp(
                -((xx - 0.65 * extent[0]) ** 2 + (yy - 0.7 * extent[1]) ** 2)
                / (2 * (0.7 * sigma) ** 2)
            )
        heights = np.ceil(surface / spacing[2]) * spacing[2]
        z_lower = np.arange(shape[2]) * spacing[2]
        values |= (z_lower + spacing[2])[None, None, :] <= heights[:, :, None]
        ceiling_values = z_lower[None, None, :] >= heights[:, :, None] + 6
        ceiling_values.setflags(write=False)
        ceiling = OccupancyMap(ceiling_values, spacing=tuple(spacing))

        def above(xp: float, yp: float) -> Point:
            i, j = int(xp / spacing[0]), int(yp / spacing[1])
            return xp, yp, float(heights[i, j] + 3)

        start, goal = above(start[0], start[1]), above(goal[0], goal[1])
        count = int(math.ceil(math.dist(start[:2], goal[:2]) / 0.5))
        witness = [
            above(float(xp), float(yp))
            for xp, yp in np.linspace(start[:2], goal[:2], count + 1)
        ]
    else:
        raise ValueError(f"Unknown map family: {family}")
    values.setflags(write=False)
    grid = OccupancyMap(values, spacing=tuple(spacing))
    return Scene(dict(spec), grid, ceiling, start, goal, witness, heights)
