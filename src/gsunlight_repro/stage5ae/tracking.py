"""Independent LOS tracking with unchanged 5A actuation and swept certification."""

from __future__ import annotations

import math
import time

from ..metrics import endpoints_match, path_length
from ..stage5a.geometry import Geometry
from ..stage5a.maps import Scene, body_radius
from ..stage5a.tracking import Route, State, chord_error_bound, integrate
from ..stage5ar.p0 import BASELINE
from ..stage5ar.replay import Replay, classify, control, replay
from .guidance import LOS


def simulate(
    path: list, scene: Scene, protocol: dict, margin: float, controller: dict
) -> Replay:
    """Keep legacy execution literal and provide a separate mature LOS cascade."""
    if controller["kind"] == "legacy":
        return replay(path, scene, protocol, margin, BASELINE)
    if controller["kind"] != "los3d":
        raise ValueError("Unknown execution controller")
    started = time.perf_counter()
    cfg = protocol["kinematics"]
    radius = body_radius(protocol)
    mission, physical, required = (
        Geometry(scene.grid, radius, scene.ceiling),
        Geometry(scene.grid, radius),
        Geometry(scene.grid, radius + margin, scene.ceiling),
    )
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
    state = State(
        scene.start,
        math.atan2(scene.goal[1] - scene.start[1], scene.goal[0] - scene.start[0]),
        0.0,
        cfg["speed_m_s"],
    )
    route = Route(path)
    guidance = LOS(route, controller["lookahead_m"])
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
        target, guidance_details = guidance.command(state, dt)
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
                "progress_m": guidance_details["reference_progress_m"],
                **guidance_details,
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
    errors = [step["cross_track_m"] for step in trace]
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
    }
    for axis in ("yaw", "pitch"):
        summary[axis + "_saturation_steps"] = sum(
            step[axis + "_saturated"] for step in trace
        )
        summary["peak_" + axis + "_rate_deg_s"] = math.degrees(
            max((abs(step[axis + "_rate_rad_s"]) for step in trace), default=0.0)
        )
    summary["peak_pitch_deg"] = math.degrees(
        max((abs(step["pitch_rad"]) for step in trace), default=0.0)
    )
    if (
        summary["peak_yaw_rate_deg_s"] > cfg["max_yaw_rate_deg_s"] + 1e-9
        or summary["peak_pitch_rate_deg_s"] > cfg["max_pitch_rate_deg_s"] + 1e-9
        or summary["peak_pitch_deg"] > cfg["max_pitch_deg"] + 1e-9
    ):
        raise RuntimeError("LOS cascade violated frozen actuation limits")
    return Replay(summary, trace)
