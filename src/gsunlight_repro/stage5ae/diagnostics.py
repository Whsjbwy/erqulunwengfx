"""Local reference safety tubes and auditable global projection discontinuities."""

from __future__ import annotations

import math

import numpy as np

from ..stage5a.tracking import Route
from .guidance import project


def local_gap(route: Route, progress: float, geometry) -> float:
    """Bound a one-metre reference neighborhood, splitting at every corner."""
    low, high = max(0.0, progress - 0.5), min(route.cumulative[-1], progress + 0.5)
    knots = [
        low,
        *route.cumulative[(route.cumulative > low) & (route.cumulative < high)],
        high,
    ]
    return min(
        geometry.clearance(route.target(a), route.target(b), mission=True)
        for a, b in zip(knots[:-1], knots[1:], strict=True)
    )


def detail(result, path: list, scene, radius: float) -> tuple[dict, list[dict]]:
    """Locate first failure and nearest-map jumps; neither replaces certification."""
    summary, trace = result.summary, result.trace
    if not trace:
        return {"first_failure_time_start_s": None, "first_failure_time_s": None}, []
    route = Route(path)
    # Evaluate all positions at once, preserving the original argmin tie rule.
    positions = np.array([row["start_position"] for row in trace])
    delta = positions[:, None] - route.points[None, :-1]
    fraction = np.divide(
        np.einsum("nsi,si->ns", delta, route.edges),
        route.lengths**2,
        out=np.zeros(delta.shape[:2]),
        where=route.lengths > 0,
    ).clip(0, 1)
    errors = np.linalg.norm(delta - fraction[:, :, None] * route.edges, axis=2)
    indices = np.argmin(errors, axis=1)
    projections = (
        route.cumulative[indices]
        + fraction[np.arange(len(indices)), indices] * route.lengths[indices]
    )
    changes = np.diff(projections)
    jumps = [
        {
            "time_s": trace[i + 1]["time_start_s"],
            "from_segment": int(indices[i]),
            "to_segment": int(indices[i + 1]),
            "projection_change_m": float(changes[i]),
            "position_step_m": math.dist(positions[i], positions[i + 1]),
        }
        for i in np.flatnonzero(np.abs(changes) > 0.5)
    ]
    extras = {
        "max_abs_projection_step_m": float(np.max(np.abs(changes)))
        if len(changes)
        else 0.0,
        "projection_jump_markers": len(jumps),
    }
    if summary["execution_success"]:
        return extras, jumps
    reason = summary["primary_class"]
    predicate = (
        (lambda row: row["margin_reason"] != "ok")
        if reason == "margin_only_failure"
        else (lambda row: row["physical_reason"] != "ok")
        if reason == "swept_safety_reject"
        else (lambda row: row["mission_reason"] == "mission_ceiling")
        if reason == "mission_band_reject"
        else (lambda row: row["cross_track_m"] > 3)
        if reason == "tracking_error_limit"
        else (lambda row: False)
    )
    event = next((row for row in trace if predicate(row)), trace[-1])
    progress, error, segment = project(route, event["position"])
    gap = local_gap(route, progress, scene.geometry(radius))
    extras.update(
        {
            "first_failure_time_start_s": event["time_start_s"],
            "first_failure_time_s": event["time_s"],
            "first_failure_position": event["position"],
            "failure_reference_progress_m": progress,
            "failure_nearest_segment": segment,
            "failure_controller_progress_m": event["progress_m"],
            "failure_target": event["target"],
            "failure_yaw_rad": event["yaw_rad"],
            "failure_pitch_rad": event["pitch_rad"],
            "failure_yaw_saturated": event["yaw_saturated"],
            "failure_pitch_saturated": event["pitch_saturated"],
            "failure_local_reference_gap_m": gap,
            "failure_nearest_error_m": error,
            "failure_error_gap_ratio": error / gap if gap > 1e-9 else None,
            "failure_physical_reason": event["physical_reason"],
            "failure_mission_reason": event["mission_reason"],
        }
    )
    return extras, jumps
