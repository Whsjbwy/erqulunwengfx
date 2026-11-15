"""One predeclared terminal-reference representation and independent checks."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..map_reader import Point
from ..stage5a.geometry import Geometry
from ..stage5a.maps import body_radius, read_config
from ..stage5a.tracking import Route, chord_error_bound, integrate, wrap
from ..stage6b.scenarios import Scenario, effective_radius


def dense_reference(scenario: Scenario, trace: list[dict[str, Any]]) -> list[Point]:
    """Keep the original sampled control path and the reference-only goal bridge."""
    points = [scenario.initial.position] + [tuple(row["position"]) for row in trace]
    if math.dist(points[-1], scenario.scene.goal) > 0.75:
        raise ValueError("Reference source does not finish inside the frozen goal ball")
    if points[-1] != scenario.scene.goal:
        points.append(scenario.scene.goal)
    return points


def tail_reference(path: list[Point], tail_arc_m: float = 2.0) -> list[Point]:
    """Replace the final original arc window by one chord, preserving its prefix."""
    points = np.asarray(path, dtype=float)
    if (
        points.ndim != 2
        or points.shape[1] != 3
        or len(points) < 2
        or not np.isfinite(points).all()
        or not math.isfinite(tail_arc_m)
        or tail_arc_m <= 0
    ):
        raise ValueError(
            "Reference needs finite 3D vertices and a positive tail window"
        )
    route = Route(path)
    anchor_s = max(0.0, float(route.cumulative[-1]) - tail_arc_m)
    prefix = route.points[route.cumulative < anchor_s - 1e-12].tolist()
    prefix.extend([route.target(anchor_s).tolist(), route.points[-1].tolist()])
    # Route applies the same frozen duplicate-vertex convention as the controller.
    return [tuple(float(x) for x in point) for point in Route(prefix).points]


def certify_reference(path: list[Point], scenario: Scenario) -> dict[str, Any]:
    """Check every whole reference chord using the frozen full effective sphere."""
    geometry = Geometry(scenario.scene.grid, effective_radius(), scenario.scene.ceiling)
    verdict = geometry.path(path)
    endpoints = (
        math.dist(path[0], scenario.scene.start) <= 1e-10
        and math.dist(path[-1], scenario.scene.goal) <= 1e-10
    )
    return {
        "reference_geometry_safe": bool(verdict.valid and endpoints),
        "reference_rejection": verdict.reason
        if not verdict.valid
        else "ok"
        if endpoints
        else "endpoints",
        "reference_length_m": float(Route(path).cumulative[-1]),
        "reference_vertices": len(Route(path).points),
    }


def certify_los(trace: list[dict[str, Any]], scenario: Scenario) -> dict[str, Any]:
    """Reintegrate saved LOS controls and recheck all recorded continuous verdicts."""
    vehicle = read_config("stage5a_protocol.json")
    radius = body_radius(vehicle)
    oracles = {
        "physical": Geometry(scenario.scene.grid, radius),
        "mission": Geometry(scenario.scene.grid, radius, scenario.scene.ceiling),
        "margin": Geometry(
            scenario.scene.grid, effective_radius(), scenario.scene.ceiling
        ),
    }
    state = scenario.initial
    first_margin = None
    maximum_error = 0.0
    for index, row in enumerate(trace):
        if math.dist(state.position, row["start_position"]) > 1e-10:
            raise ValueError("Saved LOS interval starts from another state")
        yaw, pitch = float(row["yaw_rate_rad_s"]), float(row["pitch_rate_rad_s"])
        if abs(yaw) > math.pi / 18 + 1e-12 or abs(pitch) > math.pi / 36 + 1e-12:
            raise ValueError("Saved LOS rate exceeds the frozen limit")
        following = integrate(state, yaw, pitch, 0.1)
        error = math.dist(following.position, row["position"])
        maximum_error = max(error, maximum_error)
        if (
            error > 1e-10
            or abs(wrap(following.yaw - row["yaw_rad"])) > 1e-12
            or abs(following.pitch - row["pitch_rad"]) > 1e-12
            or abs(following.pitch) > math.pi / 9 + 1e-12
            or row["speed_m_s"] != 1.0
        ):
            raise ValueError("Saved LOS state differs from frozen integration/limits")
        bound = chord_error_bound(1.0, yaw, pitch, 0.1)
        for name, oracle in oracles.items():
            verdict = oracle.segment(
                state.position, following.position, extra_radius=bound
            )
            if verdict.reason != row[name + "_reason"]:
                raise ValueError(
                    f"Saved LOS {name} certificate disagrees at interval {index}"
                )
            if name == "margin" and not verdict.valid and first_margin is None:
                first_margin = index
        state = following
    return {
        "independent_los_audit_passed": True,
        "los_intervals": len(trace),
        "maximum_los_position_error_m": maximum_error,
        "full_margin_safe": first_margin is None,
        "first_margin_interval": first_margin,
        "goal_reached": math.dist(state.position, scenario.scene.goal) <= 0.75,
    }


def terminal_diagnostics(
    path: list[Point], trace: list[dict[str, Any]], bridge_m: float
) -> dict[str, Any]:
    """Record command-time switching and interval-time failure without causal labels."""
    route = Route(path)
    length = float(route.cumulative[-1])
    switches = [row for row in trace if row["terminal_switch"]]
    if len(switches) > 1:
        raise ValueError("Frozen terminal guidance must latch at most once")
    switch = switches[0] if switches else None
    margin = next((r for r in trace if r["margin_reason"] != "ok"), None)
    tracking = next((r for r in trace if r["cross_track_m"] > 3.0), None)
    result = {
        "switch_command_time_s": switch["time_start_s"] if switch else None,
        "switch_remaining_reference_arc_m": length - switch["reference_progress_m"]
        if switch
        else None,
        "switch_active_segment": switch["active_segment"] if switch else None,
        "switch_virtual_progress_m": switch["reference_progress_m"] if switch else None,
        "switch_projected_progress_m": route.projection(
            tuple(switch["start_position"])
        )[0]
        if switch
        else None,
        "last_segment_length_m": float(route.lengths[-1]),
        "goal_bridge_length_m": bridge_m,
        "first_tracking_rejected_interval_start_s": tracking["time_start_s"]
        if tracking
        else None,
        "first_tracking_rejected_interval_end_s": tracking["time_s"]
        if tracking
        else None,
        "first_margin_rejected_interval_start_s": margin["time_start_s"]
        if margin
        else None,
        "first_margin_rejected_interval_end_s": margin["time_s"] if margin else None,
        "first_margin_candidate_position": margin["position"] if margin else None,
    }
    return result
