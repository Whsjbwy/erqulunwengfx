"""Independently recount frozen stage6B evidence before any stage6C search."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT, read_config
from ..stage6b.analysis import REQUIRED_FILES, check_request, compare
from ..stage6b.replay import audit_controls
from .common import (
    BASE,
    PUBLIC,
    boolean,
    read_csv,
    read_json,
    saved_record,
    scenarios,
    write_json,
)
from .reference import certify_los, certify_reference, dense_reference


def audit(local: Path, build_root: Path, output: Path) -> dict:
    """Recheck every actual input/output; never call a planner or write old records."""
    rows = read_csv(ROOT / "results/stage6b/planning_runs.csv")
    manifest = read_json(ROOT / "results/stage6b/search_manifest.json")
    sources = scenarios()
    ids = [row["job_id"] for row in rows]
    if len(ids) != 36 or len(set(ids)) != 36:
        raise ValueError("Stage6B requires exactly36 unique jobs")
    if {p.name for p in (local / "search").iterdir()} != set(ids):
        raise ValueError("Unregistered, missing or partial search directory")
    tasks = {task["job_id"]: task for task in manifest}
    checks = []
    intervals = los_intervals = 0
    for row in rows:
        folder = local / "search" / row["job_id"]
        if {p.name for p in folder.iterdir()} != REQUIRED_FILES:
            raise ValueError("Raw job has missing or extra files")
        source = sources[row["scenario"]]
        check_request(
            read_json(folder / "input.json"),
            tasks[row["job_id"]],
            source,
            read_config("stage6b_protocol.json"),
            local.resolve(),
        )
        payload = read_json(folder / "output.json")
        if payload["ompl_version"] != "2.0.2":
            raise ValueError("Unexpected official OMPL version")
        archived = read_json(folder / "condition_summary.json")
        for key in ("model_feasible", "was_run", "eligible", "los_strict_success"):
            if archived[key] != boolean(row[key]):
                raise ValueError(f"Raw summary and public CSV disagree: {key}")
        if payload["status"] != row["native_status"] or payload["seed"] != int(
            row["ompl_seed"]
        ):
            raise ValueError("Native status or seed differs from the archived CSV")
        fresh, trace = audit_controls(source, payload)
        if not fresh["independent_audit_passed"]:
            raise ValueError("Returned native trajectory failed independent audit")
        original = saved_record(folder)
        compare(original["native_replay_trace"], trace, row["job_id"] + ".native_trace")
        finish = float(row["independent_certificate_finish_s"])
        model = fresh["model_feasible"] and finish <= 10
        if model != boolean(row["model_feasible"]):
            raise ValueError("Model success/deadline differs from archived CSV")
        intervals += len(trace)
        reference_safe = None
        los_safe = None
        if model:
            path = dense_reference(source, trace)
            reference_safe = certify_reference(path, source)["reference_geometry_safe"]
            if not reference_safe:
                raise ValueError("Archived eligible reference is unsafe")
            los = certify_los(original["los_trace"], source)
            los_intervals += los["los_intervals"]
            los_safe = los["full_margin_safe"]
            if boolean(row["los_strict_success"]) and not (
                los_safe and los["goal_reached"]
            ):
                raise ValueError(
                    "Archived strict LOS success is a safety false positive"
                )
        checks.append(
            {
                "job_id": row["job_id"],
                "native_status": payload["status"],
                "model_feasible": model,
                "reference_geometry_safe": reference_safe,
                "los_full_margin_safe": los_safe,
                "audit_passed": True,
                "original_certificate_finish_s": finish,
            }
        )
        print(json.dumps({"audited": row["job_id"]}), flush=True)
    scope = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "4553d0f7e14207c92eb69dafd444cfdab395bcf7",
            BASE,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if len(scope) != 47 or any(not line.startswith("A\t") for line in scope):
        raise ValueError("PR10 scope differs from47 additions")
    build = read_json(build_root / "build_status.json")
    totals = {
        "K": len(rows),
        "M": sum(boolean(r["model_feasible"]) for r in rows),
        "E": sum(boolean(r["was_run"]) and boolean(r["eligible"]) for r in rows),
        "S": sum(boolean(r["los_strict_success"]) for r in rows),
    }
    if totals != {"K": 36, "M": 21, "E": 21, "S": 11}:
        raise ValueError("Unexpected frozen denominator")
    result = {
        "passed": True,
        "base_commit": BASE,
        "totals": totals,
        "status_counts": dict(Counter(r["native_status"] for r in rows)),
        "late_certificates": [
            r["job_id"] for r in rows if boolean(r["planning_deadline_rejected"])
        ],
        "native_reaudited_intervals": intervals,
        "saved_los_reaudited_intervals": los_intervals,
        "pr10_additions_only": len(scope),
        "native_version": "2.0.2",
        "actual_build_commands": len(build["commands"]),
        "actual_build_failures": sum(c["exit_code"] != 0 for c in build["commands"]),
        "tasks_are_not_independent_maps": True,
        "new_searches": 0,
        "new_los_executions": 0,
        "gitHub_verification": read_json(PUBLIC / "pr10_verification.json"),
    }
    write_csv(output / "c0_jobs.csv", checks)
    write_json(output / "c0_audit.json", result)
    return result


def main() -> None:
    """Audit read-only raw data, writing only new stage6C summaries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    print(json.dumps(audit(args.source_root, args.build_root, args.output)))


if __name__ == "__main__":
    main()
