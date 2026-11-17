"""Validate six public paired records without repeating any performance trial."""

from __future__ import annotations

import json
from typing import Any

from ..stage5a.maps import ROOT, read_config
from ..stage6c.common import boolean, read_csv, read_json
from ..stage7a.public_evidence import validate as validate_stage7a
from . import PUBLIC
from .lqr import Limits, weights


def validate() -> dict[str, Any]:
    """Reject denominator/source drift, changed weights and absent safety proofs."""
    validate_stage7a()
    config = read_config("stage7b0_protocol.json")
    gate = read_json(PUBLIC / "admission/summary.json")
    q, r, qf = weights(Limits.frozen())
    if not gate["passed"] or gate["tests"] != 19:
        raise ValueError("The actual19-case admission did not pass")
    if (gate["Q"], gate["R"], gate["Qf"]) != (q.tolist(), r.tolist(), qf.tolist()):
        raise ValueError("Frozen LQR weights changed")
    original = {
        row["job_id"]: row
        for row in read_csv(ROOT / "results/stage6ds/planning_runs.csv")
    }
    results = read_json(PUBLIC / "execution_results.json")
    comparisons = read_csv(PUBLIC / "comparison.csv")
    baselines = read_csv(PUBLIC / "baselines.csv")
    ledger = read_json(PUBLIC / "execution_ledger.json")
    if [row["job_id"] for row in results] != config["jobs"] or len(results) != 6:
        raise ValueError("New execution roster changed")
    if [row["job_id"] for row in comparisons] != config["jobs"] or len(baselines) != 18:
        raise ValueError("The six-row or18-row comparison denominator changed")
    if not all(row["run_state"] == "completed" for row in ledger) or len(ledger) != 6:
        raise ValueError("Original execution ledger is incomplete")
    for current, comparison in zip(results, comparisons, strict=True):
        job, proof = current["job_id"], current["independent_certificate"]
        if boolean(comparison["LOS_FROZEN_archived_success"]) != boolean(
            original[job]["los_strict_success"]
        ):
            raise ValueError("Historical LOS label changed")
        if not (
            proof["certificate_consistent"]
            and proof["full_margin_safe"]
            and proof["goal_reached"]
            and proof["certified_intervals"]
            == current["intervals"]
            == proof["rk4_intervals"]
            and current["intervals"] <= current["native_source_intervals"]
            and current["within_frozen_budgets"]
            and current["success"]
            and current["maximum_feedforward_difference_rad_s"] == 0
            and current["maximum_reference_position_error_m"] == 0
            and proof["maximum_all_interval_rk4_error_m"] <= 1e-10
            and current["final_goal_distance_m"] <= 0.75
        ):
            raise ValueError("A new trajectory lacks consistent independent evidence")
        group = [row for row in baselines if row["job_id"] == job]
        if {row["method"] for row in group} != {
            "NATIVE-OPEN",
            "LOS-FROZEN",
            "LTV-LQR",
        } or len(group) != 3:
            raise ValueError("A paired baseline was omitted or duplicated")
    decision = read_json(PUBLIC / "decision.json")
    expected = {
        "registered_tasks": 6,
        "new_nominal_executions": 6,
        "LTV_LQR_successes": 6,
        "LOS_FROZEN_archived_successes": 1,
        "recovered_old_failures": 5,
        "regressions": 0,
        "strict_safety_false_positives": 0,
        "new_planning_searches": 0,
        "certified_new_intervals": 3113,
    }
    if any(decision[key] != value for key, value in expected.items()):
        raise ValueError("Public research accounting differs from actual records")
    if (
        decision["decision"] != "ENGINEERING-RESOLVED"
        or decision["robustness_established"]
        or decision["original_algorithm_authorized"]
    ):
        raise ValueError("Scientific scope changed")
    for name in ("REPORT", "MODEL", "CHECKS", "DIRECTIONS"):
        if not (ROOT / f"docs/STAGE7B0_{name}_CN.md").is_file():
            raise FileNotFoundError(name)
    if not (PUBLIC / "output/pdf/stage7b0_directions_cn.pdf").is_file():
        raise FileNotFoundError("Missing two-page direction review")
    return {
        "passed": True,
        "registered": 6,
        "paired_baselines": 18,
        "admission_tests": 19,
        "new_intervals_with_saved_certificate": 3113,
        "new_trials_in_this_check": 0,
        "private_raw_sources_required": False,
    }


if __name__ == "__main__":
    print(json.dumps(validate()))
