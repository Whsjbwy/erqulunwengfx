"""Validate published54-job arithmetic; do not claim CI reran local searches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..stage6c.common import boolean, read_csv, read_json
from ..stage6d.common import save_json
from . import PUBLIC
from .analysis import group_rates
from .protocol import frozen


def main() -> None:
    """Bind real Windows engineering proof and distinct saved-local experiment data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality-root", type=Path, required=True)
    args = parser.parse_args()
    cfg, tasks = frozen()
    rows = read_csv(PUBLIC / "planning_runs.csv")
    stats = read_json(PUBLIC / "statistics.json")
    audit = read_json(PUBLIC / "final_trace_audit.json")
    decision = read_json(PUBLIC / "decision.json")
    available = read_csv(PUBLIC / "deadline_available_incumbents.csv")
    if len(rows) != 54 or [r["job_id"] for r in rows] != [t["job_id"] for t in tasks]:
        raise ValueError("Published roster differs from frozen54")
    if not all(r["run_state"] == "completed" for r in rows):
        raise ValueError("Published trials contain unrun or exception rows")
    for row, task in zip(rows, tasks, strict=True):
        model = boolean(row["model_feasible"])
        if int(row["native_seed"]) != task["seed"] or row["condition"] != task["id"]:
            raise ValueError("Published condition/seed drift")
        if model != (
            boolean(row["native_M_before_budget"])
            and float(row["best_independent_certificate_s"]) <= cfg["planning_cap_s"]
        ):
            raise ValueError("Frozen final-certificate M definition changed")
        if boolean(row["los_strict_success"]) and not (
            model
            and float(row["execution_and_audit_wall_s"]) <= cfg["execution_cap_s"]
            and float(row["pipeline_wall_s"]) <= cfg["pipeline_cap_s"]
        ):
            raise ValueError("A published strict success violates original deadlines")
        if row["adapter_id"] != "auv_pitch_contract_v1" or not boolean(
            row["actual_planner_identity_passed"]
        ):
            raise ValueError("Published planner identity is inconsistent")
    rates = group_rates(rows)
    if any(rates[k] != stats[k] for k in rates):
        raise ValueError("Published full denominators disagree with statistics")
    if (
        len(available) != 54
        or sum(boolean(r["certificate_available_before10"]) for r in available)
        != stats["at_least_one_independent_certificate_before10"]
    ):
        raise ValueError("Available incumbent disclosure is incomplete")
    if (
        not audit["passed"]
        or audit["jobs"] != 54
        or audit["strict_safety_false_positives"]
    ):
        raise ValueError("Local full trace audit is incomplete")
    proof = read_json(args.quality_root / "head-evidence.json")
    result = {
        "exact_engineering_head": proof["checked_out_head"],
        "exact_pr_head_ci": proof["exact_pr_head_ci"],
        "engineering_checks_passed": proof["engineering_checks_passed"],
        "performance_source": "Saved original local54 experiments, not CI replanning",
        "local_registered_searches": 54,
        "local_completed_searches": 54,
        "primary_frozen_final_certificate_rates": rates,
        "at_least_one_independent_certificate_before10": stats[
            "at_least_one_independent_certificate_before10"
        ],
        "local_full_trace_audit": audit,
        "scientific_decision": decision["decision"],
        "stochastic_searches_in_ci": 0,
        "h1_implementation_authorized": False,
    }
    save_json(
        args.quality_root / "public-performance-evidence.json", result, exclusive=True
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
