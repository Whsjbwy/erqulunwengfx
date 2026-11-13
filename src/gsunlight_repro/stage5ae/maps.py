"""Prospective independent scenes with new geometry, scales and task endpoints."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.maps import Scene, mode_radius


def generate(spec: dict, document: dict) -> Scene:
    """Generate exactly the declared recipe once; never reject on outcomes."""
    spacing = np.array(document["spacing"])
    extent = np.array(spec["extent_m"], dtype=float)
    shape = tuple(np.rint(extent / spacing).astype(int))
    values = np.zeros(shape, dtype=bool)
    rng = np.random.default_rng(spec["seed"])
    variant = spec["variant"]
    x, y, z = [
        (np.arange(n) + 0.5) * step for n, step in zip(shape, spacing, strict=True)
    ]
    ceiling, heights = None, None
    start = (5.0, float(6 + variant), float(6 + 0.5 * variant))
    goal = (
        float(extent[0] - 6),
        float(extent[1] - 8 - variant),
        float(8 + 0.5 * variant),
    )

    if spec["family"] == "ordinary":
        for i, fraction in enumerate((0.25, 0.44, 0.64, 0.81)):
            centre = np.array(
                [
                    extent[0] * fraction,
                    extent[1] * ((0.28, 0.67, 0.35, 0.72)[(i + variant) % 4]),
                    (5.0, 7.0, 6.0, 9.0)[i],
                ]
            )
            centre[:2] += rng.uniform(-0.8, 0.8, 2)
            radii = np.array([2.5 + 0.5 * (i % 2), 4.0 + 0.5 * variant, 4.0 + 0.5 * i])
            distance = ((x[:, None, None] - centre[0]) / radii[0]) ** 2
            distance = distance + ((y[None, :, None] - centre[1]) / radii[1]) ** 2
            distance = distance + ((z[None, None, :] - centre[2]) / radii[2]) ** 2
            values |= distance <= 1.0
        top = float(extent[2] - 2.5)
        witness = [start, (start[0], start[1], top), (goal[0], goal[1], top), goal]
    elif spec["family"] == "narrow":
        width = spec["opening_m"]
        route = []
        for i, fraction in enumerate((0.34, 0.66)):
            left = round(extent[0] * fraction * 2) / 2
            thickness = 1.5 + 0.5 * ((variant + i) % 2)
            yl = (
                round((extent[1] * (0.32 if i == 0 else 0.60) + rng.uniform(-1, 1)) * 2)
                / 2
            )
            zl = 4.5 + i + 0.5 * (variant % 2)
            a, b = int(left / spacing[0]), int((left + thickness) / spacing[0])
            values[a:b, :, :] = True
            values[
                a:b,
                int(yl / spacing[1]) : int((yl + width) / spacing[1]),
                int(zl / spacing[2]) : int((zl + width) / spacing[2]),
            ] = False
            cy, cz = yl + width / 2, zl + width / 2
            route.extend([(left - 3.0, cy, cz), (left + thickness + 3.0, cy, cz)])
        start = (5.0, 5.0 + variant, route[0][2])
        goal = (float(extent[0] - 5), float(extent[1] - 6), route[-1][2])
        witness = [start, *route, goal]
    elif spec["family"] == "near_seabed":
        xx, yy = np.meshgrid(x, y, indexing="ij")
        phase = rng.uniform(-0.4, 0.4)
        # Wave/ramp terraces, instead of the old single Gaussian hill/canyon.
        surface = (
            3.0
            + 0.035 * xx
            + 1.15
            * np.sin(xx / (7 + variant) + phase)
            * np.cos(yy / (9 - 0.5 * variant))
            + 0.45 * np.sin((xx + (-1) ** variant * yy) / 5.5)
        )
        heights = np.ceil(surface / spacing[2]) * spacing[2]
        lower_z = np.arange(shape[2]) * spacing[2]
        values = (lower_z + spacing[2])[None, None, :] <= heights[:, :, None]
        ceiling_values = lower_z[None, None, :] >= heights[:, :, None] + 6.0
        ceiling_values.setflags(write=False)
        ceiling = OccupancyMap(ceiling_values, spacing=tuple(spacing))

        def above(xp: float, yp: float) -> tuple:
            return (
                xp,
                yp,
                float(heights[int(xp / spacing[0]), int(yp / spacing[1])] + 3.0),
            )

        start = above(5.0, 6.0 + variant)
        goal = above(float(extent[0] - 6), float(extent[1] - 7 - variant))
        count = math.ceil(math.dist(start[:2], goal[:2]) / 0.4)
        witness = [
            above(float(a), float(b))
            for a, b in np.linspace(start[:2], goal[:2], count + 1)
        ]
    else:
        raise ValueError("Unknown independent map family")
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


def validate_maps(document: dict, protocol: dict) -> dict:
    """Certify all envelopes before any search, without resampling any map."""
    rows = []
    arrays = []
    for spec in document["maps"]:
        scene = generate(spec, document)
        for previous in arrays:
            if previous.shape == scene.grid.occupancy.shape and np.array_equal(
                previous, scene.grid.occupancy
            ):
                raise ValueError("Independent map geometry duplicated")
        arrays.append(scene.grid.occupancy)
        reachability = {
            mode: scene.reachability(mode_radius(mode, protocol))
            for mode in ("body", "margin")
        }
        if reachability["body"] != "certified_reachable_geometry_only":
            raise ValueError(f"Declared body witness invalid: {spec['id']}")
        if (
            spec["id"] != "E_N4"
            and reachability["margin"] != "certified_reachable_geometry_only"
        ):
            raise ValueError(f"Declared margin witness invalid: {spec['id']}")
        rows.append(
            {
                **spec,
                "shape": scene.grid.shape,
                "start": scene.start,
                "goal": scene.goal,
                "reachability": reachability,
                "occupied_fraction": float(scene.grid.occupancy.mean()),
            }
        )
    return {
        "passed": True,
        "maps": rows,
        "map_count": len(rows),
        "old_extent_reused": False,
        "outcome_based_resampling": False,
    }
