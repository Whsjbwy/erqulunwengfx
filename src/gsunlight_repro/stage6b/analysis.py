"""Audit saved native/LOS evidence without starting searches or simulations."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from ..stage5a.analysis import write_csv
from ..stage5a.geometry import Geometry
from ..stage5a.maps import ROOT, body_radius, read_config
from ..stage5a.tracking import Route, State, chord_error_bound, integrate, wrap
from ..stage5ae.guidance import frame
from ..stage5ar.reference import rk4_position
from ..stage5ar.replay import classify, control
from .replay import audit_controls
from .scenarios import (
    Scenario,
    analytic_scenarios,
    effective_radius,
    historical_scenario,
    state_values,
)

Record = dict[str, Any]
REQUIRED_FILES = frozenset(
    {
        "input.json",
        "output.json",
        "condition_summary.json",
        "independent_record.json.gz",
        "stdout.log",
        "stderr.log",
    }
)


def require(condition: bool, message: str) -> None:
    """Fail explicitly on missing, conflicting or changed evidence."""
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> Any:
    """Read existing UTF-8 evidence; missing records are never imputed."""
    return json.loads(path.read_text(encoding="utf-8"))


def compare(actual: Any, expected: Any, label: str) -> None:
    """Compare complete nested records with tight numerical tolerances."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict), f"{label}: expected object")
        require(actual.keys() == expected.keys(), f"{label}: different keys")
        for key, value in expected.items():
            compare(actual[key], value, f"{label}.{key}")
    elif isinstance(expected, (tuple, list)):
        require(isinstance(actual, (tuple, list)), f"{label}: expected sequence")
        require(len(actual) == len(expected), f"{label}: different cardinality")
        for index, (first, second) in enumerate(zip(actual, expected, strict=True)):
            compare(first, second, f"{label}[{index}]")
    elif isinstance(expected, bool) or expected is None or isinstance(expected, str):
        require(actual == expected, f"{label}: {actual!r} != {expected!r}")
    elif isinstance(expected, (int, float)):
        require(
            isinstance(actual, (int, float))
            and math.isfinite(actual)
            and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-10),
            f"{label}: numerical mismatch {actual!r} != {expected!r}",
        )
    else:
        raise TypeError(f"{label}: unsupported evidence value {type(expected)}")


def check_fields(actual: Record, expected: Record, label: str) -> None:
    """Check a declared subset without ignoring missing evidence fields."""
    require(expected.keys() <= actual.keys(), f"{label}: missing expected fields")
    for key, value in expected.items():
        compare(actual[key], value, f"{label}.{key}")


def check_grid(record: Record, grid: Any, key: str, local: Path) -> None:
    """Compare cached numeric maps directly, without generating files or hashes."""
    expected = {
        "shape": list(grid.shape),
        "origin": list(grid.origin),
        "spacing": list(grid.spacing),
        "data_file": str((local / "grids" / f"{key}.u8").resolve()),
    }
    compare(record, expected, f"grid.{key}")
    require(
        Path(record["data_file"]).read_bytes()
        == grid.occupancy.astype(np.uint8).tobytes(order="C"),
        f"Grid data differs from frozen scenario: {key}",
    )


def check_request(
    request: Record, task: Record, scenario: Scenario, protocol: Record, local: Path
) -> None:
    """Validate a full whitelisted planner request and the positive seed mapping."""
    cfg = protocol["planning"]
    exported = request["scenario"]
    require(
        exported.keys() == {"id", "physical", "ceiling", "initial", "goal", "radius_m"},
        f"{task['job_id']}: unexpected scenario keys or hidden witness",
    )
    check_fields(
        exported,
        {
            "id": scenario.id,
            "initial": state_values(scenario.initial),
            "goal": list(scenario.scene.goal),
            "radius_m": effective_radius(),
        },
        task["job_id"] + ".scenario",
    )
    require(
        exported["initial"] == state_values(scenario.initial)
        and exported["goal"] == list(scenario.scene.goal)
        and exported["radius_m"] == effective_radius(),
        f"{task['job_id']}: registered state, goal or radius changed",
    )
    check_grid(exported["physical"], scenario.scene.grid, scenario.physical_key, local)
    if scenario.scene.ceiling is None:
        require(exported["ceiling"] is None, "Unexpected mission ceiling")
    else:
        require(scenario.ceiling_key is not None, "Missing semantic ceiling key")
        check_grid(
            exported["ceiling"], scenario.scene.ceiling, scenario.ceiling_key, local
        )
    expected = {
        "mode": "plan",
        "algorithm": task["algorithm"],
        "seed": cfg["ompl_seed_by_label"][str(task["seed_label"])],
        "search_budget_s": cfg["search_cap_s"],
        "total_budget_s": cfg["wall_budget_s"],
        "scenario": exported,
        **{
            key: cfg[key]
            for key in (
                "propagation_min_steps",
                "propagation_max_steps",
                "goal_bias",
                "selection_radius",
                "pruning_radius",
            )
        },
    }
    compare(request, expected, task["job_id"] + ".request")
    require(
        cfg["seed_labels"] == [0, 1] and cfg["ompl_seed_by_label"] == {"0": 1, "1": 2},
        "Registered labels must map prospectively to distinct native seeds 1/2",
    )


def check_csv_row(record: Record, saved: dict[str, str]) -> None:
    """Verify every public CSV cell against the single saved condition summary."""
    require(saved.keys() == record.keys(), "CSV/condition summary columns differ")
    for key, value in record.items():
        encoded = (
            json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list, tuple))
            else ""
            if value is None
            else str(value)
        )
        require(saved[key] == encoded, f"{record['job_id']}: CSV mismatch: {key}")


def check_native(
    scenario: Scenario, native: Record, saved: Record, row: Record, protocol: Record
) -> tuple[Record, list[Record]]:
    """Recompute complete native controls, nodes and continuous safety evidence."""
    require(native["status"] in {"exact", "approximate", "no_solution"}, "Bad status")
    check_fields(
        native,
        {
            "mode": "plan",
            "algorithm": row["algorithm"],
            "seed": row["ompl_seed"],
            "ompl_version": protocol["official_ompl_version"],
            "status": row["native_status"],
            "raw_status": row["raw_status"],
        },
        row["job_id"] + ".native",
    )
    if native["status"] != "no_solution":
        require(
            len(native["states"]) == len(native["controls"]) + 1,
            "PathControl must have one more state than control segments",
        )
    dt = protocol["planning"]["propagation_step_s"]
    for item in native["controls"]:
        require(
            item.keys() == {"yaw_rate_rad_s", "pitch_rate_rad_s", "duration_s"},
            "Unexpected native control schema",
        )
        duration = item["duration_s"]
        count = round(duration / dt)
        require(
            math.isfinite(duration)
            and count >= 1
            and math.isclose(duration, count * dt, rel_tol=0, abs_tol=1e-12),
            "Control duration is not a positive integer multiple of 0.1s",
        )
    audit, trace = audit_controls(scenario, native)
    require(audit["independent_audit_passed"], "Recomputed native audit failed")
    expected = dict(saved["audit"])
    actual = dict(audit)
    expected.pop("independent_replay_wall_s")
    actual.pop("independent_replay_wall_s")
    before_deadline = audit["model_feasible"]
    deadline_ok = (
        row["independent_certificate_finish_s"] <= protocol["planning"]["wall_budget_s"]
    )
    actual["model_feasible"] = before_deadline and deadline_ok
    compare(actual, expected, row["job_id"] + ".saved_audit")
    compare(trace, saved["native_replay_trace"], row["job_id"] + ".native_trace")
    if native["status"] != "no_solution":
        certificate = native["native_certificate"]
        check_fields(
            certificate,
            {
                "valid": True,
                "reason": "ok",
                "checked_intervals": audit["accepted_intervals"],
                "goal_reached": audit["goal_reached"],
                "final_goal_distance_m": audit["final_goal_distance_m"],
                "maximum_node_position_error_m": audit[
                    "maximum_native_node_position_error_m"
                ],
                "maximum_node_angle_error_rad": audit[
                    "maximum_native_node_angle_or_speed_error"
                ],
                "zero_control_path": not native["controls"],
            },
            row["job_id"] + ".native_certificate",
        )
    check_fields(
        row,
        {
            "model_feasible_before_deadline": before_deadline,
            "model_feasible": actual["model_feasible"],
            "planning_deadline_rejected": not deadline_ok,
            "independent_audit_passed": True,
            "control_segments": len(native["controls"]),
            "accepted_trajectory_intervals": audit["accepted_intervals"],
            "native_failure_reason": audit["reason"]
            if deadline_ok
            else "deadline_rejected",
            "candidate_return_s": native["candidate_return_s"],
            **{
                key: native[key]
                for key in (
                    "propagated_intervals",
                    "state_validity_calls",
                    "planning_counters",
                    "rejection_counts",
                )
            },
            **{
                key: audit.get(key)
                for key in (
                    "final_goal_distance_m",
                    "maximum_native_node_position_error_m",
                    "maximum_rk4_error_m",
                    "minimum_gap_lower_bound_m",
                )
            },
        },
        row["job_id"] + ".condition",
    )
    require(row["return_code"] == 0, "Native process did not exit successfully")
    require(
        row["independent_certificate_finish_s"] >= row["bridge_total_wall_s"],
        "Independent certificate clock omits part of the native bridge",
    )
    require(
        not native["native_deadline_rejected"] or not row["model_feasible"],
        "A native deadline rejection was counted as model feasible",
    )
    require(
        not row["model_feasible"]
        or native["candidate_return_s"]
        <= native["native_certificate_finish_s"]
        <= protocol["planning"]["wall_budget_s"],
        "A model success lacks a native certificate inside the common budget",
    )
    require(
        native["raw_status"]
        == {"exact": "Exact solution", "approximate": "Approximate solution"}.get(
            native["status"], native["raw_status"]
        ),
        "Native exact/approximate status changed",
    )
    if native["status"] != "exact":
        require(
            not row["model_feasible"] and not row["was_run"], "Approximate upgraded"
        )
    return audit, trace


def observed_guidance(
    state: State, route: Route, progress: float, terminal: bool, settings: Record
) -> tuple[np.ndarray, Record, float, bool]:
    """Check guidance formulas on an observed state, without simulating a run."""
    index = min(
        len(route.edges) - 1,
        int(np.searchsorted(route.cumulative, progress, side="right") - 1),
    )
    tangent = route.edges[index]
    if np.linalg.norm(tangent) < 1e-12:
        tangent = np.array([1.0, 0.0, 0.0])
    rotation = frame(tangent)
    reference = route.target(progress)
    along, lateral, vertical = rotation.T @ (np.asarray(state.position) - reference)
    azimuth = -math.atan2(lateral, settings["lookahead_m"])
    elevation = -math.atan2(vertical, settings["lookahead_m"])
    relative = np.array(
        [
            math.cos(azimuth) * math.cos(elevation),
            math.sin(azimuth) * math.cos(elevation),
            math.sin(elevation),
        ]
    )
    base_target = np.asarray(state.position) + rotation @ relative
    rate = state.speed * relative[0] + along
    nonzero = np.flatnonzero(route.lengths > 1e-12)
    last_start = route.cumulative[nonzero[-1]] if len(nonzero) else 0.0
    threshold = max(last_start, route.cumulative[-1] - settings["terminal_distance_m"])
    switched = bool(not terminal and progress >= threshold)
    terminal |= switched
    jump = 0.0
    if switched:
        before, after = base_target - state.position, route.points[-1] - state.position
        denominator = np.linalg.norm(before) * np.linalg.norm(after)
        if denominator > 0:
            jump = math.degrees(
                math.acos(float(np.clip(before @ after / denominator, -1, 1)))
            )
    target = route.points[-1] if terminal else base_target
    details = {
        "target": target.tolist(),
        "progress_m": progress,
        "reference_progress_m": progress,
        "active_segment": index,
        "along_error_m": float(along),
        "lateral_error_m": float(lateral),
        "vertical_error_m": float(vertical),
        "progress_rate_m_s": float(rate),
        "reference_position": reference.tolist(),
        "terminal_mode": terminal,
        "terminal_switch": switched,
        "switch_direction_jump_deg": jump,
    }
    return target, details, float(rate), terminal


def audit_los(
    scenario: Scenario, native_trace: list[Record], saved: Record, row: Record
) -> tuple[Record, Record | None]:
    """Verify every saved LOS step, input, certificate and stopping decision."""
    tracking, trace = saved["tracking"], saved["los_trace"]
    require(tracking["was_run"] == row["was_run"], "LOS execution marker differs")
    require(tracking["eligible"] == row["eligible"], "LOS eligibility marker differs")
    if not tracking["was_run"]:
        require(
            not trace and not row["model_feasible"], "Unexpected unexecuted LOS trace"
        )
        return {"was_run": False, "saved_trace_intervals": 0, "passed": True}, None
    require(row["model_feasible"] and tracking["eligible"], "Ineligible actual LOS")
    vehicle, settings = (
        read_config("stage5a_protocol.json"),
        read_config("stage5af_protocol.json"),
    )
    cfg, dt = vehicle["kinematics"], vehicle["kinematics"]["step_s"]
    path = [scenario.initial.position] + [
        tuple(item["position"]) for item in native_trace
    ]
    bridge = math.dist(path[-1], scenario.scene.goal)
    require(bridge <= cfg["goal_tolerance_m"], "Reference bridge exceeds goal ball")
    geometry = Geometry(scenario.scene.grid, effective_radius(), scenario.scene.ceiling)
    require(geometry.segment(path[-1], scenario.scene.goal).valid, "Unsafe bridge")
    if path[-1] != scenario.scene.goal:
        path.append(scenario.scene.goal)
    if len(path) == 1:
        path.append(path[0])
    require(geometry.path(path).valid, "Unsafe reference chords")
    route = Route(path)
    physical = Geometry(scenario.scene.grid, body_radius(vehicle))
    mission = Geometry(
        scenario.scene.grid, body_radius(vehicle), scenario.scene.ceiling
    )
    required = Geometry(
        scenario.scene.grid, body_radius(vehicle) + 0.25, scenario.scene.ceiling
    )
    state = scenario.initial
    clearance_ok = required.segment(state.position, state.position).valid
    minimum = physical.clearance(state.position, state.position)
    mission_minimum = mission.clearance(state.position, state.position, mission=True)
    progress, terminal, maximum_position, maximum_angle, maximum_rk4 = (
        0.0,
        False,
        0.0,
        0.0,
        0.0,
    )
    switches: list[int] = []
    first_failure: Record | None = None
    first_kind: dict[str, Record] = {}
    stop_reason: str | None = None
    chosen = {0, len(trace) // 2, len(trace) - 1} if trace else set()
    for index, item in enumerate(trace):
        require(
            stop_reason is None, "LOS trace continues past its first stop criterion"
        )
        require(
            math.dist(state.position, scenario.scene.goal) > cfg["goal_tolerance_m"],
            "LOS trace continues after the frozen pre-step goal test",
        )
        check_fields(
            item,
            {
                "time_start_s": index * dt,
                "time_s": (index + 1) * dt,
                "start_position": state.position,
                "start_yaw_rad": state.yaw,
                "start_pitch_rad": state.pitch,
                "speed_m_s": state.speed,
            },
            "LOS.start",
        )
        require(
            abs(wrap(item["start_yaw_rad"] - state.yaw)) <= 1e-12
            and abs(item["start_pitch_rad"] - state.pitch) <= 1e-12
            and abs(item["speed_m_s"] - state.speed) <= 1e-12,
            "LOS initial/adjacent angular or speed state drift",
        )
        target, details, rate, terminal = observed_guidance(
            state, route, progress, terminal, settings
        )
        check_fields(item, details, "LOS.guidance")
        progress = float(np.clip(progress + dt * rate, 0, route.cumulative[-1]))
        requested_yaw, requested_pitch, yaw, pitch = control(state, target, cfg)
        check_fields(
            item,
            {
                "requested_yaw_rate_rad_s": requested_yaw,
                "requested_pitch_rate_rad_s": requested_pitch,
                "yaw_rate_rad_s": yaw,
                "pitch_rate_rad_s": pitch,
                "yaw_saturated": abs(requested_yaw - yaw) > 1e-12,
                "pitch_saturated": abs(requested_pitch - pitch) > 1e-12,
            },
            "LOS.control",
        )
        require(abs(yaw) <= math.radians(cfg["max_yaw_rate_deg_s"]), "Yaw rate bound")
        require(
            abs(pitch) <= math.radians(cfg["max_pitch_rate_deg_s"]) + 1e-12,
            "Pitch rate bound",
        )
        following = integrate(state, yaw, pitch, dt)
        maximum_position = max(
            maximum_position, math.dist(following.position, item["position"])
        )
        maximum_angle = max(
            maximum_angle,
            abs(wrap(following.yaw - item["yaw_rad"])),
            abs(following.pitch - item["pitch_rad"]),
        )
        require(maximum_position <= 1e-10 and maximum_angle <= 1e-12, "LOS state drift")
        require(
            abs(following.pitch) <= math.radians(cfg["max_pitch_deg"]) + 1e-12,
            "LOS pitch bound",
        )
        bound = chord_error_bound(state.speed, yaw, pitch, dt)
        verdicts = {
            kind: oracle.segment(state.position, following.position, extra_radius=bound)
            for kind, oracle in (
                ("physical", physical),
                ("mission", mission),
                ("margin", required),
            )
        }
        clearance_ok &= verdicts["margin"].valid
        gap = physical.clearance(state.position, following.position) - bound
        mission_gap = (
            mission.clearance(state.position, following.position, mission=True) - bound
        )
        minimum, mission_minimum = min(minimum, gap), min(mission_minimum, mission_gap)
        _, error = route.projection(following.position)
        to_goal, direction = (
            np.asarray(scenario.scene.goal) - state.position,
            target - state.position,
        )
        denominator = np.linalg.norm(to_goal) * np.linalg.norm(direction)
        cosine = float(direction @ to_goal / denominator) if denominator else None
        check_fields(
            item,
            {
                **{
                    kind + "_reason": verdict.reason
                    for kind, verdict in verdicts.items()
                },
                "chord_error_bound_m": bound,
                "physical_clearance_lower_bound_m": gap,
                "mission_clearance_lower_bound_m": mission_gap,
                "cross_track_m": error,
                "goal_direction_cosine": cosine,
                "goal_distance_before_m": math.dist(
                    state.position, scenario.scene.goal
                ),
                "goal_distance_after_m": math.dist(
                    following.position, scenario.scene.goal
                ),
            },
            "LOS.certificate",
        )
        if index in chosen:
            reference = rk4_position(state, yaw, pitch, dt, steps=50)
            maximum_rk4 = max(maximum_rk4, math.dist(reference, following.position))
        if item["terminal_switch"]:
            switches.append(index)
        if terminal and cosine is not None:
            require(cosine >= 1 - 1e-12, "Terminal direction differs from actual goal")
        for kind, verdict in verdicts.items():
            if not verdict.valid and kind not in first_kind:
                first_kind[kind] = item
        failures = [
            (
                "physical_sweep_rejected_" + verdicts["physical"].reason,
                not verdicts["physical"].valid,
            ),
            ("mission_band_sweep_rejected", not verdicts["mission"].valid),
            ("required_margin_violated", not verdicts["margin"].valid),
            ("tracking_error_limit", error > cfg["max_cross_track_m"]),
        ]
        if first_failure is None:
            failure = next((name for name, failed in failures if failed), None)
            if failure is not None:
                first_failure = {"reason": failure, "index": index, **item}
        if not verdicts["physical"].valid:
            stop_reason = "physical_sweep_rejected_" + verdicts["physical"].reason
        elif not verdicts["mission"].valid:
            stop_reason = "mission_band_sweep_rejected"
        elif error > cfg["max_cross_track_m"]:
            stop_reason = "tracking_error_limit"
        state = following
    require(len(switches) <= 1, "Terminal latch switched more than once")
    require(maximum_rk4 <= 1e-10, "LOS independent RK4 mismatch")
    limit = min(600, max(60, 3 * float(sum(route.lengths)) / state.speed + 30))
    reached = bool(
        stop_reason is None
        and len(trace) * dt < limit
        and math.dist(state.position, scenario.scene.goal) <= cfg["goal_tolerance_m"]
    )
    if stop_reason is None:
        if reached:
            stop_reason = (
                "goal_reached"
                if clearance_ok
                else "goal_reached_required_margin_violated"
            )
        elif len(trace) * dt >= limit:
            stop_reason = "simulation_timeout"
        else:
            require(
                tracking["failure_reason"] == "execution_resource_timeout",
                "LOS trace ends without any recorded stop criterion",
            )
            stop_reason = "execution_resource_timeout"
    terminal_rows = [item for item in trace if item["terminal_mode"]]
    errors = [item["cross_track_m"] for item in trace]
    expected = {
        "eligible": True,
        "execution_success": reached and clearance_ok,
        "physical_execution_success": reached,
        "reached": reached,
        "required_clearance_satisfied": clearance_ok,
        "failure_reason": stop_reason,
        "primary_class": classify(stop_reason),
        "steps": len(trace),
        "simulation_time_s": len(trace) * dt,
        "simulation_limit_s": limit,
        "max_tracking_error_m": max(errors, default=0.0),
        "rms_tracking_error_m": math.sqrt(sum(x * x for x in errors) / len(errors))
        if errors
        else 0.0,
        "final_position": state.position,
        "final_position_error_m": math.dist(state.position, scenario.scene.goal),
        "min_physical_clearance_lower_bound_m": minimum,
        "min_mission_clearance_lower_bound_m": mission_minimum,
        "rate_limit_violations": 0,
        "pitch_limit_violations": 0,
        "speed_limit_violations": 0,
        "terminal_switches": len(switches),
        "terminal_switch_index": switches[0] if switches else None,
        "terminal_switch_time_s": switches[0] * dt if switches else None,
        "maximum_switch_jump_deg": max(
            (item["switch_direction_jump_deg"] for item in trace), default=0.0
        ),
        "terminal_distance_increase_steps": sum(
            item["goal_distance_after_m"] > item["goal_distance_before_m"]
            for item in terminal_rows
        ),
        "minimum_terminal_goal_cosine": min(
            (
                item["goal_direction_cosine"]
                for item in terminal_rows
                if item["goal_direction_cosine"] is not None
            ),
            default=None,
        ),
        "last_reference_progress_m": trace[-1]["progress_m"] if trace else 0.0,
        "reference_samples_before_bridge": 1 + len(native_trace),
        "reference_bridge_length_m": bridge,
        "reference_bridge_is_native_control": False,
        "reference_bridge_certified": True,
        "reference_chords_certified": True,
        "initial_state": state_values(scenario.initial),
    }
    increments = np.diff([0.0] + [item["reference_progress_m"] for item in trace])
    expected["maximum_reference_progress_step_m"] = float(max(increments, default=0.0))
    expected["reference_progress_jump_markers_gt1m"] = int(sum(increments > 1.0))
    for kind in ("physical", "mission", "margin"):
        first = first_kind.get(kind)
        expected[f"first_{kind}_rejection_time_s"] = first["time_s"] if first else None
        expected[f"first_{kind}_rejection_position"] = (
            first["position"] if first else None
        )
    for axis in ("yaw", "pitch"):
        expected[axis + "_saturation_steps"] = sum(
            item[axis + "_saturated"] for item in trace
        )
        expected["peak_" + axis + "_rate_deg_s"] = math.degrees(
            max((abs(item[axis + "_rate_rad_s"]) for item in trace), default=0.0)
        )
    expected["peak_pitch_deg"] = math.degrees(
        max((abs(item["pitch_rad"]) for item in trace), default=0.0)
    )
    check_fields(tracking, expected, row["job_id"] + ".LOS_summary")
    protocol = read_config("stage6b_protocol.json")["reference_contract"]
    wall = tracking["tracking_and_adaptation_wall_s"]
    deadline = (
        wall <= protocol["wall_cap_s"]
        and wall + row["independent_certificate_finish_s"]
        <= protocol["total_pipeline_wall_cap_s"]
    )
    check_fields(
        row,
        {
            "los_success_before_deadline": expected["execution_success"],
            "los_strict_success": expected["execution_success"] and deadline,
            "los_failure_reason": stop_reason
            if deadline
            else "execution_deadline_rejected",
            "tracking_and_adaptation_wall_s": wall,
            "reference_bridge_length_m": bridge,
            "reference_progress_jump_markers_gt1m": expected[
                "reference_progress_jump_markers_gt1m"
            ],
            "maximum_tracking_error_m": expected["max_tracking_error_m"],
            **{
                key: expected[key]
                for key in (
                    "first_physical_rejection_time_s",
                    "first_physical_rejection_position",
                    "first_mission_rejection_position",
                    "first_margin_rejection_position",
                )
            },
        },
        row["job_id"] + ".LOS_condition",
    )
    report = {
        "was_run": True,
        "saved_trace_intervals": len(trace),
        "passed": True,
        "maximum_position_error_m": maximum_position,
        "maximum_angle_error_rad": maximum_angle,
        "independent_rk4_intervals": len(chosen),
        "maximum_rk4_error_m": maximum_rk4,
        "failure_reason_recomputed": stop_reason,
        "goal_reached_recomputed": reached,
        "success_recomputed": expected["execution_success"] and deadline,
    }
    diagnostic = None
    if not row["los_strict_success"]:
        switch = trace[switches[0]] if switches else None
        last_start = float(route.cumulative[-2])
        diagnostic = {
            "job_id": row["job_id"],
            "scenario": scenario.id,
            "algorithm": row["algorithm"],
            "seed_label": row["seed_label"],
            "reachability": row["reachability"],
            "los_failure_reason": row["los_failure_reason"],
            "first_observed_failure_reason": first_failure["reason"]
            if first_failure
            else stop_reason,
            "first_observed_failure_time_s": first_failure["time_s"]
            if first_failure
            else len(trace) * dt,
            "first_observed_failure_interval_start_s": first_failure["time_start_s"]
            if first_failure
            else None,
            "first_observed_failure_interval_end_s": first_failure["time_s"]
            if first_failure
            else None,
            "first_observed_failure_interval_start_position": first_failure[
                "start_position"
            ]
            if first_failure
            else None,
            "first_observed_failure_position": first_failure["position"]
            if first_failure
            else state.position,
            "terminal_active_at_first_failure": first_failure["terminal_mode"]
            if first_failure
            else terminal,
            "terminal_switch_time_s": switch["time_start_s"] if switch else None,
            "terminal_switch_goal_distance_m": switch["goal_distance_before_m"]
            if switch
            else None,
            "terminal_switch_reference_progress_m": switch["reference_progress_m"]
            if switch
            else None,
            "terminal_switch_threshold_m": max(
                last_start,
                float(route.cumulative[-1]) - settings["terminal_distance_m"],
            ),
            "reference_length_m": float(route.cumulative[-1]),
            "last_reference_edge_length_m": float(route.lengths[-1]),
            "reference_bridge_length_m": bridge,
            "last_native_reference_chord_length_m": math.dist(path[-3], path[-2])
            if bridge > 0 and len(path) >= 3
            else None,
            "minimum_observed_goal_distance_m": min(
                [math.dist(scenario.initial.position, scenario.scene.goal)]
                + [item["goal_distance_after_m"] for item in trace]
            ),
            "final_goal_distance_m": expected["final_position_error_m"],
            "max_tracking_error_m": expected["max_tracking_error_m"],
            "terminal_distance_increase_steps": expected[
                "terminal_distance_increase_steps"
            ],
            "interpretation": (
                "observational co-occurrence only; "
                "interval-end candidate is not an exact collision instant; "
                "no causal attribution or controller retuning"
            ),
        }
    return report, diagnostic


def grouped(rows: list[Record]) -> list[tuple[Record, list[Record]]]:
    """Provide explicit overall, algorithm, scenario and reachability strata."""
    groups: list[tuple[Record, list[Record]]] = [
        ({"group_by": "overall", "group": "all"}, rows)
    ]
    for keys in (
        ("algorithm",),
        ("scenario",),
        ("reachability",),
        ("algorithm", "scenario", "reachability"),
    ):
        bins: dict[tuple[str, ...], list[Record]] = defaultdict(list)
        for row in rows:
            bins[tuple(row[key] for key in keys)].append(row)
        for values, selected in sorted(bins.items()):
            groups.append(
                ({"group_by": "+".join(keys), "group": "|".join(values)}, selected)
            )
    return groups


def tables(rows: list[Record]) -> tuple[list[Record], list[Record], list[Record]]:
    """Compute registered denominators, retained failure counts and paired outcomes."""
    rates, failures, pairs = [], [], []
    for identity, selected in grouped(rows):
        count = len(selected)
        model = sum(item["model_feasible"] for item in selected)
        executed = sum(item["was_run"] and item["eligible"] for item in selected)
        success = sum(item["los_strict_success"] for item in selected)
        rates.append(
            {
                **identity,
                "K": count,
                "M": model,
                "E": executed,
                "S": success,
                "M_over_K": model / count,
                "S_over_E": success / executed if executed else None,
                "S_over_K": success / count,
            }
        )
        for stage, key, predicate in (
            (
                "native",
                "native_failure_reason",
                lambda item: not item["model_feasible"],
            ),
            (
                "los_executed",
                "los_failure_reason",
                lambda item: item["was_run"] and not item["los_strict_success"],
            ),
            ("los_not_run", "los_failure_reason", lambda item: not item["was_run"]),
        ):
            counts = Counter(item[key] for item in selected if predicate(item))
            failures.extend(
                {**identity, "stage": stage, "failure_reason": reason, "count": number}
                for reason, number in sorted(counts.items())
            )
    bins: dict[tuple[str, int], dict[str, Record]] = defaultdict(dict)
    for row in rows:
        key = (row["scenario"], row["seed_label"])
        require(row["algorithm"] not in bins[key], "Duplicate paired task")
        bins[key][row["algorithm"]] = row
    for (scenario, label), pair in sorted(bins.items()):
        require(pair.keys() == {"rrt", "sst"}, "Unpaired RRT/SST task")
        record = {
            "scenario": scenario,
            "seed_label": label,
            "reachability": pair["rrt"]["reachability"],
        }
        for algorithm, row in pair.items():
            for key in (
                "native_status",
                "model_feasible",
                "was_run",
                "los_strict_success",
                "native_failure_reason",
                "los_failure_reason",
                "final_goal_distance_m",
            ):
                record[algorithm + "_" + key] = row[key]
        for name, key in (
            ("model", "model_feasible"),
            ("strict_los", "los_strict_success"),
        ):
            active = [algorithm for algorithm in ("rrt", "sst") if pair[algorithm][key]]
            record[name + "_paired_outcome"] = (
                "both"
                if len(active) == 2
                else active[0] + "_only"
                if active
                else "neither"
            )
        pairs.append(record)
    return rates, failures, pairs


def trajectory_metrics(
    scenario: Scenario,
    native: Record,
    audit: Record,
    native_trace: list[Record],
    saved: Record,
    row: Record,
) -> Record:
    """Derive arc lengths and actuation metrics from already audited records."""
    dt = read_config("stage5a_protocol.json")["kinematics"]["step_s"]
    returned_path = native["status"] != "no_solution"
    native_duration = (
        sum(item["duration_s"] for item in native["controls"])
        if returned_path
        else None
    )
    if native_duration is not None:
        compare(native_duration, len(native_trace) * dt, "native.total_duration")
    witness_length = (
        sum(item["duration_s"] for item in scenario.witness_controls)
        * scenario.initial.speed
        if scenario.reachability == "known_control_witness"
        else None
    )
    tracking, los_trace = saved["tracking"], saved["los_trace"]
    was_run = tracking["was_run"]
    first_margin = (
        next(
            (
                index
                for index, item in enumerate(los_trace)
                if item["margin_reason"] != "ok"
            ),
            len(los_trace),
        )
        if was_run
        else None
    )
    return {
        "job_id": row["job_id"],
        "scenario": scenario.id,
        "algorithm": row["algorithm"],
        "seed_label": row["seed_label"],
        "reachability": row["reachability"],
        "native_status": native["status"],
        "model_feasible": row["model_feasible"],
        "native_returned_duration_s": native_duration,
        "native_returned_arc_length_m": native_duration * scenario.initial.speed
        if native_duration is not None
        else None,
        "provided_witness_length_m": witness_length,
        "native_minimum_gap_lower_bound_m": audit.get("minimum_gap_lower_bound_m"),
        "native_peak_yaw_rate_deg_s": math.degrees(
            max((abs(item["yaw_rate_rad_s"]) for item in native_trace), default=0.0)
        )
        if returned_path
        else None,
        "native_peak_pitch_rate_deg_s": math.degrees(
            max((abs(item["pitch_rate_rad_s"]) for item in native_trace), default=0.0)
        )
        if returned_path
        else None,
        "native_peak_pitch_deg": math.degrees(
            max(
                [abs(scenario.initial.pitch)]
                + [abs(item["pitch_rad"]) for item in native_trace]
            )
        )
        if returned_path
        else None,
        "los_was_run": was_run,
        "los_strict_success": row["los_strict_success"],
        "los_simulated_arc_length_m": len(los_trace) * dt * scenario.initial.speed
        if was_run
        else None,
        "los_simulated_arc_length_includes_final_candidate_interval": True
        if was_run
        else None,
        "los_simulated_arc_length_is_full_margin_safety_claim": False
        if was_run
        else None,
        "los_full_margin_certified_prefix_length_m": (
            first_margin * dt * scenario.initial.speed
            if first_margin is not None
            else None
        ),
        "los_first_margin_rejected_interval_start_s": first_margin * dt
        if first_margin is not None and first_margin < len(los_trace)
        else None,
        "los_min_physical_clearance_lower_bound_m": tracking[
            "min_physical_clearance_lower_bound_m"
        ]
        if was_run
        else None,
        "los_min_mission_clearance_lower_bound_m": tracking[
            "min_mission_clearance_lower_bound_m"
        ]
        if was_run
        else None,
        "los_yaw_saturation_steps": tracking["yaw_saturation_steps"]
        if was_run
        else None,
        "los_pitch_saturation_steps": tracking["pitch_saturation_steps"]
        if was_run
        else None,
        "los_reference_bridge_length_m": tracking["reference_bridge_length_m"]
        if was_run
        else None,
    }


def analyze(local: Path, output: Path) -> Record:
    """Read all registered evidence first, then write only compact new summaries."""
    local, output = local.resolve(), output.resolve()
    require(not local.is_relative_to(ROOT), "Raw evidence must remain outside Git")
    require(
        output == (ROOT / "results/stage6b").resolve(), "Only Stage6B output is allowed"
    )
    protocol = read_config("stage6b_protocol.json")
    cfg = protocol["planning"]
    scenarios = {
        item.id: item for item in analytic_scenarios() if item.expected_reason == "ok"
    }
    scenarios.update(
        {
            identity: historical_scenario(identity)
            for identity in ("F_O1", "F_N1", "F_B1")
        }
    )
    expected = [
        {
            "job_id": f"{scenario}--{algorithm}--seed{label}",
            "scenario": scenario,
            "algorithm": algorithm,
            "seed_label": label,
            "ompl_seed": cfg["ompl_seed_by_label"][str(label)],
            "reachability": scenarios[scenario].reachability,
        }
        for scenario in cfg["cases"]
        for label in cfg["seed_labels"]
        for algorithm in cfg["algorithms"]
    ]
    manifest = read_json(output / "search_manifest.json")
    compare(manifest, expected, "search_manifest")
    require(
        len(manifest) == cfg["total_trials_maximum"] == 36,
        "Registered matrix is not 36",
    )
    with (output / "planning_runs.csv").open(encoding="utf-8", newline="") as stream:
        public_rows = list(csv.DictReader(stream))
    indexed = {item["job_id"]: item for item in public_rows}
    ids = {item["job_id"] for item in manifest}
    require(len(public_rows) == len(indexed) == len(ids), "Duplicate/missing CSV task")
    require(indexed.keys() == ids, "CSV tasks differ from manifest")
    search = local / "search"
    folders = {path.name: path for path in search.iterdir() if path.is_dir()}
    require(folders.keys() == ids, "Unregistered, partial or missing search directory")
    request_files = list(search.rglob("input.json"))
    require(
        len(request_files) == len(ids), "Duplicated pilot or nested attempt requests"
    )
    require(
        all(path.parent == folders[path.parent.name] for path in request_files),
        "Nested attempt directory",
    )
    unexpected = [
        str(path.relative_to(search))
        for path in search.rglob("*")
        if path.is_file()
        and (path.parent not in folders.values() or path.name not in REQUIRED_FILES)
    ]
    require(not unexpected, f"Partial/error/extra search evidence: {unexpected}")
    rows: list[Record] = []
    reports: list[Record] = []
    diagnostics: list[Record] = []
    trajectories: list[Record] = []
    for task in manifest:
        folder = folders[task["job_id"]]
        require(
            {path.name for path in folder.iterdir()} == REQUIRED_FILES,
            f"Incomplete job directory: {folder.name}",
        )
        row = read_json(folder / "condition_summary.json")
        check_fields(row, task, task["job_id"] + ".identity")
        check_csv_row(row, indexed[task["job_id"]])
        check_request(
            read_json(folder / "input.json"),
            task,
            scenarios[task["scenario"]],
            protocol,
            local,
        )
        native = read_json(folder / "output.json")
        with gzip.open(
            folder / "independent_record.json.gz", "rt", encoding="utf-8"
        ) as stream:
            saved = json.load(stream)
        require(
            saved.keys() == {"audit", "native_replay_trace", "tracking", "los_trace"},
            "Unexpected independent record schema",
        )
        for name in ("stdout.log", "stderr.log"):
            (folder / name).read_bytes()
        audit, native_trace = check_native(
            scenarios[task["scenario"]], native, saved, row, protocol
        )
        los, diagnostic = audit_los(
            scenarios[task["scenario"]], native_trace, saved, row
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        trajectories.append(
            trajectory_metrics(
                scenarios[task["scenario"]], native, audit, native_trace, saved, row
            )
        )
        reports.append(
            {
                **task,
                "native_status": native["status"],
                "model_feasible": row["model_feasible"],
                "native_deadline_rejected": native["native_deadline_rejected"],
                "planning_deadline_rejected": row["planning_deadline_rejected"],
                "independent_certificate_finish_s": row[
                    "independent_certificate_finish_s"
                ],
                "native_controls": len(native["controls"]),
                "native_nodes": len(native["states"]),
                "native_intervals": len(native_trace),
                "native_complete_interval_audit_passed": True,
                "saved_audit_and_trace_match": True,
                "native_certificate_matches": True,
                "maximum_native_node_position_error_m": audit.get(
                    "maximum_native_node_position_error_m"
                ),
                "native_rk4_intervals": audit.get("independent_rk4_intervals"),
                "native_maximum_rk4_error_m": audit.get("maximum_rk4_error_m"),
                "los_saved_trace_audit": los,
            }
        )
        rows.append(row)
        print(
            json.dumps(
                {
                    "audited": task["job_id"],
                    "native_intervals": len(native_trace),
                    "saved_los_intervals": los["saved_trace_intervals"],
                }
            ),
            flush=True,
        )
    totals = {
        "registered": len(manifest),
        "actually_run": len(rows),
        "complete": len(rows) == len(manifest),
        "model_successes": sum(row["model_feasible"] for row in rows),
        "actual_los_executions": sum(
            row["was_run"] and row["eligible"] for row in rows
        ),
        "strict_los_successes": sum(row["los_strict_success"] for row in rows),
        "pilot_only": False,
    }
    check_fields(
        read_json(output / "experiment_accounting.json"),
        totals,
        "experiment_accounting",
    )
    require(
        len(diagnostics) == totals["model_successes"] - totals["strict_los_successes"],
        "Missing model-success/LOS-failure diagnostics",
    )
    rates, failures, pairs = tables(rows)
    report = {
        "passed": True,
        "audit_mode": (
            "read saved evidence; recompute native control certificate "
            "and observed LOS steps only"
        ),
        "new_native_searches": 0,
        "new_los_simulations": 0,
        "totals": totals,
        "native_status_counts": dict(Counter(row["native_status"] for row in rows)),
        "planning_deadline_rejections": [
            {
                "job_id": row["job_id"],
                "native_status": row["native_status"],
                "independent_certificate_finish_s": row[
                    "independent_certificate_finish_s"
                ],
            }
            for row in rows
            if row["planning_deadline_rejected"]
        ],
        "single_directory_per_registered_job": True,
        "pilot_jobs_reused_once": cfg["pilot"],
        "pilot_reuse_evidence_limit": (
            "Single saved directory/request/response per pilot; "
            "no process history outside the preserved evidence tree is claimed."
        ),
        "partial_error_or_unregistered_directories": [],
        "raw_required_files_per_job": sorted(REQUIRED_FILES),
        "all_planner_requests_match_fixed_inputs_without_hidden_witness": True,
        "seed_labels_to_native_seeds": cfg["ompl_seed_by_label"],
        "native_audited_intervals": sum(item["native_intervals"] for item in reports),
        "los_audited_intervals": sum(
            item["los_saved_trace_audit"]["saved_trace_intervals"] for item in reports
        ),
        "terminal_diagnostics_count": len(diagnostics),
        "trajectory_metrics_count": len(trajectories),
        "trajectory_length_interpretation": (
            "Native length is the returned control arc length, retaining exact "
            "and approximate status. LOS simulated arc includes the final "
            "candidate interval and is not a full-margin safety claim. "
            "The full-margin prefix ends before the first margin rejection. "
            "Unexecuted LOS metrics and unknown historical witnesses stay null."
        ),
        "interpretation": (
            "Development correctness smoke only; terminal/last-edge relationships "
            "are observations, not causal evidence or algorithm superiority."
        ),
        "jobs": reports,
    }
    write_csv(output / "rates.csv", rates)
    write_csv(output / "failure_counts.csv", failures)
    write_csv(output / "paired_outcomes.csv", pairs)
    write_csv(output / "terminal_diagnostics.csv", diagnostics)
    write_csv(output / "trajectory_metrics.csv", trajectories)
    (output / "trace_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    """Require the existing raw record root; never invoke a planner or tracker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results/stage6b")
    args = parser.parse_args()
    result = analyze(args.local_root, args.output)
    print(
        json.dumps({"passed": result["passed"], **result["totals"]}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
