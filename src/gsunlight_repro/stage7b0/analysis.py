"""Summarize the six completed executions and archived controls without reruns."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT, read_config
from ..stage6c.common import boolean, read_csv, read_json
from ..stage6d.common import load_record, outcome, save_json
from . import PUBLIC


def run(raw: Path, local: Path) -> dict[str, Any]:
    """Keep six registered tasks and18 labelled baseline rows, with source scopes."""
    cfg = read_config("stage7b0_protocol.json")
    new = read_json(PUBLIC / "execution_results.json")
    if [r["job_id"] for r in new] != cfg["jobs"]:
        raise ValueError("Completed roster differs from the approved six")
    old = {
        r["job_id"]: r for r in read_csv(ROOT / "results/stage6ds/planning_runs.csv")
    }
    audit = {
        r["job_id"]: r for r in read_csv(ROOT / "results/stage7a/execution_index.csv")
    }
    comparisons, baselines, old_los = [], [], []
    for current in new:
        job = current["job_id"]
        if current != read_json(local / job / "result.json"):
            raise ValueError("Public summary differs from actual new raw result")
        original = load_record(raw / "search" / job / "independent_record.json.gz")
        old_los.append(original["los_trace"])
        native_ok = boolean(old[job]["model_feasible"])
        los_ok = boolean(old[job]["los_strict_success"])
        comparisons.append(
            {
                "job_id": job,
                "scenario": old[job]["scenario"],
                "native_seed": int(old[job]["native_seed"]),
                "NATIVE_OPEN_archived_success": native_ok,
                "LOS_FROZEN_archived_success": los_ok,
                "LTV_LQR_new_success": current["success"],
                "paired_outcome_vs_LOS": outcome(los_ok, current["success"]),
                "LOS_original_termination": audit[job]["reported_termination_reason"],
                "LOS_first_strict_kind": audit[job]["earliest_strict_failure_kind"],
                "LOS_first_strict_candidate_time_s": audit[job][
                    "earliest_strict_failure_time_s"
                ],
                "LQR_termination": current["failure_reason"],
                "LQR_first_margin_rejection_time_s": current[
                    "first_margin_rejection_time_s"
                ],
                "LQR_first_physical_rejection_time_s": current[
                    "first_physical_rejection_time_s"
                ],
                "LQR_executed_intervals": current["intervals"],
                "native_saved_intervals": current["native_source_intervals"],
                "LQR_final_goal_distance_m": current["final_goal_distance_m"],
                "LQR_minimum_required_gap_lower_bound_m": current[
                    "minimum_required_gap_lower_bound_m"
                ],
                "LQR_maximum_reference_position_error_m": current[
                    "maximum_reference_position_error_m"
                ],
                "LQR_maximum_feedforward_difference_rad_s": current[
                    "maximum_feedforward_difference_rad_s"
                ],
                "LQR_all_interval_RK4_error_m": current["independent_certificate"][
                    "maximum_all_interval_rk4_error_m"
                ],
                "LQR_setup_wall_s": current["setup_wall_s"],
                "LQR_execution_and_certification_wall_s": current[
                    "execution_and_certification_wall_s"
                ],
                "original_planning_certificate_wall_s": current[
                    "original_planning_certificate_wall_s"
                ],
                "combined_wall_s": current["combined_wall_s"],
                "within_frozen_budgets": current["within_frozen_budgets"],
                "new_trace": f"{job}/execution.json.gz",
                "historical_trace": f"search/{job}/independent_record.json.gz",
                "scope": (
                    "fixed_development_diagnostic_nominal_"
                    "no_robustness_or_generalization_claim"
                ),
            }
        )
        for method, success, reason, gap, first, scope in (
            (
                "NATIVE-OPEN",
                native_ok,
                original["audit"]["reason"],
                original["audit"]["minimum_gap_lower_bound_m"],
                "not_observed",
                "archived_full_native_certificate_no_new_performance_replay",
            ),
            (
                "LOS-FROZEN",
                los_ok,
                audit[job]["reported_termination_reason"],
                audit[job]["LOS_required_gap_lower_bound_derived_m"],
                audit[job]["earliest_strict_failure_time_s"],
                "archived_frozen_LOS_execution",
            ),
            (
                "LTV-LQR",
                current["success"],
                current["failure_reason"],
                current["minimum_required_gap_lower_bound_m"],
                current["first_margin_rejection_time_s"],
                "new_zero_error_nominal_execution_with_own_certificate",
            ),
        ):
            baselines.append(
                {
                    "job_id": job,
                    "method": method,
                    "strict_success": success,
                    "termination": reason,
                    "minimum_required_gap_lower_bound_m": gap,
                    "first_strict_candidate_time_s": first,
                    "data_source": scope,
                    "is_new_execution": method == "LTV-LQR",
                }
            )
    write_csv(PUBLIC / "comparison.csv", comparisons)
    write_csv(PUBLIC / "baselines.csv", baselines)
    write_csv(
        PUBLIC / "failures.csv", [r for r in baselines if not r["strict_success"]]
    )
    distinct_los: list[list[dict[str, Any]]] = []
    for trace in old_los:
        if not any(trace == prior for prior in distinct_los):
            distinct_los.append(trace)
    certificate_ok = all(
        r["independent_certificate"]["certificate_consistent"] for r in new
    )
    false_positives = sum(
        r["online_strict_success"]
        and not (
            r["independent_certificate"]["full_margin_safe"]
            and r["independent_certificate"]["goal_reached"]
        )
        for r in new
    )
    successes = sum(r["success"] for r in new)
    decision = (
        "BLOCKED"
        if not certificate_ok or false_positives
        else "ENGINEERING-RESOLVED"
        if successes >= 5
        else "NEED-EVIDENCE"
    )
    result = {
        "decision": decision,
        "registered_tasks": 6,
        "usable_native_sources": 6,
        "new_nominal_executions": 6,
        "additional_independent_certifications": 6,
        "NATIVE_OPEN_archived_successes": 6,
        "LOS_FROZEN_archived_successes": sum(
            r["LOS_FROZEN_archived_success"] for r in comparisons
        ),
        "LTV_LQR_successes": successes,
        "recovered_old_failures": sum(
            r["paired_outcome_vs_LOS"] == "recovered" for r in comparisons
        ),
        "regressions": sum(
            r["paired_outcome_vs_LOS"] == "regressed" for r in comparisons
        ),
        "distinct_archived_LOS_trajectories": len(distinct_los),
        "unique_LOS_successes": sum(
            all(row["margin_reason"] == "ok" for row in t)
            and t[-1]["goal_distance_after_m"] <= 0.75
            for t in distinct_los
        ),
        "new_failed_or_timed_out": 6 - successes,
        "new_unrun": 0,
        "strict_safety_false_positives": false_positives,
        "certified_new_intervals": sum(
            r["independent_certificate"]["certified_intervals"] for r in new
        ),
        "maximum_all_interval_RK4_error_m": max(
            r["independent_certificate"]["maximum_all_interval_rk4_error_m"]
            for r in new
        ),
        "maximum_reference_position_error_m": max(
            r["maximum_reference_position_error_m"] for r in new
        ),
        "maximum_feedforward_difference_rad_s": max(
            r["maximum_feedforward_difference_rad_s"] for r in new
        ),
        "new_planning_searches": 0,
        "new_LOS_executions": 0,
        "robustness_established": False,
        "original_algorithm_authorized": False,
        "decision_scope": (
            "Only the six approved diagnostic tasks; "
            "no inference that all15 or all47 were newly executed"
        ),
        "stop_for_review": True,
    }
    if not math.isfinite(result["maximum_all_interval_RK4_error_m"]):
        raise ValueError("Nonfinite certification evidence")
    save_json(PUBLIC / "decision.json", result)
    return result


def main() -> None:
    """Summarize existing records only, without execution capability."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.raw_root, args.local_root))


if __name__ == "__main__":
    main()
