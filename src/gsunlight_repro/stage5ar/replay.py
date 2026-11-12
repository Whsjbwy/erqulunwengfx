"""Instrumented replay, reusing frozen primitives and preserving update order.

The original tracker has no state/trace hook. This independently instrumented
loop is therefore checked against the untouched original for every baseline.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from ..map_reader import Point
from ..metrics import endpoints_match, path_length
from ..stage5a.geometry import Geometry
from ..stage5a.maps import Scene, body_radius
from ..stage5a.tracking import Route, State, chord_error_bound, integrate, wrap


@dataclass(slots=True)
class Replay:
    """Compact outcome and the single full-resolution local trace."""

    summary: dict
    trace: list[dict]


def classify(reason: str) -> str:
    """Map detailed reasons to mutually exclusive diagnostic outcomes."""
    if reason.startswith("geometry_rejected_before_tracking"):
        return "geometry_precheck_reject"
    if reason.startswith("physical_sweep_rejected"):
        return "swept_safety_reject"
    categories = {
        "mission_band_sweep_rejected": "mission_band_reject",
        "tracking_error_limit": "tracking_error_limit",
        "simulation_timeout": "goal_not_reached",
        "execution_resource_timeout": "resource_timeout",
        "goal_reached_required_margin_violated": "margin_only_failure",
        "goal_reached": "success",
    }
    if reason not in categories:
        raise ValueError(f"Unclassified execution reason: {reason}")
    return categories[reason]


def initial_state(path: list[Point], scene: Scene, condition: dict) -> State:
    """Set the declared heading without altering the task goal or polyline."""
    direction = np.asarray(scene.goal) - scene.start
    if condition["initial_yaw"] == "first_segment":
        for edge in np.diff(np.asarray(path), axis=0):
            if np.linalg.norm(edge[:2]) > 1e-12:
                direction = edge
                break
        else:
            raise ValueError("First-segment yaw is undefined for a vertical route")
    elif condition["initial_yaw"] != "goal":
        raise ValueError("Unknown initial yaw condition")
    return State(
        scene.start,
        math.atan2(direction[1], direction[0]),
        0.0,
        condition["speed_m_s"],
    )


def control(state: State, target: np.ndarray, cfg: dict) -> tuple[float, ...]:
    """Apply exactly the frozen proportional angular control and clipping."""
    direction = target - state.position
    desired_yaw = math.atan2(direction[1], direction[0])
    desired_pitch = math.atan2(direction[2], math.hypot(direction[0], direction[1]))
    requested_yaw = cfg["angle_gain_s_inv"] * wrap(desired_yaw - state.yaw)
    requested_pitch = cfg["angle_gain_s_inv"] * (desired_pitch - state.pitch)
    max_yaw = math.radians(cfg["max_yaw_rate_deg_s"])
    max_pitch_rate = math.radians(cfg["max_pitch_rate_deg_s"])
    max_pitch = math.radians(cfg["max_pitch_deg"])
    step = cfg["step_s"]
    yaw_rate = float(np.clip(requested_yaw, -max_yaw, max_yaw))
    pitch_rate = float(
        np.clip(
            requested_pitch,
            max(-max_pitch_rate, (-max_pitch - state.pitch) / step),
            min(max_pitch_rate, (max_pitch - state.pitch) / step),
        )
    )
    return requested_yaw, requested_pitch, yaw_rate, pitch_rate


def compare_frozen(actual: dict, expected: dict) -> None:
    """Reject outcome, termination or numerical drift from original tracking."""
    exact = (
        "eligible",
        "execution_success",
        "physical_execution_success",
        "failure_reason",
        "steps",
        "yaw_saturation_steps",
        "pitch_saturation_steps",
        "rate_limit_violations",
        "pitch_limit_violations",
        "speed_limit_violations",
        "required_clearance_satisfied",
    )
    numeric = (
        "simulation_time_s",
        "min_physical_clearance_lower_bound_m",
        "min_mission_clearance_lower_bound_m",
        "max_tracking_error_m",
        "rms_tracking_error_m",
        "final_position_error_m",
        "peak_yaw_rate_deg_s",
        "peak_pitch_rate_deg_s",
        "peak_pitch_deg",
    )
    for key in exact:
        if actual.get(key) != expected.get(key):
            raise ValueError(f"Frozen replay mismatch: {key}")
    for key in numeric:
        if key in expected and not math.isclose(
            actual[key], expected[key], rel_tol=1e-12, abs_tol=1e-9
        ):
            raise ValueError(f"Frozen replay numerical mismatch: {key}")


def replay(
    path: list[Point], scene: Scene, protocol: dict, margin: float, condition: dict
) -> Replay:
    """Replay one controlled input with the 5A safety and termination sequence."""
    started = time.perf_counter()
    cfg = dict(protocol["kinematics"])
    cfg.update(speed_m_s=condition["speed_m_s"], lookahead_m=condition["lookahead_m"])
    if not cfg["min_speed_m_s"] <= cfg["speed_m_s"] <= cfg["max_speed_m_s"]:
        raise ValueError("Controlled speed is outside the frozen permitted range")
    radius = body_radius(protocol)
    mission = Geometry(scene.grid, radius, scene.ceiling)
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
                "failure_reason": reason,
                "primary_class": classify(reason),
                "steps": 0,
            },
            [],
        )
    physical = Geometry(scene.grid, radius)
    required = Geometry(scene.grid, radius + margin, scene.ceiling)
    route = Route(path)
    state = initial_state(path, scene, condition)
    initial = state
    step = cfg["step_s"]
    unconstrained_limit = max(60, 3 * path_length(path) / state.speed + 30)
    limit = min(600, unconstrained_limit)
    progress, error = route.projection(state.position)
    max_error, sum_squared_error, steps = error, 0.0, 0
    minimum_clearance = physical.clearance(state.position, state.position)
    minimum_mission = mission.clearance(state.position, state.position, mission=True)
    clearance_satisfied = required.segment(state.position, state.position).valid
    trace: list[dict] = []
    first: dict[str, dict] = {}
    yaw_saturation = pitch_saturation = yaw_run = pitch_run = 0
    longest_yaw = longest_pitch = 0
    peaks = np.zeros(3)
    reached, reason = False, "simulation_timeout"
    while steps * step < limit:
        if math.dist(state.position, scene.goal) <= cfg["goal_tolerance_m"]:
            reached, reason = True, "goal_reached"
            break
        if time.perf_counter() - started > cfg["wall_guard_s"]:
            reason = "execution_resource_timeout"
            break
        projection, _ = route.projection(state.position)
        progress = max(progress, projection)
        target = route.target(progress + cfg["lookahead_m"])
        requested_yaw, requested_pitch, yaw_rate, pitch_rate = control(
            state, target, cfg
        )
        saturated_yaw = abs(requested_yaw - yaw_rate) > 1e-12
        saturated_pitch = abs(requested_pitch - pitch_rate) > 1e-12
        yaw_saturation += int(saturated_yaw)
        pitch_saturation += int(saturated_pitch)
        yaw_run = yaw_run + 1 if saturated_yaw else 0
        pitch_run = pitch_run + 1 if saturated_pitch else 0
        longest_yaw, longest_pitch = (
            max(longest_yaw, yaw_run),
            max(longest_pitch, pitch_run),
        )
        following = integrate(state, yaw_rate, pitch_rate, step)
        deviation = chord_error_bound(state.speed, yaw_rate, pitch_rate, step)
        physical_verdict = physical.segment(
            state.position, following.position, extra_radius=deviation
        )
        mission_verdict = mission.segment(
            state.position, following.position, extra_radius=deviation
        )
        required_verdict = required.segment(
            state.position, following.position, extra_radius=deviation
        )
        clearance_satisfied &= required_verdict.valid
        clearance = physical.clearance(state.position, following.position) - deviation
        mission_clearance = (
            mission.clearance(state.position, following.position, mission=True)
            - deviation
        )
        minimum_clearance, minimum_mission = (
            min(minimum_clearance, clearance),
            min(minimum_mission, mission_clearance),
        )
        peaks = np.maximum(
            peaks, [abs(yaw_rate), abs(pitch_rate), abs(following.pitch)]
        )
        previous = state
        state = following
        steps += 1
        _, error = route.projection(state.position)
        max_error = max(max_error, error)
        sum_squared_error += error * error
        row = {
            "time_start_s": (steps - 1) * step,
            "time_s": steps * step,
            "start_position": previous.position,
            "position": state.position,
            "yaw_rad": state.yaw,
            "pitch_rad": state.pitch,
            "start_yaw_rad": previous.yaw,
            "start_pitch_rad": previous.pitch,
            "speed_m_s": state.speed,
            "target": target.tolist(),
            "progress_m": progress,
            "requested_yaw_rate_rad_s": requested_yaw,
            "requested_pitch_rate_rad_s": requested_pitch,
            "yaw_rate_rad_s": yaw_rate,
            "pitch_rate_rad_s": pitch_rate,
            "yaw_saturated": saturated_yaw,
            "pitch_saturated": saturated_pitch,
            "cross_track_m": error,
            "chord_error_bound_m": deviation,
            "physical_reason": physical_verdict.reason,
            "mission_reason": mission_verdict.reason,
            "margin_reason": required_verdict.reason,
            "physical_clearance_lower_bound_m": clearance,
            "mission_clearance_lower_bound_m": mission_clearance,
        }
        trace.append(row)
        events = {
            "physical": not physical_verdict.valid,
            "mission": not mission_verdict.valid,
            "margin": not required_verdict.valid,
            "error": error > cfg["max_cross_track_m"],
        }
        for name, occurred in events.items():
            if occurred and name not in first:
                first[name] = row
        if not physical_verdict.valid:
            reason = "physical_sweep_rejected_" + physical_verdict.reason
            break
        if not mission_verdict.valid:
            reason = "mission_band_sweep_rejected"
            break
        if error > cfg["max_cross_track_m"]:
            reason = "tracking_error_limit"
            break
    physical_success = reached
    success = physical_success and clearance_satisfied
    if reached and not clearance_satisfied:
        reason = "goal_reached_required_margin_violated"
    summary = {
        "eligible": True,
        "execution_success": bool(success),
        "physical_execution_success": physical_success,
        "required_clearance_satisfied": bool(clearance_satisfied),
        "reached": reached,
        "failure_reason": reason,
        "primary_class": classify(reason),
        "steps": steps,
        "simulation_time_s": steps * step,
        "simulation_limit_s": limit,
        "simulation_limit_capped": unconstrained_limit > 600,
        "tracking_wall_s": time.perf_counter() - started,
        "initial_yaw_rad": initial.yaw,
        "initial_pitch_rad": initial.pitch,
        "final_position": state.position,
        "final_position_error_m": math.dist(state.position, scene.goal),
        "min_physical_clearance_lower_bound_m": minimum_clearance,
        "min_mission_clearance_lower_bound_m": minimum_mission,
        "max_tracking_error_m": max_error,
        "rms_tracking_error_m": math.sqrt(sum_squared_error / steps) if steps else 0.0,
        "peak_yaw_rate_deg_s": math.degrees(peaks[0]),
        "peak_pitch_rate_deg_s": math.degrees(peaks[1]),
        "peak_pitch_deg": math.degrees(peaks[2]),
        "yaw_saturation_steps": yaw_saturation,
        "pitch_saturation_steps": pitch_saturation,
        "yaw_saturation_s": yaw_saturation * step,
        "pitch_saturation_s": pitch_saturation * step,
        "longest_yaw_saturation_s": longest_yaw * step,
        "longest_pitch_saturation_s": longest_pitch * step,
        "rate_limit_violations": int(
            peaks[0] > math.radians(cfg["max_yaw_rate_deg_s"]) + 1e-12
            or peaks[1] > math.radians(cfg["max_pitch_rate_deg_s"]) + 1e-12
        ),
        "pitch_limit_violations": int(
            peaks[2] > math.radians(cfg["max_pitch_deg"]) + 1e-12
        ),
        "speed_limit_violations": 0,
        "reference_horizontal_turn_radius_m": state.speed
        / math.radians(cfg["max_yaw_rate_deg_s"]),
        "first_failure_time_s": None
        if success
        else (
            first["margin"]["time_s"]
            if reason == "goal_reached_required_margin_violated"
            else steps * step
        ),
    }
    for name in ("physical", "mission", "margin", "error"):
        event = first.get(name)
        summary.update(
            {
                f"first_{name}_time_start_s": event["time_start_s"] if event else None,
                f"first_{name}_time_s": event["time_s"] if event else None,
                f"first_{name}_position": event["position"] if event else None,
            }
        )
    return Replay(summary, trace)
