"""Complete fixed21 A/B/C/D reference-contract comparison with42 new replays."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT, read_config
from ..stage5a.tracking import Route
from ..stage5af import tracking
from ..stage6b.runner import exclusive_run
from ..stage6c.common import boolean, read_csv, read_json, saved_record, scenarios
from ..stage6c.reference import (
    certify_los,
    certify_reference,
    dense_reference,
    tail_reference,
    terminal_diagnostics,
)
from .common import PUBLIC, load_record, save_json, save_record
from .reference import geometry_equivalence, guidance_factory, subdivide


def metric_row(
    job: str,
    version: str,
    path: list,
    trace: list[dict[str, Any]],
    success: bool,
    reason: str,
    wall: float,
    planning: float,
) -> dict[str, Any]:
    """Separate saved historical timing from this round's measured intervals."""
    events = terminal_diagnostics(path, trace, 0.0)
    return {
        "job_id": job,
        "version": version,
        "native_M": True,
        "reference_geometry_safe": True,
        "LOS_success": success,
        "first_failure_reason": reason,
        "switch_arc": float(Route(path).cumulative[-1])
        - min(float(Route(path).lengths[-1]), 2.0)
        if version != "C"
        else max(0.0, float(Route(path).cumulative[-1]) - 2.0),
        "switch_time": events["switch_command_time_s"],
        "max_cross_track": max((r["cross_track_m"] for r in trace), default=0.0),
        "minimum_clearance": min(
            (r["mission_clearance_lower_bound_m"] for r in trace), default=None
        ),
        "wall_s": wall,
        "original_planning_charge_s": planning,
        "timing_source": "saved_historical"
        if version in ("A", "D")
        else "measured_stage6d",
        **events,
    }


def run(source: Path, previous: Path, local: Path, output: Path) -> dict[str, Any]:
    """Use every original strict path and never rerun historical A or D."""
    if (
        not read_json(output / "d0_audit.json")["passed"]
        or not read_json(output / "d1_acceptance.json")["passed"]
    ):
        raise RuntimeError("D0 and D1 correctness acceptance must pass first")
    original = [
        r
        for r in read_csv(ROOT / "results/stage6b/planning_runs.csv")
        if boolean(r["model_feasible"])
    ]
    if len(original) != 21:
        raise ValueError("All21 original paths are required")
    cases, rows, equivalents = scenarios(), [], []
    for old in original:
        job, case = old["job_id"], cases[old["scenario"]]
        archived = saved_record(source / "search" / job)
        d = load_record(previous / "c1" / job / "record.json.gz")
        a = dense_reference(case, archived["native_replay_trace"])
        b = subdivide(a)
        equivalence = geometry_equivalence(a, b)
        for path in (a, b, tail_reference(a)):
            if not certify_reference(path, case)["reference_geometry_safe"]:
                raise RuntimeError("Strict reference safety/equivalence gate failed")
        equivalents.append(
            {"job_id": job, **equivalence, "all_segment_certificates_safe": True}
        )
        planning = float(old["independent_certificate_finish_s"])
        rows.append(
            metric_row(
                job,
                "A",
                a,
                archived["los_trace"],
                boolean(old["los_strict_success"]),
                old["los_failure_reason"],
                float(old["tracking_and_adaptation_wall_s"]),
                planning,
            )
        )
        ds = d["summary"]
        rows.append(
            metric_row(
                job,
                "D",
                tail_reference(a),
                d["los_trace"],
                ds["adapted_los_success"],
                ds["adapted_failure_reason"],
                ds["adaptation_execution_and_audit_wall_s"],
                planning,
            )
        )
        for version, path in (("B", b), ("C", a)):
            folder = local / "d1" / job / version
            folder.mkdir(parents=True, exist_ok=False)
            started = time.perf_counter()
            certificate = certify_reference(path, case)
            if not certificate["reference_geometry_safe"]:
                raise RuntimeError("A pure reference intervention became unsafe")
            with guidance_factory(version == "C"):
                replay = tracking.simulate(
                    path,
                    case.scene,
                    read_config("stage5a_protocol.json"),
                    0.25,
                    read_config("stage5af_protocol.json"),
                    initial=case.initial,
                )
            audit = certify_los(replay.trace, case)
            wall = time.perf_counter() - started
            save_json(
                folder / "original_clock.json",
                {"execution_and_audit_s": wall},
                exclusive=True,
            )
            safe = audit["full_margin_safe"] and audit["goal_reached"]
            if replay.summary["execution_success"] and not safe:
                raise RuntimeError("LOS strict success is a safety false positive")
            success = bool(
                replay.summary["execution_success"]
                and wall <= 20
                and planning + wall <= 30
            )
            reason = (
                "execution_deadline"
                if wall > 20
                else "pipeline_deadline"
                if planning + wall > 30
                else replay.summary["failure_reason"]
            )
            row = metric_row(
                job, version, path, replay.trace, success, reason, wall, planning
            )
            rows.append(row)
            save_record(
                folder / "record.json.gz",
                {
                    "row": row,
                    "tracking": replay.summary,
                    "independent_los": audit,
                    "trace": replay.trace,
                    "reference_recipe": version,
                    "reference_not_duplicated": True,
                },
            )
            write_csv(output / "d1_results.csv", rows)
            print(
                json.dumps(
                    {"job": job, "version": version, "S": success, "reason": reason}
                ),
                flush=True,
            )
    write_csv(output / "d1_geometry_equivalence.csv", equivalents)
    result = {
        "passed": True,
        "source_paths": 21,
        "new_replays": 42,
        "new_searches": 0,
        "safety_false_positives": 0,
        "success_by_version": {
            v: sum(r["LOS_success"] for r in rows if r["version"] == v)
            for v in ("A", "B", "C", "D")
        },
    }
    save_json(output / "d1_summary.json", result)
    return result


def main() -> None:
    """Require explicit immutable source roots and a new6D record directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "previous-root", "local-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    with exclusive_run(args.local_root):
        print(
            json.dumps(
                run(args.source_root, args.previous_root, args.local_root, args.output)
            )
        )


if __name__ == "__main__":
    main()
