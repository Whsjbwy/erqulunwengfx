"""Fixed obstacle recipes and hidden supplied-control reachability witnesses."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.maps import Scene, read_config
from ..stage5a.tracking import State, integrate
from ..stage6b.scenarios import Scenario


def box_slices(box: list[float], spacing: list[float]) -> tuple[slice, ...]:
    """Require voxel-aligned closed occupied boxes with explicit coordinates."""
    result = []
    for axis, step in enumerate(spacing):
        low, high = box[2 * axis : 2 * axis + 2]
        indexes = (low / step, high / step)
        if low < 0 or high <= low or any(abs(x - round(x)) > 1e-10 for x in indexes):
            raise ValueError("Map boxes must be ordered and voxel aligned")
        result.append(slice(round(indexes[0]), round(indexes[1])))
    return tuple(result)


def build_scenarios() -> list[Scenario]:
    """Generate every registered development map without search feedback."""
    config = read_config("stage6d_maps.json")
    spacing = config["spacing_m"]
    shape = tuple(
        round(a / b) for a, b in zip(config["extent_m"], spacing, strict=True)
    )
    scenarios = []
    for spec in config["maps"]:
        occupied = np.full(shape, "free_boxes" in spec, dtype=bool)
        for box in spec.get("boxes", []):
            occupied[box_slices(box, spacing)] = True
        for box in spec.get("free_boxes", []):
            occupied[box_slices(box, spacing)] = False
        grid = OccupancyMap(occupied, spacing=tuple(spacing))
        ceiling = None
        if "ceiling_z_m" in spec:
            values = np.zeros(shape, dtype=bool)
            values[:, :, round(spec["ceiling_z_m"] / spacing[2]) :] = True
            ceiling = OccupancyMap(values, spacing=tuple(spacing))
        initial = State(
            tuple(spec["start"]),
            math.radians(spec["yaw_deg"]),
            math.radians(spec["pitch_deg"]),
            1.0,
        )
        controls = tuple(
            {
                "yaw_rate_rad_s": math.radians(yaw),
                "pitch_rate_rad_s": math.radians(pitch),
                "duration_s": float(duration),
            }
            for yaw, pitch, duration in spec["controls"]
        )
        final = initial
        for control in controls:
            for _ in range(round(control["duration_s"] / 0.1)):
                final = integrate(
                    final, control["yaw_rate_rad_s"], control["pitch_rate_rad_s"], 0.1
                )
        scene = Scene(
            {"id": spec["id"], "family": spec["family"]},
            grid,
            ceiling,
            initial.position,
            final.position,
            None,
        )
        scenarios.append(
            Scenario(
                spec["id"],
                scene,
                initial,
                controls,
                "ok",
                "known_control_witness_pending_certification",
                spec["id"] + "_physical",
                spec["id"] + "_ceiling" if ceiling else None,
            )
        )
    return scenarios


def roster(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    """Register all54 conditions before observing any baseline outcomes."""
    cfg = protocol["d2"]
    return [
        {
            "job_id": f"{name}--{condition['id']}--seed{seed}",
            "scenario": name,
            "seed": seed,
            **condition,
        }
        for name in cfg["maps"]
        for seed in cfg["seeds"]
        for condition in cfg["conditions"]
    ]
