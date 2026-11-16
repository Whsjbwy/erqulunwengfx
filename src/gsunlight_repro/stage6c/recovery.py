"""Recover one preserved pilot as a timing failure, never as a new success."""

from __future__ import annotations

import argparse
import gzip
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from ..stage6b.replay import audit_controls
from ..stage6b.scenarios import analytic_scenarios
from .calibration import available_memory, validate_events
from .common import PUBLIC, read_json, write_json

JOB = "straight--sst_radius2_anytime--seed1"


def recover(local: Path, output: Path) -> dict:
    """Retain missing original clock as null and strict M/S as false."""
    folder = local / "search" / JOB
    target = folder / "condition_summary.json"
    if target.exists():
        raise FileExistsError("The preserved pilot must not be rewritten")
    started = time.perf_counter()
    payload = read_json(folder / "output.json")
    source = next(s for s in analytic_scenarios() if s.id == "straight")
    first, _ = audit_controls(source, {**payload["first_path"], "status": "exact"})
    last, trace = audit_controls(source, payload)
    if not first["model_feasible"] or not last["model_feasible"]:
        raise ValueError("Pilot model/safety mismatch: do not expand")
    costs = validate_events(payload["improvement_events"])
    template = read_json(
        local / "search/straight--rrt_first--seed1/condition_summary.json"
    )
    row = {key: None for key in template}
    row.update(
        job_id=JOB,
        scenario="straight",
        condition="sst_radius2_anytime",
        algorithm="sst",
        search_mode="anytime",
        native_seed=1,
        data_role="development",
        selection_radius=2.0,
        pruning_radius=0.1,
        native_status=payload["status"],
        raw_status=payload["raw_status"],
        model_feasible_before_deadline=True,
        model_feasible=False,
        planning_deadline_rejected=None,
        first_native_certificate_s=payload["improvement_events"][0][
            "native_certificate_finish_s"
        ],
        candidate_return_s=payload["candidate_return_s"],
        native_certificate_finish_s=payload["native_certificate_finish_s"],
        first_native_cost_m=costs[0],
        raw_returned_arc_length_m=sum(u["duration_s"] for u in payload["controls"]),
        improvement_events=len(costs),
        propagated_intervals=payload["propagated_intervals"],
        collision_queries=payload["collision_queries"],
        box_distance_tests=payload["box_distance_tests"],
        peak_native_rss_bytes=payload["peak_native_rss_bytes"],
        maximum_rk4_error_m=last["maximum_rk4_error_m"],
        minimum_gap_lower_bound_m=last["minimum_gap_lower_bound_m"],
        los_was_run=False,
        los_eligible=False,
        los_strict_success=False,
        los_failure_reason="not_run_instrumentation_failure",
        failure_reason="instrumentation_failed_missing_original_clock",
        return_code=0,
    )
    recovery = {
        "job_id": JOB,
        "original_clock_available": False,
        "searches_reexecuted": 0,
        "los_executions": 0,
        "posthoc_recovery_utc": datetime.now(UTC).isoformat(),
        "posthoc_recovery_wall_s": time.perf_counter() - started,
        "first_and_final_independent_model_certificates": True,
        "original_strict_M": False,
        "original_strict_S": False,
        "cost_events_integer_nonincreasing": True,
        "available_memory_bytes": available_memory(),
    }
    with gzip.open(
        folder / "independent_record.json.gz", "xt", encoding="utf-8"
    ) as stream:
        json.dump(
            {
                "first_audit": first,
                "audit": last,
                "native_replay_trace": trace,
                "tracking": {
                    "was_run": False,
                    "eligible": False,
                    "execution_success": False,
                },
                "los_audit": None,
                "los_trace": [],
                "recovery": recovery,
            },
            stream,
            ensure_ascii=False,
            allow_nan=False,
        )
    write_json(target, row)
    resources = [
        {
            "job_id": p.name,
            "rss_bytes": read_json(p / "output.json")["peak_native_rss_bytes"],
            "record_bytes": sum(f.stat().st_size for f in p.iterdir() if f.is_file()),
        }
        for p in sorted((local / "search").iterdir())
    ]
    if len(resources) != 4 or any(
        r["rss_bytes"] > 2**30 or r["record_bytes"] > 5 * 2**20 for r in resources
    ):
        raise ValueError("Pilot resources do not satisfy preregistration")
    recovery.update(resource_pilots=resources, resource_gate_passed=True)
    write_json(output / "c2_pilot_recovery.json", recovery)
    return recovery


def main() -> None:
    """One-time evidence recovery; the source controls and outputs remain read-only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    print(json.dumps(recover(args.local_root, args.output)))


if __name__ == "__main__":
    main()
