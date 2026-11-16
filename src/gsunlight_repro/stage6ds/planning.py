"""Execute only the original54 jobs, reusing frozen timing/audit/LOS semantics."""

from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT
from ..stage6b.runner import exclusive_run
from ..stage6c.calibration import available_memory
from ..stage6c.common import read_json
from ..stage6d.common import save_json
from ..stage6d.maps import build_scenarios
from ..stage6d.planning import run_one
from ..stage6dr.acceptance import validate_policy
from ..stage6dr.cases import export_scene
from . import BINARY_ID, PUBLIC
from .protocol import check_identity, frozen, request_for


def ledger(
    tasks: list[dict[str, Any]], completed: dict[str, dict[str, Any]]
) -> list[dict]:
    """Keep every denominator; not-run measurements are null, never fake failures."""
    result = []
    for task in tasks:
        base = {
            "job_id": task["job_id"],
            "scenario": task["scenario"],
            "condition": task["id"],
            "algorithm": task["algorithm"],
            "native_seed": task["seed"],
            "search_mode": task["mode"],
            "run_state": "not_run",
            "model_feasible": None,
            "los_strict_success": None,
            "failure_reason": "not_run",
        }
        result.append({**base, **completed.get(task["job_id"], {})})
    fields = list(dict.fromkeys(key for row in result for key in row))
    return [{key: row.get(key) for key in fields} for row in result]


def resource_check(folder: Path, row: dict[str, Any], cfg: dict[str, Any]) -> dict:
    """Check actual process RSS and all files of every completed job."""
    size = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
    peak = row["peak_native_rss_bytes"]
    if not isinstance(peak, int) or not 0 < peak <= cfg["maximum_native_rss_bytes"]:
        raise RuntimeError("Actual process RSS resource gate failed")
    if size > cfg["maximum_job_record_bytes"]:
        raise RuntimeError("Single-job raw evidence size resource gate failed")
    return {"peak_native_rss_bytes": peak, "record_bytes": size}


def audit_completed(
    task: dict[str, Any],
    request: dict[str, Any],
    folder: Path,
    row: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Read original measurements; never rerun or replace a partial invocation."""
    if read_json(folder / "input.json") != request:
        raise RuntimeError("Saved request differs from the inherited exact task")
    native = read_json(folder / "output.json")
    if native["seed"] != task["seed"] or native["algorithm"] != task["algorithm"]:
        raise RuntimeError("Measured native seed/algorithm differs")
    check_identity(native["identity"], task)
    validate_policy(native)
    if native["binary_id"] != BINARY_ID:
        raise RuntimeError("Actual search did not use the new planner binary")
    clock = read_json(folder / "native_clock.json")
    certificates = read_json(folder / "certificate_clock.json")
    finish = certificates["final_independent_finish_s"]
    first = certificates["first_independent_finish_s"]
    native_finish = native["native_certificate_finish_s"]
    if (
        clock["return_code"] != 0
        or not 0 <= native["candidate_return_s"] <= native_finish
        or not 0
        < clock["bridge_total_wall_s"]
        <= clock["observed_return_elapsed_s"]
        <= finish
        or native_finish > clock["native_process_wall_s"] + 0.1
        or (
            first is not None
            and not clock["observed_return_elapsed_s"] <= first <= finish
        )
        or row["best_independent_certificate_s"] != finish
        or row["model_feasible"] != bool(row["native_M_before_budget"] and finish <= 10)
    ):
        raise RuntimeError("Original clocks/model deadline are missing or inconsistent")
    event_times = [
        event["native_certificate_finish_s"] for event in native["improvement_events"]
    ]
    if any(
        a > b for a, b in zip(event_times[:-1], event_times[1:], strict=True)
    ) or any(not 0 <= t <= native_finish for t in event_times):
        raise RuntimeError("Native incumbent clocks are inconsistent")
    resource = resource_check(folder, row, cfg["resource_gate"])
    return {
        **row,
        "run_state": "completed",
        "adapter_id": native["adapter"]["adapter_id"],
        "binary_id": BINARY_ID,
        "official_class": native["identity"]["official_class"],
        "actual_planner_identity_passed": True,
        "raw_status": native["raw_status"],
        "native_certificate_finish_s": native_finish,
        "returned_state_count": len(native["states"]),
        "returned_control_count": len(native["controls"]),
        "improvement_event_count": len(event_times),
        **resource,
    }


def run(
    executable: Path,
    dependency: Path,
    acceptance: Path,
    quality: Path,
    local: Path,
    references: list[Path],
    *,
    pilot_only: bool,
) -> dict[str, Any]:
    """Stop on hard inconsistencies; pilot outcome never selects seeds or maps."""
    if local.resolve().is_relative_to(ROOT):
        raise ValueError("Raw54-job evidence must remain outside Git")
    cfg, tasks = frozen()
    if (local / "blocked.json").exists() or (PUBLIC / "blocked.json").exists():
        raise RuntimeError("A hard stop exists; do not resume or retry searches")
    gate = read_json(acceptance / "acceptance_summary.json")
    checks = read_json(quality / "head-evidence.json")
    if not (
        gate["passed"]
        and gate["binary_id"] == BINARY_ID
        and gate["map_accepted_intervals"] == 2440
        and gate["planner_identity_checks"] == 3
        and checks["engineering_checks_passed"]
        and checks["new_model_interface_passed"]
    ):
        raise RuntimeError("P0/P1 engineering and real planner acceptance must pass")
    if not pilot_only and not read_json(PUBLIC / "pilot_review.json")["passed"]:
        raise RuntimeError(
            "Three original pilot records must be reviewed before the other51"
        )
    cases = {c.id: c for c in build_scenarios()}
    scenes = {
        name: export_scene(case, references, local / "grids")
        for name, case in cases.items()
    }
    completed = {}
    write_csv(PUBLIC / "planning_runs.csv", ledger(tasks, completed))
    start = time.perf_counter()
    for task in tasks[:3] if pilot_only else tasks:
        folder = local / "search" / task["job_id"]
        request = request_for(task, scenes[task["scenario"]])
        try:
            summary = folder / "condition_summary.json"
            if summary.exists():
                row = read_json(summary)
            else:
                if folder.exists():
                    raise RuntimeError("Partial original job exists; never retry it")
                ram = available_memory()
                if ram < cfg["resource_gate"]["minimum_available_ram_bytes"]:
                    raise RuntimeError("Available physical RAM resource gate failed")
                row = run_one(
                    task,
                    cases[task["scenario"]],
                    request,
                    executable,
                    dependency,
                    folder,
                )
            row = audit_completed(task, request, folder, row, cfg)
            completed[task["job_id"]] = row
            write_csv(PUBLIC / "planning_runs.csv", ledger(tasks, completed))
            print(
                json.dumps(
                    {
                        "job": task["job_id"],
                        "status": row["native_status"],
                        "M": row["model_feasible"],
                        "S": row["los_strict_success"],
                        "planning_s": row["best_independent_certificate_s"],
                    }
                ),
                flush=True,
            )
        except Exception:
            failure = {
                "failed_job": task["job_id"],
                "error": traceback.format_exc(),
                "completed": len(completed),
                "registered": 54,
                "decision": "BLOCKED",
                "no_retry": True,
            }
            completed[task["job_id"]] = {
                "run_state": "exception",
                "failure_reason": "hard_consistency_or_resource_stop",
            }
            write_csv(PUBLIC / "planning_runs.csv", ledger(tasks, completed))
            save_json(local / "blocked.json", failure, exclusive=True)
            save_json(PUBLIC / "blocked.json", failure, exclusive=True)
            raise
    if pilot_only:
        review = {
            "passed": True,
            "jobs": [task["job_id"] for task in tasks[:3]],
            "identity_safety_clocks_resources_passed": True,
            "success_count_is_not_a_gate": True,
            "resources": [
                {
                    "job_id": k,
                    "peak_native_rss_bytes": v["peak_native_rss_bytes"],
                    "record_bytes": v["record_bytes"],
                }
                for k, v in completed.items()
            ],
            "completed_searches": 3,
        }
        save_json(PUBLIC / "pilot_review.json", review, exclusive=True)
    result = {
        "registered": 54,
        "completed": len(completed),
        "complete": len(completed) == 54,
        "pilot_reused": not pilot_only,
        "batch_wall_s": time.perf_counter() - start,
        "M": sum(r["model_feasible"] for r in completed.values()),
        "S": sum(r["los_strict_success"] for r in completed.values()),
    }
    save_json(
        PUBLIC / ("pilot_accounting.json" if pilot_only else "accounting.json"), result
    )
    return result


def main() -> None:
    """Use explicit roots and an exclusive batch lock for original measurements."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "executable",
        "dependency-root",
        "acceptance-root",
        "quality-root",
        "local-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--grid-reference", type=Path, action="append", default=[])
    parser.add_argument("--pilot-only", action="store_true")
    args = parser.parse_args()
    with exclusive_run(args.local_root):
        print(
            json.dumps(
                run(
                    args.executable,
                    args.dependency_root,
                    args.acceptance_root,
                    args.quality_root,
                    args.local_root,
                    args.grid_reference,
                    pilot_only=args.pilot_only,
                )
            )
        )


if __name__ == "__main__":
    main()
