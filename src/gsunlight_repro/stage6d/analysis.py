"""Read-only audit of every reference condition and explicit blocked denominators."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT, read_config
from ..stage5a.tracking import Route, State
from ..stage5af.guidance import TerminalLOS
from ..stage5ar.replay import control
from ..stage6c.common import boolean, read_csv, read_json, saved_record, scenarios
from ..stage6c.reference import certify_los, dense_reference, tail_reference
from .common import PUBLIC, load_record, outcome, save_json
from .maps import build_scenarios, roster
from .reference import ArcTerminalLOS, geometry_equivalence, subdivide


def audit_commands(path: list, trace: list[dict[str, Any]], version: str) -> None:
    """Recompute guidance and inner controls at saved states, without a new plant."""
    settings = read_config("stage5af_protocol.json")
    cls = ArcTerminalLOS if version == "C" else TerminalLOS
    guide = cls(Route(path), settings["lookahead_m"], settings["terminal_distance_m"])
    cfg = read_config("stage5a_protocol.json")["kinematics"]
    for row in trace:
        state = State(
            tuple(row["start_position"]),
            row["start_yaw_rad"],
            row["start_pitch_rad"],
            1.0,
        )
        target, details = guide.command(state, 0.1)
        requested_yaw, requested_pitch, yaw, pitch = control(state, target, cfg)
        if not np.allclose(target, row["target"], rtol=0, atol=1e-10):
            raise RuntimeError(
                "Saved guidance target differs from the declared variant"
            )
        for key in (
            "reference_progress_m",
            "active_segment",
            "terminal_mode",
            "terminal_switch",
        ):
            if not np.isclose(details[key], row[key], rtol=0, atol=1e-10):
                raise RuntimeError("Saved guidance details differ")
        for key, value in (
            ("requested_yaw_rate_rad_s", requested_yaw),
            ("requested_pitch_rate_rad_s", requested_pitch),
            ("yaw_rate_rad_s", yaw),
            ("pitch_rate_rad_s", pitch),
        ):
            if abs(row[key] - value) > 1e-12:
                raise RuntimeError("Saved frozen inner-loop control differs")


def d1_sources(source: Path, previous: Path, local: Path) -> list[dict[str, Any]]:
    """Retrieve every A/B/C/D trace without copying historical numeric files."""
    cases, result = scenarios(), []
    for old in read_csv(ROOT / "results/stage6b/planning_runs.csv"):
        if not boolean(old["model_feasible"]):
            continue
        job, case = old["job_id"], cases[old["scenario"]]
        a = saved_record(source / "search" / job)
        d = load_record(previous / "c1" / job / "record.json.gz")
        path = dense_reference(case, a["native_replay_trace"])
        b = load_record(local / "d1" / job / "B/record.json.gz")
        c = load_record(local / "d1" / job / "C/record.json.gz")
        result.append(
            {
                "job": job,
                "case": case,
                "paths": {
                    "A": path,
                    "B": subdivide(path),
                    "C": path,
                    "D": tail_reference(path),
                },
                "traces": {
                    "A": a["los_trace"],
                    "B": b["trace"],
                    "C": c["trace"],
                    "D": d["los_trace"],
                },
                "new": {"B": b, "C": c},
            }
        )
    if len(result) != 21:
        raise RuntimeError("D1 source denominator is not21")
    return result


def run(source: Path, previous: Path, local: Path, output: Path) -> dict[str, Any]:
    """Audit saved execution and keep all54 unexecuted searches explicitly missing."""
    rows = read_csv(output / "d1_results.csv")
    if len(rows) != 84 or len({(r["job_id"], r["version"]) for r in rows}) != 84:
        raise RuntimeError("D1 four-version roster is incomplete")
    indexed = {(r["job_id"], r["version"]): r for r in rows}
    pairs, audits, intervals, failures = [], [], 0, []
    for data in d1_sources(source, previous, local):
        job = data["job"]
        geometry_equivalence(data["paths"]["A"], data["paths"]["B"])
        if data["paths"]["A"] != data["paths"]["C"]:
            raise RuntimeError("C changed the original reference vertices")
        for version, path in data["paths"].items():
            trace = data["traces"][version]
            audit_commands(path, trace, version)
            audit = certify_los(trace, data["case"])
            row = indexed[job, version]
            success = boolean(row["LOS_success"])
            if not success:
                first = next(
                    (
                        r
                        for r in trace
                        if r["margin_reason"] != "ok"
                        or r["mission_reason"] != "ok"
                        or r["physical_reason"] != "ok"
                        or r["cross_track_m"] > 3.0
                    ),
                    None,
                )
                failures.append(
                    {
                        "phase": "D1_LOS",
                        "job_id": job,
                        "version": version,
                        "reason": row["first_failure_reason"],
                        "interval_start_s": first["time_start_s"] if first else None,
                        "interval_end_s": first["time_s"] if first else None,
                        "candidate_position": first["position"] if first else None,
                        "candidate_is_exact_collision_instant": False,
                    }
                )
            if success and not (audit["full_margin_safe"] and audit["goal_reached"]):
                raise RuntimeError("Strict LOS success is a safety false positive")
            if version in ("B", "C"):
                record = data["new"][version]
                clock = read_json(local / "d1" / job / version / "original_clock.json")
                wall = clock["execution_and_audit_s"]
                expected = bool(
                    record["tracking"]["execution_success"]
                    and wall <= 20
                    and wall + float(row["original_planning_charge_s"]) <= 30
                )
                if expected != success or wall != float(row["wall_s"]):
                    raise RuntimeError("D1 actual timing/strict result differs")
            intervals += len(trace)
            audits.append(
                {
                    "job_id": job,
                    "version": version,
                    "audit_passed": True,
                    "intervals": len(trace),
                    "strict_success": success,
                    "required_margin_lower_bound_m": float(row["minimum_clearance"])
                    - 0.25,
                    "first_margin_interval": audit["first_margin_interval"],
                }
            )
        a = indexed[job, "A"]
        for version in ("B", "C", "D"):
            other = indexed[job, version]
            first_difference = next(
                (
                    i
                    for i, (x, y) in enumerate(
                        zip(data["traces"]["A"], data["traces"][version], strict=False)
                    )
                    if math.dist(x["position"], y["position"]) > 1e-10
                ),
                None,
            )
            pairs.append(
                {
                    "job_id": job,
                    "comparison": "A_" + version,
                    "before_success": boolean(a["LOS_success"]),
                    "after_success": boolean(other["LOS_success"]),
                    "outcome": outcome(
                        boolean(a["LOS_success"]), boolean(other["LOS_success"])
                    ),
                    "first_position_difference_time_s": first_difference * 0.1
                    if first_difference is not None
                    else None,
                    "before_failure": a["first_failure_reason"],
                    "after_failure": other["first_failure_reason"],
                }
            )
    write_csv(output / "d1_pairs.csv", pairs)
    write_csv(output / "d1_trace_audit.csv", audits)
    counts = {
        name: {
            kind: sum(r["comparison"] == name and r["outcome"] == kind for r in pairs)
            for kind in ("kept_success", "regressed", "recovered", "kept_failure")
        }
        for name in ("A_B", "A_C", "A_D")
    }
    failure = read_json(output / "model_mapping_failure.json")
    failures.append(
        {
            "phase": "D2_witness_mapping",
            "job_id": "terrain_1",
            "version": "native_SI",
            "reason": "pitch_predicate_mismatch",
            "interval_start_s": failure["time_start_s"],
            "interval_end_s": failure["time_start_s"] + 0.1,
            "candidate_position": failure["candidate_state"][:3],
            "candidate_is_exact_collision_instant": False,
        }
    )
    write_csv(output / "failure_locations.csv", failures)
    counts_by_reason = Counter(
        (r["version"], r["first_failure_reason"], boolean(r["LOS_success"]))
        for r in rows
    )
    write_csv(
        output / "d1_outcome_counts.csv",
        [
            {
                "version": key[0],
                "reason": key[1],
                "strict_success": key[2],
                "count": count,
            }
            for key, count in sorted(counts_by_reason.items())
        ],
    )
    if failure["model_mapping_gate_passed"]:
        raise RuntimeError("Blocked-stage analysis requires the actual failed gate")
    search = local / "search"
    if search.exists() and list(search.iterdir()):
        raise RuntimeError("Unexpected planning after the blocked gate")
    tasks = roster(read_config("stage6d_protocol.json"))
    write_csv(
        output / "d2_registered_not_run.csv",
        [
            {
                **task,
                "execution_status": "not_run_blocked_model_mapping",
                "actual_attempt": False,
                "native_M": None,
                "LOS_success": None,
                "planning_wall_s": None,
            }
            for task in tasks
        ],
    )
    witnesses = {r["map"]: r for r in read_csv(output / "d2_witnesses.csv")}
    statuses = [
        {
            "map": case.id,
            "family": case.scene.specification["family"],
            "registered": True,
            "occupied_voxels": int(case.scene.grid.occupancy.sum()),
            "status": "native_and_independent_passed"
            if case.id in witnesses
            else "native_interface_exception"
            if case.id == "terrain_1"
            else "not_run_after_stop",
            "native_attempted": case.id in witnesses or case.id == "terrain_1",
            "joint_certified_witness": case.id in witnesses,
        }
        for case in build_scenarios()
    ]
    write_csv(output / "d2_witness_status.csv", statuses)
    accounting = {
        "registered": 54,
        "actually_started": 0,
        "actually_completed": 0,
        "M": None,
        "E": 0,
        "S": None,
        "M_over_K": None,
        "reason": "BLOCKED: frozen model/SI pitch predicates differ",
        "witness_registered": 6,
        "witness_native_attempted": 5,
        "witness_joint_passed": 4,
        "witness_native_exception": 1,
        "witness_not_run": 1,
        "no_rerun_or_seed_selection": True,
    }
    save_json(output / "d2_accounting.json", accounting)
    save_json(
        output / "d2_witness_acceptance.json",
        {
            "passed": False,
            "registered": 6,
            "joint_passed": 4,
            "native_exception": 1,
            "not_run_after_stop": 1,
            "reason": "Actual SI and frozen model pitch predicates disagree",
            "searches_started": 0,
        },
    )
    summary = {
        "decision": "BLOCKED",
        "d1_conditions": 84,
        "d1_new_replays": 42,
        "d1_audited_intervals": intervals,
        "d1_pairs": counts,
        "new_planning_searches": 0,
        "safety_false_positives": 0,
        "model_mapping_gate_passed": False,
        "d2": accounting,
    }
    save_json(output / "analysis_summary.json", summary)
    return summary


def main() -> None:
    """Read existing records only, without solve or a new plant simulation."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "previous-root", "local-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.source_root, args.previous_root, args.local_root, args.output)
        )
    )


if __name__ == "__main__":
    main()
