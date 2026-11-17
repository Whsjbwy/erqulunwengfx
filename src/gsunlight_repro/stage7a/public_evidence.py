"""Check public denominators and provenance without private traces or propagation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..stage5a.maps import ROOT
from ..stage6c.common import boolean, read_csv, read_json
from . import PUBLIC


def validate(root: Path = ROOT) -> dict[str, Any]:
    """Fail on denominator drift, changed historic labels or incomplete citations."""
    new = root / "results/stage7a"
    old = read_csv(root / "results/stage6ds/planning_runs.csv")
    old_runs = {r["job_id"]: r for r in old if boolean(r["model_feasible"])}
    index = read_csv(new / "execution_index.csv")
    failures = read_csv(new / "failure_audit.csv")
    summary = read_json(new / "audit_summary.json")
    if len(index) != 47 or len({r["job_id"] for r in index}) != 47:
        raise ValueError("Public execution denominator is not exactly47 unique jobs")
    if set(old_runs) != {r["job_id"] for r in index}:
        raise ValueError("Public index differs from original M_final47")
    for row in index:
        original = old_runs[row["job_id"]]
        if (
            boolean(row["LOS_strict_success"])
            != boolean(original["los_strict_success"])
            or row["reported_termination_reason"] != original["los_failure_reason"]
            or not boolean(row["saved_control_node_correspondence_passed"])
            or not boolean(row["actual_saved_initial_state_matches"])
        ):
            raise ValueError("Original labels or saved-source correspondence changed")
    failed_ids = {r["job_id"] for r in index if not boolean(r["LOS_strict_success"])}
    if len(failures) != 15 or {r["job_id"] for r in failures} != failed_ids:
        raise ValueError("Failure subset is inconsistent with original E47/S32")
    if summary["earliest_strict_failure_counts"] != {"margin": 12, "tracking": 3}:
        raise ValueError("Unexpected first strict-event accounting")
    for key in (
        "new_planning_searches",
        "new_control_replays",
        "new_controller_implementations",
    ):
        if summary[key] != 0:
            raise ValueError("Stage7A scope changed")
    papers = read_json(new / "literature_sources.json")["papers"]
    matrix = read_csv(new / "literature_matrix.csv")
    if len(papers) < 12 or {p["id"] for p in papers} != {p["id"] for p in matrix}:
        raise ValueError("Literature matrix is incomplete")
    if papers != matrix:
        raise ValueError("Literature CSV differs from its complete source descriptions")
    for paper in papers:
        for field in ("doi", "official_url", "full_text", "code_url", "license"):
            if not paper.get(field):
                raise ValueError(
                    f"Missing literature provenance: {paper['id']}/{field}"
                )
    for name in (
        "STAGE7A_REPORT_CN.md",
        "STAGE7A_LITERATURE_CN.md",
        "STAGE7A_INTERFACE_CONTRACT_CN.md",
        "STAGE7A_HYPOTHESIS_DECISION_CN.md",
        "STAGE7B_DRAFT_PROTOCOL_CN.md",
    ):
        if not (root / "docs" / name).is_file():
            raise FileNotFoundError(name)
    decision = read_json(new / "decision.json")
    if decision["decision"] != "PIVOT" or decision["stage7b_authorized"]:
        raise ValueError("Research decision or authorization boundary changed")
    return {
        "passed": True,
        "executions": 47,
        "failures": 15,
        "literature_items": len(papers),
        "private_raw_data_required_for_this_check": False,
        "new_trials_run_by_this_check": 0,
    }


if __name__ == "__main__":
    print(json.dumps(validate(PUBLIC.parents[1]), ensure_ascii=False))
