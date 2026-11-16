"""Registered obstacle search with unchanged official6C trees and full denominators."""

from __future__ import annotations

import argparse
import json
import random
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from ..stage5a.analysis import write_csv
from ..stage5a.maps import read_config
from ..stage6b.bridge import invoke_native
from ..stage6b.replay import audit_controls, track_reference
from ..stage6b.runner import exclusive_run
from ..stage6b.scenarios import Scenario, export_scenario
from ..stage6c.acceptance import environment
from ..stage6c.calibration import available_memory, validate_events
from ..stage6c.common import read_json
from ..stage6c.reference import certify_los
from .common import PUBLIC, save_json, save_record
from .maps import build_scenarios, roster


def trace_metrics(trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe all returned trajectories, including safe approximate prefixes."""
    if not trace:
        return {
            "returned_intervals": 0,
            "minimum_gap_m": None,
            "gap_q25_m": None,
            "gap_median_m": None,
            "maximum_pitch_deg": None,
            "total_absolute_yaw_change_deg": None,
            "total_absolute_pitch_change_deg": None,
        }
    gaps = np.asarray([r["minimum_gap_lower_bound_m"] for r in trace])
    return {
        "returned_intervals": len(trace),
        "minimum_gap_m": float(gaps.min()),
        "gap_q25_m": float(np.quantile(gaps, 0.25)),
        "gap_median_m": float(np.median(gaps)),
        "maximum_pitch_deg": float(np.degrees(max(abs(r["pitch_rad"]) for r in trace))),
        "total_absolute_yaw_change_deg": float(
            np.degrees(sum(abs(r["yaw_rate_rad_s"]) * 0.1 for r in trace))
        ),
        "total_absolute_pitch_change_deg": float(
            np.degrees(sum(abs(r["pitch_rate_rad_s"]) * 0.1 for r in trace))
        ),
    }


def run_one(
    task: dict[str, Any],
    case: Scenario,
    request: dict[str, Any],
    executable: Path,
    dependency: Path,
    folder: Path,
) -> dict[str, Any]:
    """Save original clocks before fallible postprocessing; never retry a search."""
    random.seed(task["seed"])
    np.random.seed(task["seed"])
    started = time.perf_counter()
    native = invoke_native(
        executable, request, folder, environment=environment(dependency)
    )
    payload = native.payload
    save_json(
        folder / "native_clock.json",
        {**native.timing, "observed_return_elapsed_s": time.perf_counter() - started},
        exclusive=True,
    )
    first_audit, first_finished = None, None
    if payload.get("first_path") is not None:
        first_audit, _ = audit_controls(
            case, {**payload["first_path"], "status": "exact"}
        )
        first_finished = time.perf_counter() - started
    audit, trace = audit_controls(case, payload)
    finish = time.perf_counter() - started
    if payload.get("first_path_is_final"):
        first_audit, first_finished = audit, finish
    save_json(
        folder / "certificate_clock.json",
        {
            "first_independent_finish_s": first_finished,
            "final_independent_finish_s": finish,
        },
        exclusive=True,
    )
    if not audit["independent_audit_passed"] or (
        first_audit is not None and not first_audit["model_feasible"]
    ):
        raise RuntimeError(
            "Native model/safety certificate disagreement; stop comparison"
        )
    events = payload["improvement_events"]
    costs = validate_events(events)
    duration = sum(float(control["duration_s"]) for control in payload["controls"])
    if audit["model_feasible"] and (not costs or abs(costs[-1] - duration) > 1e-9):
        raise RuntimeError("Native event/final cost mismatch")
    model = bool(audit["model_feasible"] and finish <= 10.0)
    tracking = {
        "was_run": False,
        "eligible": False,
        "execution_success": False,
        "failure_reason": "not_run_no_budget_qualified_native",
    }
    los_trace, los_audit, execution_wall = [], None, None
    if model:
        execution_started = time.perf_counter()
        tracking, los_trace = track_reference(case, audit, trace)
        if tracking["was_run"]:
            los_audit = certify_los(los_trace, case)
        execution_wall = time.perf_counter() - execution_started
        save_json(
            folder / "execution_clock.json",
            {"execution_and_audit_s": execution_wall},
            exclusive=True,
        )
        if tracking["execution_success"] and not (
            los_audit and los_audit["full_margin_safe"] and los_audit["goal_reached"]
        ):
            raise RuntimeError("LOS strict safety false positive; stop comparison")
    strict = bool(
        model
        and tracking["execution_success"]
        and execution_wall is not None
        and execution_wall <= 20
        and finish + execution_wall <= 30
    )
    reason = (
        "planning_deadline"
        if finish > 10
        else audit["reason"]
        if not model
        else "execution_deadline"
        if execution_wall is not None and execution_wall > 20
        else "pipeline_deadline"
        if execution_wall is not None and finish + execution_wall > 30
        else tracking["failure_reason"]
    )
    row = {
        "job_id": task["job_id"],
        "scenario": case.id,
        "family": case.scene.specification["family"],
        "condition": task["id"],
        "algorithm": task["algorithm"],
        "search_mode": task["mode"],
        "native_seed": task["seed"],
        "reachability": "independently_certified_control_witness",
        "data_role": "obstacle_development",
        "native_status": payload["status"],
        "native_M_before_budget": audit["model_feasible"],
        "model_feasible": model,
        "first_native_certificate_s": events[0]["native_certificate_finish_s"]
        if events
        else None,
        "first_independent_certificate_s": first_finished,
        "best_independent_certificate_s": finish,
        "planning_deadline_rejected": finish > 10,
        "native_candidate_return_s": payload["candidate_return_s"],
        "first_native_cost_m": costs[0] if costs else None,
        "returned_control_arc_m": duration if payload["controls"] else None,
        "strict_control_arc_m": duration if model else None,
        "reference_geometry_safe": bool(
            tracking.get("reference_chords_certified", False)
        )
        if model
        else None,
        "los_was_run": tracking["was_run"],
        "los_eligible": tracking["eligible"],
        "los_strict_success": strict,
        "los_failure_reason": tracking["failure_reason"],
        "execution_and_audit_wall_s": execution_wall,
        "pipeline_wall_s": finish + execution_wall
        if execution_wall is not None
        else finish,
        "failure_reason": reason,
        "peak_native_rss_bytes": payload["peak_native_rss_bytes"],
        "propagated_intervals": payload["propagated_intervals"],
        "propagator_calls": payload["propagator_calls"],
        "state_validity_calls": payload["state_validity_calls"],
        "collision_queries": payload["collision_queries"],
        "box_distance_tests": payload["box_distance_tests"],
        "rejection_counts": json.dumps(payload["rejection_counts"], sort_keys=True),
        "maximum_rk4_error_m": audit.get("maximum_rk4_error_m"),
        "initial_yaw_rad": case.initial.yaw,
        "initial_pitch_rad": case.initial.pitch,
        "gap_query_truncation_m": 3.0,
        **trace_metrics(trace),
        **native.timing,
    }
    save_record(
        folder / "independent_record.json.gz",
        {
            "audit": audit,
            "first_audit": first_audit,
            "native_trace": trace,
            "tracking": tracking,
            "los_audit": los_audit,
            "los_trace": los_trace,
        },
    )
    save_json(folder / "condition_summary.json", row, exclusive=True)
    return row


def run(
    executable: Path,
    dependency: Path,
    local: Path,
    output: Path,
    *,
    pilot_only: bool = False,
) -> dict[str, Any]:
    """Reuse three pilots verbatim; reject partial directories instead of rerunning."""
    if not read_json(output / "d2_witness_acceptance.json")["passed"]:
        raise RuntimeError("All six control witnesses must pass before searching")
    cfg = read_config("stage6d_protocol.json")["d2"]
    tasks = roster(read_config("stage6d_protocol.json"))
    manifest = output / "d2_manifest.json"
    if manifest.exists() and read_json(manifest) != tasks:
        raise RuntimeError("Registered roster changed")
    save_json(manifest, tasks)
    cases = {case.id: case for case in build_scenarios()}
    scenes = {
        name: export_scenario(case, local / "grids") for name, case in cases.items()
    }
    rows, curves = [], []
    for index, task in enumerate(tasks[:3] if pilot_only else tasks):
        request = {
            "mode": "plan",
            "algorithm": task["algorithm"],
            "search_mode": task["mode"],
            "seed": task["seed"],
            "scenario": scenes[task["scenario"]],
            "search_budget_s": cfg["search_cap_s"],
            **{
                key: cfg[key]
                for key in (
                    "selection_radius",
                    "pruning_radius",
                    "goal_bias",
                    "propagation_min_steps",
                    "propagation_max_steps",
                )
            },
        }
        folder = local / "search" / task["job_id"]
        if (folder / "condition_summary.json").exists():
            if read_json(folder / "input.json") != request:
                raise RuntimeError("Existing pilot request differs")
            row = read_json(folder / "condition_summary.json")
        else:
            if available_memory() < cfg["resource_gate"]["minimum_available_ram_bytes"]:
                raise RuntimeError("Available RAM resource gate failed")
            try:
                row = run_one(
                    task,
                    cases[task["scenario"]],
                    request,
                    executable,
                    dependency,
                    folder,
                )
            except Exception:
                if folder.exists():
                    save_json(
                        folder / "stopped.json",
                        {"job": task["job_id"], "error": traceback.format_exc()},
                        exclusive=True,
                    )
                save_json(
                    output / "d2_stopped.json",
                    {
                        "failed_job": task["job_id"],
                        "completed": len(rows),
                        "registered": 54,
                        "error": traceback.format_exc(),
                    },
                )
                raise
        rows.append(row)
        payload = read_json(folder / "output.json")
        curves.extend(
            {
                "job_id": task["job_id"],
                "condition": task["id"],
                "scenario": task["scenario"],
                "native_seed": task["seed"],
                "event": i,
                **event,
            }
            for i, event in enumerate(payload["improvement_events"])
        )
        write_csv(output / "planning_runs.csv", rows)
        if curves:
            write_csv(output / "native_cost_events.csv", curves)
        if index < 3:
            size = sum(
                path.stat().st_size for path in folder.iterdir() if path.is_file()
            )
            if (
                row["peak_native_rss_bytes"]
                > cfg["resource_gate"]["maximum_native_rss_bytes"]
                or size > cfg["resource_gate"]["maximum_job_record_bytes"]
            ):
                raise RuntimeError("Pilot memory/record-size gate failed")
        accounting = {
            "registered": 54,
            "actually_completed": len(rows),
            "complete": len(rows) == 54,
            "pilot_reused": not pilot_only,
            "M": sum(r["model_feasible"] for r in rows),
            "Gref": sum(r["reference_geometry_safe"] is True for r in rows),
            "E": sum(r["los_was_run"] and r["los_eligible"] for r in rows),
            "S": sum(r["los_strict_success"] for r in rows),
        }
        save_json(output / "d2_accounting.json", accounting)
        print(
            json.dumps(
                {
                    "job": task["job_id"],
                    "status": row["native_status"],
                    "M": row["model_feasible"],
                    "S": row["los_strict_success"],
                }
            ),
            flush=True,
        )
    return accounting


def main() -> None:
    """Lock the serial batch and stop immediately on a consistency failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "dependency-root", "local-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    parser.add_argument("--pilot-only", action="store_true")
    args = parser.parse_args()
    with exclusive_run(args.local_root):
        print(
            json.dumps(
                run(
                    args.executable,
                    args.dependency_root,
                    args.local_root,
                    args.output,
                    pilot_only=args.pilot_only,
                )
            )
        )


if __name__ == "__main__":
    main()
