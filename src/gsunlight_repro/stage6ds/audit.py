"""Read-only complete trajectory review; original experiment clocks never change."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage6b.replay import audit_controls
from ..stage6c.common import boolean, read_csv, read_json
from ..stage6c.reference import certify_los
from ..stage6d.analysis import audit_commands
from ..stage6d.common import load_record, save_json
from ..stage6d.maps import build_scenarios
from . import PUBLIC
from .planning import audit_completed
from .protocol import frozen


def run(local: Path) -> dict[str, Any]:
    """Recheck all54 paths and every saved LOS interval, retaining all failures."""
    cfg, tasks = frozen()
    rows = read_csv(PUBLIC / "planning_runs.csv")
    if len(rows) != 54 or any(r["run_state"] != "completed" for r in rows):
        raise ValueError("Complete54 original results are required")
    cases = {c.id: c for c in build_scenarios()}
    checks, failures = [], []
    native_intervals = first_intervals = los_intervals = 0
    maximum_rk4 = maximum_los_error = 0.0
    for task, row in zip(tasks, rows, strict=True):
        if task["job_id"] != row["job_id"]:
            raise ValueError("Roster/order changed")
        folder = local / "search" / task["job_id"]
        native, request = (
            read_json(folder / "output.json"),
            read_json(folder / "input.json"),
        )
        if "controls" in request or "controls" in request["scenario"]:
            raise ValueError("Witness controls leaked into a planning request")
        audit_completed(
            task, request, folder, read_json(folder / "condition_summary.json"), cfg
        )
        case = cases[task["scenario"]]
        original = load_record(folder / "independent_record.json.gz")
        audit, trace = audit_controls(case, native)
        if not audit["independent_audit_passed"] or len(trace) != len(
            original["native_trace"]
        ):
            raise ValueError("Full native control recertification failed")
        if audit["model_feasible"] != original["audit"]["model_feasible"]:
            raise ValueError("Saved native admission differs from posthoc audit")
        native_intervals += len(trace)
        maximum_rk4 = max(maximum_rk4, audit.get("maximum_rk4_error_m", 0))
        if native.get("first_path") is not None:
            first, first_trace = audit_controls(
                case, {**native["first_path"], "status": "exact"}
            )
            if not first["model_feasible"]:
                raise ValueError(
                    "Saved first incumbent failed independent recertification"
                )
            first_intervals += len(first_trace)
            maximum_rk4 = max(maximum_rk4, first["maximum_rk4_error_m"])
        saved_los = original["los_trace"]
        los = None
        if saved_los:
            reference = [case.initial.position] + [tuple(r["position"]) for r in trace]
            if reference[-1] != case.scene.goal:
                reference.append(case.scene.goal)
            audit_commands(reference, saved_los, "A")
            los = certify_los(saved_los, case)
            for i, interval in enumerate(saved_los):
                if not math.isclose(interval["time_s"], (i + 1) * 0.1, abs_tol=1e-9):
                    raise ValueError("Saved LOS interval clock differs from frozen dt")
            los_intervals += len(saved_los)
            maximum_los_error = max(
                maximum_los_error, los["maximum_los_position_error_m"]
            )
        if boolean(row["los_strict_success"]) and not (
            los and los["full_margin_safe"] and los["goal_reached"]
        ):
            raise ValueError("A strict LOS success is a safety false positive")
        checks.append(
            {
                "job_id": row["job_id"],
                "native_intervals": len(trace),
                "native_audit_passed": True,
                "native_exact_safe": audit["model_feasible"],
                "original_budget_qualified_M": boolean(row["model_feasible"]),
                "los_intervals": len(saved_los),
                "los_record_audit_passed": True,
                "maximum_native_node_error_m": audit.get(
                    "maximum_native_node_position_error_m"
                ),
                "maximum_rk4_error_m": audit.get("maximum_rk4_error_m"),
            }
        )
        if not boolean(row["los_strict_success"]):
            failed = next(
                (
                    r
                    for r in saved_los
                    if r["margin_reason"] != "ok"
                    or r["mission_reason"] != "ok"
                    or r["physical_reason"] != "ok"
                    or r["cross_track_m"] > 3
                ),
                None,
            )
            point = (
                failed["position"]
                if failed
                else native["states"][-1][:3]
                if native["states"]
                else [None] * 3
            )
            failures.append(
                {
                    "job_id": row["job_id"],
                    "condition": row["condition"],
                    "reason": row["failure_reason"],
                    "location_kind": (
                        "first_recorded_LOS_limit_candidate_not_collision_instant"
                    )
                    if failed
                    else "native_terminal_not_collision_location",
                    "candidate_x": point[0],
                    "candidate_y": point[1],
                    "candidate_z": point[2],
                    "interval_start_s": failed["time_start_s"] if failed else None,
                    "interval_end_s": failed["time_s"] if failed else None,
                    "margin_reason": failed["margin_reason"] if failed else None,
                    "physical_reason": failed["physical_reason"] if failed else None,
                }
            )
    write_csv(PUBLIC / "final_audit_cases.csv", checks)
    write_csv(PUBLIC / "failure_positions.csv", failures)
    result = {
        "passed": True,
        "jobs": 54,
        "native_intervals": native_intervals,
        "additional_first_incumbent_intervals": first_intervals,
        "los_intervals": los_intervals,
        "maximum_rk4_error_m": maximum_rk4,
        "maximum_los_position_error_m": maximum_los_error,
        "strict_safety_false_positives": 0,
        "new_searches": 0,
        "original_clocks_unchanged": True,
    }
    save_json(PUBLIC / "final_trace_audit.json", result)
    return result


def main() -> None:
    """Save only compact audit summaries, never another copy of large traces."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, required=True)
    print(run(parser.parse_args().local_root))


if __name__ == "__main__":
    main()
