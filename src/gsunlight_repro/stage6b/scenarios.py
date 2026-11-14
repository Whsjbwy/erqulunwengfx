"""Frozen analytic and historical development scenarios for native baselines."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.maps import ROOT, Scene, body_radius, read_config
from ..stage5a.tracking import State, integrate
from ..stage5af.maps import generate


@dataclass(frozen=True, slots=True)
class Scenario:
    """One immutable task and optional hidden supplied-control witness."""

    id: str
    scene: Scene
    initial: State
    witness_controls: tuple[dict[str, float], ...]
    expected_reason: str
    reachability: str
    physical_key: str
    ceiling_key: str | None = None


def state_values(state: State) -> list[float]:
    """Serialize the five states plus the frozen, nondynamic speed parameter."""
    return [*state.position, state.yaw, state.pitch, state.speed]


def effective_radius() -> float:
    """Use the historical circumsphere and unchanged extra safety margin."""
    vehicle = read_config("stage5a_protocol.json")
    return body_radius(vehicle) + vehicle["vehicle"]["safety_margin_m"]


def analytic_scenarios() -> list[Scenario]:
    """Reconstruct all twelve registered 6A cases without changing their inputs."""
    protocol = read_config("stage6a_feasibility_protocol.json")
    vehicle = read_config("stage5a_protocol.json")
    shape = tuple(
        int(round(length / spacing))
        for length, spacing in zip(
            protocol["extent_m"], protocol["spacing_m"], strict=True
        )
    )
    empty = np.zeros(shape, dtype=bool)
    obstacle = empty.copy()
    obstacle[60:62, 35:45, 26:34] = True
    result = []
    for spec in protocol["cases"]:
        has_obstacle = bool(spec.get("obstacle"))
        grid = OccupancyMap(
            obstacle if has_obstacle else empty,
            spacing=tuple(protocol["spacing_m"]),
        )
        ceiling = None
        ceiling_key = None
        if "ceiling_z_m" in spec:
            top = np.zeros(shape, dtype=bool)
            top[:, :, int(spec["ceiling_z_m"] / protocol["spacing_m"][2]) :] = True
            ceiling = OccupancyMap(top, spacing=tuple(protocol["spacing_m"]))
            ceiling_key = f"analytic_ceiling_{spec['ceiling_z_m']}"
        initial = State(
            tuple(protocol["start_position_m"]),
            0.0,
            math.radians(spec.get("initial_pitch_deg", 0)),
            float(spec.get("initial_speed_m_s", vehicle["kinematics"]["speed_m_s"])),
        )
        controls = tuple(
            {
                "yaw_rate_rad_s": math.radians(yaw),
                "pitch_rate_rad_s": math.radians(pitch),
                "duration_s": float(duration),
            }
            for yaw, pitch, duration in spec["controls_deg_s_duration_s"]
        )
        endpoint = initial
        # Only defines the registered target; never provides controls to a planner.
        for control in controls:
            count = round(control["duration_s"] / protocol["step_s"])
            for _ in range(count):
                endpoint = integrate(
                    endpoint,
                    control["yaw_rate_rad_s"],
                    control["pitch_rate_rad_s"],
                    protocol["step_s"],
                )
        scene = Scene(
            {"id": spec["id"], "family": "supplied_control_acceptance"},
            grid,
            ceiling,
            initial.position,
            endpoint.position,
            None,
        )
        result.append(
            Scenario(
                spec["id"],
                scene,
                initial,
                controls,
                spec["expected"],
                "known_control_witness"
                if spec["expected"] == "ok"
                else "negative_input",
                "analytic_obstacle" if has_obstacle else "analytic_empty",
                ceiling_key,
            )
        )
    return result


def mid_segment_scenario() -> Scenario:
    """Construct a 0.1-second segment with free endpoints and a colliding middle."""
    shape, spacing = (160, 160, 80), (0.5, 0.5, 0.5)
    values = np.zeros(shape, dtype=bool)
    values[60, 40, 30] = True
    radius = effective_radius()
    distance = radius - 0.0004
    middle = np.array(
        (30 - distance / math.sqrt(2), 20 - distance / math.sqrt(2), 15.25)
    )
    tangent = np.array((1, -1, 0)) / math.sqrt(2)
    start, end = middle - 0.05 * tangent, middle + 0.05 * tangent
    initial = State(tuple(float(x) for x in start), -math.pi / 4, 0.0, 1.0)
    goal = tuple(float(x) for x in end)
    scene = Scene(
        {"id": "mid_segment_reject", "family": "continuous_safety_counterexample"},
        OccupancyMap(values, spacing=spacing),
        None,
        initial.position,
        goal,
        None,
    )
    return Scenario(
        "mid_segment_reject",
        scene,
        initial,
        ({"yaw_rate_rad_s": 0.0, "pitch_rate_rad_s": 0.0, "duration_s": 0.1},),
        "physical_obstacle",
        "negative_continuous_safety",
        "mid_segment_obstacle",
    )


def historical_scenario(identity: str) -> Scenario:
    """Load one approved historical F development map without altering its recipe."""
    if identity not in ("F_O1", "F_N1", "F_B1"):
        raise ValueError("Historical Stage6B tasks are limited to F_O1/F_N1/F_B1")
    document = read_config("stage5af_maps.json")
    spec = next(item for item in document["maps"] if item["id"] == identity)
    scene = generate(spec, document)
    initial = State(
        scene.start,
        math.atan2(scene.goal[1] - scene.start[1], scene.goal[0] - scene.start[0]),
        0.0,
        1.0,
    )
    return Scenario(
        identity,
        scene,
        initial,
        (),
        "not_a_supplied_control_case",
        "geometry_only_kinodynamic_unknown",
        identity + "_physical",
        identity + "_ceiling" if scene.ceiling is not None else None,
    )


def _cache_grid(grid: OccupancyMap, key: str, folder: Path) -> dict[str, Any]:
    """Write a semantic map once and reject an inconsistent existing cache."""
    if not key.replace("_", "").isalnum():
        raise ValueError("Grid cache key must be a simple identifier")
    path = folder / f"{key}.u8"
    data = grid.occupancy.astype(np.uint8).tobytes(order="C")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Existing grid cache differs from frozen map: {key}")
    else:
        with path.open("xb") as stream:
            stream.write(data)
    return {
        "shape": list(grid.shape),
        "origin": list(grid.origin),
        "spacing": list(grid.spacing),
        "data_file": str(path.resolve()),
    }


def export_scenario(scenario: Scenario, cache_directory: Path) -> dict[str, Any]:
    """Export native task inputs while keeping cached grids outside Git history."""
    folder = cache_directory.resolve()
    if folder.is_relative_to(ROOT):
        raise ValueError("Native numeric grids must remain outside the repository")
    folder.mkdir(parents=True, exist_ok=True)
    ceiling = None
    if scenario.scene.ceiling is not None:
        if scenario.ceiling_key is None:
            raise ValueError("A mission ceiling requires a declared semantic cache key")
        ceiling = _cache_grid(scenario.scene.ceiling, scenario.ceiling_key, folder)
    return {
        "id": scenario.id,
        "physical": _cache_grid(scenario.scene.grid, scenario.physical_key, folder),
        "ceiling": ceiling,
        "initial": state_values(scenario.initial),
        "goal": list(scenario.scene.goal),
        "radius_m": effective_radius(),
    }
