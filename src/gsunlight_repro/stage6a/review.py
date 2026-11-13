"""Read frozen public CSVs without rerunning or modifying historical experiments."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read UTF-8 CSV, including files exported with an Excel-compatible BOM."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def boolean(value: str) -> bool:
    """Reject missing or malformed truth values instead of counting them as false."""
    if value not in ("True", "False"):
        raise ValueError(f"Unexpected historical Boolean: {value!r}")
    return value == "True"


def historical_review(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Recompute denominators and terminal mechanisms from frozen Stage5A-F data."""
    folder = root / "results/stage5af"
    plans = read_rows(folder / "planning_runs.csv")
    execution = read_rows(folder / "execution_runs.csv")
    mechanisms = read_rows(folder / "terminal_mechanisms.csv")
    if len({row["job_id"] for row in plans}) != len(plans):
        raise ValueError("Duplicate planning job identities")
    if len({row["case_id"] for row in execution}) != len(execution):
        raise ValueError("Duplicate execution condition identities")
    solved = {row["job_id"] for row in plans if boolean(row["geometry_success"])}
    rates = []
    groups = sorted({(r["processing"], r["controller"]) for r in execution})
    for processing, controller in groups:
        group = [
            row
            for row in execution
            if (row["processing"], row["controller"]) == (processing, controller)
        ]
        eligible = [row for row in group if boolean(row["was_run"])]
        if {row["job_id"] for row in eligible} != solved:
            raise ValueError("Execution denominator differs from solved planning set")
        successes = sum(boolean(row["execution_success"]) for row in eligible)
        rates.append(
            {
                "historical_stage": "5A-F",
                "processing": processing,
                "controller": controller,
                "planning_trials_K": len(plans),
                "geometric_successes_G": len(solved),
                "actual_executions_E": len(eligible),
                "strict_successes_S": successes,
                "geometric_success_rate_G_over_K": len(solved) / len(plans),
                "conditional_execution_rate_S_over_E": successes / len(eligible),
                "complete_task_rate_S_over_K": successes / len(plans),
                "margin_policy": "historical_body_or_margin_modes_mixed",
            }
        )
    fixed = [
        row
        for row in mechanisms
        if row["phase"] == "independent" and row["controller"] == "los_terminal_v1"
    ]
    failures = [row for row in fixed if not boolean(row["execution_success"])]
    summary = {
        "stage5af_planning_trials": len(plans),
        "stage5af_geometry_successes": len(solved),
        "stage5af_registered_execution_rows": len(execution),
        "stage5af_actual_execution_rows": sum(
            boolean(row["was_run"]) for row in execution
        ),
        "stage5af_fixed_los_conditions": len(fixed),
        "stage5af_fixed_los_failures": len(failures),
        "stage5af_failure_phase_counts": dict(
            Counter(row["first_failure_phase"] for row in failures)
        ),
        "stage5af_reachability_task_counts": dict(
            Counter(row["reachability"] for row in plans)
        ),
        "sources": [
            "results/stage5af/planning_runs.csv",
            "results/stage5af/execution_runs.csv",
            "results/stage5af/terminal_mechanisms.csv",
        ],
        "interpretation": (
            "Historical mixed-radius diagnostic results, not Stage6A performance "
            "or the uniform-margin future benchmark. Conditions share paths/maps."
        ),
    }
    return summary, rates


def main() -> None:
    """Write only new compact review artifacts, with all history left read-only."""
    summary, rates = historical_review(ROOT)
    output = ROOT / "results/stage6a"
    output.mkdir(exist_ok=True)
    write_csv(output / "historical_success_rates.csv", rates)
    (output / "historical_review.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
