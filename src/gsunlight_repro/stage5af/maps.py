"""Prospective slanted baffles, carved corridors and forced-climb ridge scenes."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.maps import Scene, mode_radius


def generate(spec: dict, document: dict) -> Scene:
    """Generate only the registered recipe, without outcome-based rejection."""
    spacing = np.array(document["spacing"])
    extent = np.array(spec["extent_m"], dtype=float)
    shape = tuple(np.rint(extent / spacing).astype(int))
    x, y, z = [
        (np.arange(n) + 0.5) * step for n, step in zip(shape, spacing, strict=True)
    ]
    values = np.zeros(shape, dtype=bool)
    heights, ceiling = None, None
    variant = spec["variant"]
    start = (5.0, 6.0, 6.5 + 0.5 * variant)
    goal = (float(extent[0] - 5), float(extent[1] - 6), 8.0 + 0.5 * variant)
    if spec["family"] == "ordinary":
        jitter = np.random.default_rng(spec["seed"]).uniform(-0.5, 0.5)
        first = (
            abs(
                x[:, None]
                - (0.35 * extent[0] + 0.15 * (y[None, :] - extent[1] / 2) + jitter)
            )
            <= 1
        )
        second = (
            abs(
                x[:, None]
                - (0.68 * extent[0] - 0.18 * (y[None, :] - extent[1] / 2) - jitter)
            )
            <= 1
        )
        wall = (first & (y[None, :] <= extent[1] - 9)) | (second & (y[None, :] >= 9))
        values = wall[:, :, None] & (z[None, None, :] <= extent[2] - 4)
        top = float(extent[2] - 2)
        witness = [start, (start[0], start[1], top), (goal[0], goal[1], top), goal]
    elif spec["family"] == "narrow":
        values[:] = True
        width = spec["opening_m"]
        offset = 0.25 if width == 2.5 else 0.0
        a, b = (
            round(0.30 * extent[0] * 2) / 2 + offset,
            round(0.65 * extent[0] * 2) / 2 + offset,
        )
        low, mid, high = (
            6 + offset,
            round(0.55 * extent[1] * 2) / 2 + offset,
            extent[1] - 6 - offset,
        )
        start, goal = (
            (5 + offset, low, 8.0),
            (float(extent[0] - 5 - offset), float(high), 9.0),
        )
        witness = [
            start,
            (a, low, 8.0),
            (a, mid, 8.5),
            (b, mid, 8.5),
            (b, high, 9.0),
            goal,
        ]

        def carve(left: tuple, right: tuple, halfwidth: float) -> None:
            padding = np.array([halfwidth, halfwidth, 3.0])
            lower = np.minimum(left, right) - padding
            upper = np.maximum(left, right) + padding
            region = (
                (x[:, None, None] >= lower[0])
                & (x[:, None, None] < upper[0])
                & (y[None, :, None] >= lower[1])
                & (y[None, :, None] < upper[1])
                & (z[None, None, :] >= lower[2])
                & (z[None, None, :] < upper[2])
            )
            values[region] = False

        for left, right in zip(witness[:-1], witness[1:], strict=True):
            carve(left, right, width / 2)
        carve(start, start, 4.0)
        carve(goal, goal, 4.0)
    elif spec["family"] == "near_seabed":
        xx, yy = np.meshgrid(x, y, indexing="ij")
        ridge = np.clip(
            np.minimum((xx / extent[0] - 0.12) / 0.28, (0.88 - xx / extent[0]) / 0.28),
            0,
            1,
        )
        heights = (
            np.ceil(
                (3 + spec["ridge_height_m"] * ridge + 1.5 * (yy / extent[1] - 0.5))
                / 0.5
            )
            * 0.5
        )
        lower_z = np.arange(shape[2]) * spacing[2]
        values = (lower_z + spacing[2])[None, None, :] <= heights[:, :, None]
        ceiling = OccupancyMap(
            lower_z[None, None, :] >= heights[:, :, None] + 6, spacing=tuple(spacing)
        )

        def above(xp: float, yp: float) -> tuple:
            return (
                xp,
                yp,
                float(heights[int(xp / spacing[0]), int(yp / spacing[1])] + 3),
            )

        start, goal = above(5.0, 6.0), above(float(extent[0] - 6), float(extent[1] - 7))
        count = math.ceil(math.dist(start[:2], goal[:2]) / 0.25)
        witness = [
            above(float(a), float(b))
            for a, b in np.linspace(start[:2], goal[:2], count + 1)
        ]
    else:
        raise ValueError("Unregistered map family")
    values.setflags(write=False)
    return Scene(
        dict(spec),
        OccupancyMap(values, spacing=tuple(spacing)),
        ceiling,
        start,
        goal,
        witness,
        heights,
    )


def validate(document: dict, vehicle: dict) -> dict:
    """Require nominal witnesses and blocked direct lines before any search."""
    rows = []
    for spec in document["maps"]:
        scene = generate(spec, document)
        reachable = {
            mode: scene.reachability(mode_radius(mode, vehicle))
            for mode in ("body", "margin")
        }
        direct = (
            scene.geometry(mode_radius("body", vehicle))
            .segment(scene.start, scene.goal)
            .valid
        )
        if direct or not reachable["body"].startswith("certified_reachable"):
            raise ValueError(f"Prospective geometric acceptance failed: {spec['id']}")
        expected = (
            "certified_unreachable_aperture"
            if spec["id"] == "F_N4"
            else "certified_reachable_geometry_only"
        )
        if reachable["margin"] != expected:
            raise ValueError(f"Margin witness/certificate failed: {spec['id']}")
        rows.append(
            {
                **spec,
                "start": scene.start,
                "goal": scene.goal,
                "reachability": reachable,
                "nominal_direct_valid": direct,
                "occupied_fraction": float(scene.grid.occupancy.mean()),
            }
        )
    return {"passed": True, "maps": rows, "outcome_based_resampling": False}
