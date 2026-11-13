"""One instrumented execution loop for unchanged and terminal-corrected LOS.

Frozen integration, inner control, collision primitives and stop order are
reused. The adapter is verified against frozen outputs, not assumed equal.
"""

from __future__ import annotations

import math
import time

import numpy as np

from ..metrics import endpoints_match, path_length
from ..stage5a.geometry import Geometry
from ..stage5a.maps import Scene, body_radius
from ..stage5a.tracking import Route, State, chord_error_bound, integrate
from ..stage5ae.guidance import LOS
from ..stage5ar.replay import Replay, classify, control
from .guidance import TerminalLOS


def simulate(
    path: list,
    scene: Scene,
    vehicle: dict,
    margin: float,
    settings: dict,
    *,
    corrected: bool = True,
    initial: State | None = None,
    initial_progress: float = 0.0,
) -> Replay:
    """Execute one guidance object with identical actuation and continuous checks."""
    started = time.perf_counter()
    cfg, radius = vehicle["kinematics"], body_radius(vehicle)
    mission = Geometry(scene.grid, radius, scene.ceiling)
    physical = Geometry(scene.grid, radius)
    required = Geometry(scene.grid, radius + margin, scene.ceiling)
    verdict = mission.path(path)
    if not verdict.valid or not endpoints_match(path, scene.start, scene.goal):
        reason = "geometry_rejected_before_tracking_" + (
            verdict.reason if not verdict.valid else "endpoints"
        )
        return Replay(
            {
                "eligible": False,
                "execution_success": False,
                "physical_execution_success": False,
                "steps": 0,
                "failure_reason": reason,
                "primary_class": classify(reason),
            },
            [],
        )
    state = initial or State(
        scene.start,
        math.atan2(scene.goal[1] - scene.start[1], scene.goal[0] - scene.start[0]),
        0.0,
        cfg["speed_m_s"],
    )
    route = Route(path)
    guidance = (
        TerminalLOS(route, settings["lookahead_m"], settings["terminal_distance_m"])
        if corrected
        else LOS(route, settings["lookahead_m"])
    )
    if (
        not math.isfinite(initial_progress)
        or not 0 <= initial_progress <= route.cumulative[-1]
    ):
        raise ValueError("Analytic initial progress is outside the reference path")
    if corrected:
        guidance.base.progress = initial_progress
    else:
        guidance.progress = initial_progress
    dt = cfg["step_s"]
    limit = min(600, max(60, 3 * path_length(path) / state.speed + 30))
    clearance_ok = required.segment(state.position, state.position).valid
    minimum = physical.clearance(state.position, state.position)
    mission_minimum = mission.clearance(state.position, state.position, mission=True)
    trace, reason, reached = [], "simulation_timeout", False
    while len(trace) * dt < limit:
        if math.dist(state.position, scene.goal) <= cfg["goal_tolerance_m"]:
            reached, reason = True, "goal_reached"
            break
        if time.perf_counter() - started > cfg["wall_guard_s"]:
            reason = "execution_resource_timeout"
            break
        target, details = guidance.command(state, dt)
        requested_yaw, requested_pitch, yaw_rate, pitch_rate = control(
            state, target, cfg
        )
        following = integrate(state, yaw_rate, pitch_rate, dt)
        deviation = chord_error_bound(state.speed, yaw_rate, pitch_rate, dt)
        pv = physical.segment(
            state.position, following.position, extra_radius=deviation
        )
        mv = mission.segment(state.position, following.position, extra_radius=deviation)
        rv = required.segment(
            state.position, following.position, extra_radius=deviation
        )
        clearance_ok &= rv.valid
        gap = physical.clearance(state.position, following.position) - deviation
        mission_gap = (
            mission.clearance(state.position, following.position, mission=True)
            - deviation
        )
        minimum, mission_minimum = min(minimum, gap), min(mission_minimum, mission_gap)
        _, error = route.projection(following.position)
        to_goal = np.array(scene.goal) - state.position
        direction = target - state.position
        denominator = np.linalg.norm(to_goal) * np.linalg.norm(direction)
        trace.append(
            {
                "time_start_s": len(trace) * dt,
                "time_s": (len(trace) + 1) * dt,
                "start_position": state.position,
                "position": following.position,
                "start_yaw_rad": state.yaw,
                "start_pitch_rad": state.pitch,
                "yaw_rad": following.yaw,
                "pitch_rad": following.pitch,
                "speed_m_s": state.speed,
                "target": target.tolist(),
                "progress_m": details["reference_progress_m"],
                **details,
                "requested_yaw_rate_rad_s": requested_yaw,
                "requested_pitch_rate_rad_s": requested_pitch,
                "yaw_rate_rad_s": yaw_rate,
                "pitch_rate_rad_s": pitch_rate,
                "yaw_saturated": abs(requested_yaw - yaw_rate) > 1e-12,
                "pitch_saturated": abs(requested_pitch - pitch_rate) > 1e-12,
                "cross_track_m": error,
                "physical_reason": pv.reason,
                "mission_reason": mv.reason,
                "margin_reason": rv.reason,
                "chord_error_bound_m": deviation,
                "physical_clearance_lower_bound_m": gap,
                "mission_clearance_lower_bound_m": mission_gap,
                "goal_direction_cosine": float(direction @ to_goal / denominator)
                if denominator
                else None,
                "goal_distance_before_m": float(np.linalg.norm(to_goal)),
                "goal_distance_after_m": math.dist(following.position, scene.goal),
            }
        )
        state = following
        if not pv.valid:
            reason = "physical_sweep_rejected_" + pv.reason
            break
        if not mv.valid:
            reason = "mission_band_sweep_rejected"
            break
        if error > cfg["max_cross_track_m"]:
            reason = "tracking_error_limit"
            break
    if reached and not clearance_ok:
        reason = "goal_reached_required_margin_violated"
    errors = [row["cross_track_m"] for row in trace]
    switches = [i for i, row in enumerate(trace) if row.get("terminal_switch", False)]
    terminal = [row for row in trace if row.get("terminal_mode", False)]
    summary = {
        "eligible": True,
        "execution_success": bool(reached and clearance_ok),
        "physical_execution_success": reached,
        "reached": reached,
        "required_clearance_satisfied": bool(clearance_ok),
        "failure_reason": reason,
        "primary_class": classify(reason),
        "steps": len(trace),
        "simulation_time_s": len(trace) * dt,
        "simulation_limit_s": limit,
        "tracking_wall_s": time.perf_counter() - started,
        "max_tracking_error_m": max(errors, default=0.0),
        "rms_tracking_error_m": math.sqrt(sum(x * x for x in errors) / len(errors))
        if errors
        else 0.0,
        "final_position": state.position,
        "final_position_error_m": math.dist(state.position, scene.goal),
        "min_physical_clearance_lower_bound_m": minimum,
        "min_mission_clearance_lower_bound_m": mission_minimum,
        "rate_limit_violations": 0,
        "pitch_limit_violations": 0,
        "speed_limit_violations": 0,
        "terminal_switches": len(switches),
        "terminal_switch_index": switches[0] if switches else None,
        "terminal_switch_time_s": switches[0] * dt if switches else None,
        "maximum_switch_jump_deg": max(
            (row.get("switch_direction_jump_deg", 0) for row in trace), default=0
        ),
        "terminal_distance_increase_steps": sum(
            row["goal_distance_after_m"] > row["goal_distance_before_m"]
            for row in terminal
        ),
        "minimum_terminal_goal_cosine": min(
            (
                row["goal_direction_cosine"]
                for row in terminal
                if row["goal_direction_cosine"] is not None
            ),
            default=None,
        ),
        "last_reference_progress_m": trace[-1]["progress_m"] if trace else 0.0,
    }
    for axis in ("yaw", "pitch"):
        summary[axis + "_saturation_steps"] = sum(
            row[axis + "_saturated"] for row in trace
        )
        summary["peak_" + axis + "_rate_deg_s"] = math.degrees(
            max((abs(row[axis + "_rate_rad_s"]) for row in trace), default=0)
        )
    summary["peak_pitch_deg"] = math.degrees(
        max((abs(row["pitch_rad"]) for row in trace), default=0)
    )
    if (
        summary["peak_yaw_rate_deg_s"] > cfg["max_yaw_rate_deg_s"] + 1e-9
        or summary["peak_pitch_rate_deg_s"] > cfg["max_pitch_rate_deg_s"] + 1e-9
        or summary["peak_pitch_deg"] > cfg["max_pitch_deg"] + 1e-9
        or len(switches) > 1
        or any(
            row["goal_direction_cosine"] < 1 - 1e-12
            for row in terminal
            if row["goal_direction_cosine"] is not None
        )
    ):
        raise RuntimeError("Actuation or terminal direction/switch invariant failed")
    return Replay(summary, trace)
