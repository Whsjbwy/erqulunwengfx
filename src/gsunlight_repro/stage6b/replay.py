"""Independent frozen-Python certification and an explicit LOS reference contract."""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from ..stage5a.geometry import Geometry
from ..stage5a.maps import read_config
from ..stage5a.tracking import State, chord_error_bound, integrate, wrap
from ..stage5af.tracking import simulate
from ..stage5ar.reference import rk4_position
from .scenarios import Scenario, effective_radius, state_values

POSITION_TOLERANCE_M = 1e-10
ANGLE_TOLERANCE_RAD = 1e-12


def _state(values: list[float]) -> State:
    """Reject malformed native states rather than accepting missing components."""
    if len(values) != 6 or not all(math.isfinite(float(value)) for value in values):
        raise ValueError("Native states require six finite components")
    return State(tuple(float(x) for x in values[:3]), *map(float, values[3:]))


def _state_error(first: State, second: State) -> tuple[float, float, float, float]:
    """Compare headings on SO(2), not by their raw wrapped representation."""
    return (
        math.dist(first.position, second.position),
        abs(wrap(first.yaw - second.yaw)),
        abs(first.pitch - second.pitch),
        abs(first.speed - second.speed),
    )


def _matches(error: tuple[float, float, float, float]) -> bool:
    return error[0] <= POSITION_TOLERANCE_M and max(error[1:]) <= ANGLE_TOLERANCE_RAD


def _replay(
    scenario: Scenario, controls: list[dict[str, float]] | tuple[dict[str, float], ...]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[State]]:
    """Rebuild every interval from controls with the frozen independent oracle."""
    started = time.perf_counter()
    cfg = read_config("stage5a_protocol.json")["kinematics"]
    dt = cfg["step_s"]
    geometry = Geometry(scenario.scene.grid, effective_radius(), scenario.scene.ceiling)
    state = scenario.initial
    values = state_values(state)
    reason = "ok"
    if not all(math.isfinite(value) for value in values):
        reason = "invalid_state"
    elif state.speed != cfg["speed_m_s"]:
        reason = "frozen_speed"
    elif abs(state.pitch) > math.radians(cfg["max_pitch_deg"]) + ANGLE_TOLERANCE_RAD:
        reason = "pitch_bound"
    else:
        reason = geometry.segment(state.position, state.position).reason
    trace: list[dict[str, Any]] = []
    endpoints = [state]
    minimum_gap = geometry.clearance(state.position, state.position, mission=True)
    for index, control in enumerate(controls):
        if reason != "ok":
            break
        yaw, pitch, duration = (
            float(control[key])
            for key in ("yaw_rate_rad_s", "pitch_rate_rad_s", "duration_s")
        )
        if not all(math.isfinite(x) for x in (yaw, pitch, duration)):
            reason = "invalid_control"
            break
        count = round(duration / dt)
        if count < 1 or not math.isclose(
            count * dt, duration, rel_tol=0, abs_tol=1e-12
        ):
            raise ValueError(
                "Native control duration must contain positive whole0.1s steps"
            )
        if abs(yaw) > math.radians(cfg["max_yaw_rate_deg_s"]):
            reason = "yaw_rate"
            break
        if abs(pitch) > math.radians(cfg["max_pitch_rate_deg_s"]):
            reason = "pitch_rate"
            break
        for step in range(count):
            following = integrate(state, yaw, pitch, dt)
            bound = chord_error_bound(state.speed, yaw, pitch, dt)
            if (
                abs(following.pitch)
                > math.radians(cfg["max_pitch_deg"]) + ANGLE_TOLERANCE_RAD
            ):
                reason = "pitch_bound"
            else:
                reason = geometry.segment(
                    state.position, following.position, extra_radius=bound
                ).reason
            gap = (
                geometry.clearance(state.position, following.position, mission=True)
                - bound
            )
            minimum_gap = min(minimum_gap, gap)
            trace.append(
                {
                    "time_start_s": len(trace) * dt,
                    "time_s": (len(trace) + 1) * dt,
                    "control_index": index,
                    "control_step": step,
                    "start_position": state.position,
                    "position": following.position,
                    "start_yaw_rad": state.yaw,
                    "start_pitch_rad": state.pitch,
                    "yaw_rad": following.yaw,
                    "pitch_rad": following.pitch,
                    "speed_m_s": state.speed,
                    "yaw_rate_rad_s": yaw,
                    "pitch_rate_rad_s": pitch,
                    "chord_error_bound_m": bound,
                    "accepted": reason == "ok",
                    "reason": reason,
                    "minimum_gap_lower_bound_m": gap,
                }
            )
            if reason != "ok":
                break
            state = following
        if reason == "ok":
            endpoints.append(state)
    chosen = sorted({0, len(trace) // 2, len(trace) - 1}) if trace else []
    maximum_rk4 = 0.0
    for index in chosen:
        row = trace[index]
        reference = rk4_position(
            State(
                row["start_position"],
                row["start_yaw_rad"],
                row["start_pitch_rad"],
                row["speed_m_s"],
            ),
            row["yaw_rate_rad_s"],
            row["pitch_rate_rad_s"],
            dt,
            steps=50,
        )
        maximum_rk4 = max(maximum_rk4, math.dist(reference, row["position"]))
    summary = {
        "reason": reason,
        "accepted_intervals": sum(row["accepted"] for row in trace),
        "integrated_intervals": len(trace),
        "last_accepted_state": state_values(state),
        "last_candidate_state": (
            [
                *trace[-1]["position"],
                trace[-1]["yaw_rad"],
                trace[-1]["pitch_rad"],
                state.speed,
            ]
            if trace
            else None
        ),
        "goal_reached": math.dist(state.position, scenario.scene.goal)
        <= cfg["goal_tolerance_m"],
        "final_goal_distance_m": math.dist(state.position, scenario.scene.goal),
        "minimum_gap_lower_bound_m": minimum_gap,
        "independent_rk4_intervals": len(chosen),
        "maximum_rk4_error_m": maximum_rk4,
        "independent_replay_wall_s": time.perf_counter() - started,
        "first_rejected_position": trace[-1]["position"]
        if reason != "ok" and trace
        else None,
    }
    return summary, trace, endpoints


def audit_supplied_controls(
    scenario: Scenario, native_payload: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Check the native13-case interface against independently supplied controls."""
    summary, trace, _ = _replay(scenario, scenario.witness_controls)
    native_trace = native_payload["trace"]
    maximum_position = maximum_angle = 0.0
    consistent = len(native_trace) == len(trace)
    for expected, native in zip(trace, native_trace, strict=False):
        expected_start = State(
            expected["start_position"],
            expected["start_yaw_rad"],
            expected["start_pitch_rad"],
            expected["speed_m_s"],
        )
        expected_end = State(
            expected["position"],
            expected["yaw_rad"],
            expected["pitch_rad"],
            expected["speed_m_s"],
        )
        for known, values in (
            (expected_start, native["start"]),
            (expected_end, native["following"]),
        ):
            error = _state_error(known, _state(values))
            maximum_position = max(maximum_position, error[0])
            maximum_angle = max(maximum_angle, *error[1:])
            consistent &= _matches(error)
        consistent &= native["reason"] == expected["reason"]
        consistent &= native["accepted"] is expected["accepted"]
        consistent &= math.isclose(
            float(native["chord_error_bound_m"]),
            expected["chord_error_bound_m"],
            rel_tol=0,
            abs_tol=1e-15,
        )
    expected_states = [scenario.initial] + [
        State(row["position"], row["yaw_rad"], row["pitch_rad"], row["speed_m_s"])
        for row in trace
        if row["accepted"]
    ]
    native_states = native_payload["states"]
    consistent &= len(expected_states) == len(native_states)
    for known, values in zip(expected_states, native_states, strict=False):
        error = _state_error(known, _state(values))
        maximum_position = max(maximum_position, error[0])
        maximum_angle = max(maximum_angle, *error[1:])
        consistent &= _matches(error)
    consistent &= _matches(
        _state_error(
            _state(summary["last_accepted_state"]),
            _state(native_payload["last_accepted_state"]),
        )
    )
    if summary["last_candidate_state"] is None:
        consistent &= native_payload["last_candidate_state"] is None
    elif native_payload["last_candidate_state"] is None:
        consistent = False
    else:
        consistent &= _matches(
            _state_error(
                _state(summary["last_candidate_state"]),
                _state(native_payload["last_candidate_state"]),
            )
        )
    consistent &= (
        native_payload["reason"] == summary["reason"] == scenario.expected_reason
    )
    consistent &= (
        int(native_payload["accepted_intervals"]) == summary["accepted_intervals"]
    )
    consistent &= summary["maximum_rk4_error_m"] <= POSITION_TOLERANCE_M
    summary.update(
        scenario_id=scenario.id,
        expected_reason=scenario.expected_reason,
        native_reason=native_payload["reason"],
        maximum_native_position_error_m=maximum_position,
        maximum_native_angle_or_speed_error=maximum_angle,
        independent_audit_passed=bool(consistent),
        model_feasible=False,
        purpose="supplied-control interface acceptance, not planner performance",
    )
    return summary, trace


def audit_controls(
    scenario: Scenario, native_payload: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reconstruct official controls; distinguish exact and approximate solutions."""
    status = native_payload["status"]
    if status not in ("exact", "approximate", "no_solution"):
        raise ValueError(f"Unrecognized native solution status: {status}")
    controls, nodes = native_payload["controls"], native_payload["states"]
    if status == "no_solution":
        if controls or nodes:
            raise ValueError("No-solution payload unexpectedly contains a trajectory")
        return {
            "scenario_id": scenario.id,
            "independent_audit_passed": True,
            "model_feasible": False,
            "reason": "no_solution",
            "native_status": status,
            "accepted_intervals": 0,
            "independent_replay_wall_s": 0.0,
        }, []
    if len(nodes) != len(controls) + 1:
        raise ValueError("PathControl must have one more state than controls")
    summary, trace, endpoints = _replay(scenario, controls)
    initial_error = _state_error(scenario.initial, _state(nodes[0]))
    errors = [initial_error]
    if summary["reason"] == "ok":
        errors.extend(
            _state_error(known, _state(values))
            for known, values in zip(endpoints[1:], nodes[1:], strict=True)
        )
    nodes_match = all(_matches(error) for error in errors)
    passed = (
        summary["reason"] == "ok"
        and nodes_match
        and summary["maximum_rk4_error_m"] <= POSITION_TOLERANCE_M
    )
    reason = summary["reason"]
    if reason == "ok" and not nodes_match:
        reason = "native_state_mismatch"
    if reason == "ok" and summary["maximum_rk4_error_m"] > POSITION_TOLERANCE_M:
        reason = "independent_rk4_mismatch"
    if passed and status == "exact" and not summary["goal_reached"]:
        passed, reason = False, "exact_status_goal_mismatch"
    summary.update(
        scenario_id=scenario.id,
        native_status=status,
        independent_audit_passed=bool(passed),
        model_feasible=bool(passed and status == "exact" and summary["goal_reached"]),
        maximum_native_node_position_error_m=max(error[0] for error in errors),
        maximum_native_node_angle_or_speed_error=max(
            max(error[1:]) for error in errors
        ),
        reason="approximate_not_strict"
        if passed and status == "approximate"
        else reason,
    )
    return summary, trace


def track_reference(
    scenario: Scenario,
    audit_summary: dict[str, Any],
    audit_trace: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Certify the declared reference bridge and use the unchanged terminalLOS."""
    started = time.perf_counter()
    rejected = {
        "scenario_id": scenario.id,
        "was_run": False,
        "eligible": False,
        "execution_success": False,
        "reference_bridge_is_native_control": False,
    }
    if not audit_summary["model_feasible"]:
        return {**rejected, "failure_reason": "not_run_no_strict_native_trajectory"}, []
    if any(not row["accepted"] for row in audit_trace):
        raise ValueError("A rejected interval cannot be given to the frozen tracker")
    reference = [scenario.initial.position] + [
        tuple(row["position"]) for row in audit_trace
    ]
    if math.dist(reference[0], scenario.scene.start) > POSITION_TOLERANCE_M:
        raise ValueError("Reference order must preserve the original start state")
    radius = effective_radius()
    geometry = Geometry(scenario.scene.grid, radius, scenario.scene.ceiling)
    bridge_length = math.dist(reference[-1], scenario.scene.goal)
    if (
        bridge_length
        > read_config("stage5a_protocol.json")["kinematics"]["goal_tolerance_m"]
    ):
        return {**rejected, "failure_reason": "interface_rejected_goal_ball"}, []
    bridge = geometry.segment(reference[-1], scenario.scene.goal)
    if not bridge.valid:
        return {
            **rejected,
            "failure_reason": "interface_rejected_reference_bridge_" + bridge.reason,
            "reference_bridge_length_m": bridge_length,
            "reference_adaptation_wall_s": time.perf_counter() - started,
        }, []
    if reference[-1] != scenario.scene.goal:
        reference.append(scenario.scene.goal)
    if len(reference) == 1:
        reference.append(reference[0])
    verdict = geometry.path(reference)
    if not verdict.valid:
        return {
            **rejected,
            "failure_reason": "interface_rejected_reference_chord_" + verdict.reason,
            "reference_bridge_length_m": bridge_length,
            "reference_adaptation_wall_s": time.perf_counter() - started,
        }, []
    adaptation_s = time.perf_counter() - started
    replay = simulate(
        reference,
        scenario.scene,
        read_config("stage5a_protocol.json"),
        0.25,
        read_config("stage5af_protocol.json"),
        corrected=True,
        initial=scenario.initial,
    )
    progress = [0.0] + [row["reference_progress_m"] for row in replay.trace]
    increments = np.diff(progress)
    summary = {
        **replay.summary,
        "scenario_id": scenario.id,
        "was_run": True,
        "reference_samples_before_bridge": 1 + len(audit_trace),
        "reference_bridge_length_m": bridge_length,
        "reference_bridge_is_native_control": False,
        "reference_bridge_certified": True,
        "reference_chords_certified": True,
        "reference_adaptation_wall_s": adaptation_s,
        "tracking_and_adaptation_wall_s": time.perf_counter() - started,
        "initial_state": state_values(scenario.initial),
        "maximum_reference_progress_step_m": float(max(increments, default=0.0)),
        "reference_progress_jump_markers_gt1m": int(sum(increments > 1.0)),
    }
    for kind in ("physical", "mission", "margin"):
        first = next(
            (row for row in replay.trace if row[kind + "_reason"] != "ok"), None
        )
        summary[f"first_{kind}_rejection_time_s"] = first["time_s"] if first else None
        summary[f"first_{kind}_rejection_position"] = (
            first["position"] if first else None
        )
    return summary, replay.trace
