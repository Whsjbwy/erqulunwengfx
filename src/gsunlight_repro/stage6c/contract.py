"""Paired replay of all21 frozen native paths with one terminal adapter."""

from __future__ import annotations

import argparse
import gzip
import json
import time
from collections import Counter
from pathlib import Path

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT, read_config
from ..stage5af.tracking import simulate
from .common import (
    PUBLIC,
    boolean,
    read_csv,
    read_json,
    saved_record,
    scenarios,
    write_json,
)
from .reference import (
    certify_los,
    certify_reference,
    dense_reference,
    tail_reference,
    terminal_diagnostics,
)


def run(source_root: Path, local_root: Path, output: Path) -> dict:
    """Keep archived baseline traces and write exactly one new variant per source."""
    if not read_json(output / "c0_audit.json")["passed"]:
        raise ValueError("C0 audit must pass first")
    if not read_json(output / "c1_acceptance_checks.json")["passed"]:
        raise ValueError("Analytical/safety acceptance must pass before replay")
    if local_root.resolve().is_relative_to(ROOT):
        raise ValueError("Full traces must remain outside the repository")
    rows = [
        r
        for r in read_csv(ROOT / "results/stage6b/planning_runs.csv")
        if boolean(r["model_feasible"])
    ]
    if len(rows) != 21:
        raise ValueError("C1 must include all21 original strict native paths")
    cases = scenarios()
    paired, diagnostics = [], []
    for old in rows:
        folder = local_root / "c1" / old["job_id"]
        folder.mkdir(parents=True, exist_ok=False)
        case = cases[old["scenario"]]
        started = time.perf_counter()
        stored = saved_record(source_root / "search" / old["job_id"])
        baseline = dense_reference(case, stored["native_replay_trace"])
        adapted = tail_reference(baseline)
        geometry = certify_reference(adapted, case)
        geometry_finished = time.perf_counter() - started
        trace, summary = [], {}
        independent = None
        was_run = geometry["reference_geometry_safe"]
        if was_run:
            replay = simulate(
                adapted,
                case.scene,
                read_config("stage5a_protocol.json"),
                0.25,
                read_config("stage5af_protocol.json"),
                corrected=True,
                initial=case.initial,
            )
            summary, trace = replay.summary, replay.trace
        execution_finished = time.perf_counter() - started
        if was_run:
            independent = certify_los(trace, case)
            if summary["execution_success"] and not (
                independent["full_margin_safe"] and independent["goal_reached"]
            ):
                raise ValueError("New strict LOS success is a safety false positive")
        audit_wall = time.perf_counter() - started - execution_finished
        planning_charge = float(old["independent_certificate_finish_s"])
        new_success = bool(
            was_run
            and summary["execution_success"]
            and execution_finished <= 20
            and planning_charge + execution_finished <= 30
        )
        old_success = boolean(old["los_strict_success"])
        outcome = (
            "kept_success"
            if old_success and new_success
            else "regressed"
            if old_success
            else "recovered"
            if new_success
            else "kept_failure"
        )
        reason = (
            "interface_rejected_" + geometry["reference_rejection"]
            if not was_run
            else "execution_deadline"
            if execution_finished > 20
            else "pipeline_deadline"
            if planning_charge + execution_finished > 30
            else summary["failure_reason"]
        )
        bridge = float(old["reference_bridge_length_m"])
        row = {
            "job_id": old["job_id"],
            "scenario": old["scenario"],
            "algorithm": old["algorithm"],
            "ompl_seed": int(old["ompl_seed"]),
            "data_role": "development",
            "native_model_feasible": True,
            "baseline_reference_safe": True,
            "adapted_reference_safe": was_run,
            "baseline_los_success": old_success,
            "adapted_los_was_run": was_run,
            "adapted_los_success": new_success,
            "paired_outcome": outcome,
            "baseline_failure_reason": old["los_failure_reason"],
            "adapted_failure_reason": reason,
            **geometry,
            "reference_geometry_finish_s": geometry_finished,
            "adaptation_and_execution_wall_s": execution_finished,
            "posthoc_los_audit_wall_s": audit_wall,
            "original_planning_charge_s": planning_charge,
            "pipeline_wall_s": planning_charge + execution_finished,
            "baseline_simulation_limit_s": stored["tracking"]["simulation_limit_s"],
            "adapted_simulation_limit_s": summary.get("simulation_limit_s"),
            "goal_bridge_length_m": bridge,
        }
        paired.append(row)
        for variant, path, observed in (
            ("baseline", baseline, stored["los_trace"]),
            ("tail_arc_2m_v1", adapted, trace),
        ):
            diagnostics.append(
                {
                    "job_id": old["job_id"],
                    "variant": variant,
                    **terminal_diagnostics(path, observed, bridge),
                }
            )
        record = {
            "source_job_id": old["job_id"],
            "adapter": "tail_arc_2m_v1",
            "summary": row,
            "tracking": summary,
            "independent_los": independent,
            "los_trace": trace,
            "anchor": adapted[-2],
            "reference_is_native_control": False,
        }
        with gzip.open(folder / "record.json.gz", "xt", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False)
        print(
            json.dumps({"job_id": old["job_id"], "outcome": outcome, "reason": reason}),
            flush=True,
        )
    outcomes = dict(Counter(r["paired_outcome"] for r in paired))
    result = {
        "passed": True,
        "source_paths": 21,
        "native_M": 21,
        "baseline_Gref": 21,
        "baseline_E": 21,
        "baseline_S": 11,
        "adapted_Gref": sum(r["adapted_reference_safe"] for r in paired),
        "adapted_E": sum(r["adapted_los_was_run"] for r in paired),
        "adapted_S": sum(r["adapted_los_success"] for r in paired),
        "paired_outcomes": outcomes,
        "safety_false_positives": 0,
        "new_searches": 0,
        "new_los_executions": sum(r["adapted_los_was_run"] for r in paired),
        "c2_gate_passed": True,
        "c2_gate_scope": (
            "Safety and deterministic interface audit passed. Native M/cost is "
            "primary; frozen dense+bridge LOS remains secondary with its "
            "measured representation limitations."
        ),
        "causal_scope": (
            "Whole tail-reference representation, including tangent, projection, "
            "last-edge and path-length-dependent simulation horizon. "
            "Not isolated terminal-switch timing causality."
        ),
    }
    write_csv(output / "c1_paired.csv", paired)
    write_csv(output / "c1_terminal_events.csv", diagnostics)
    write_json(output / "c1_summary.json", result)
    return result


def main() -> None:
    """Replay the fixed roster only after C0 and real test evidence pass."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    print(json.dumps(run(args.source_root, args.local_root, args.output)))


if __name__ == "__main__":
    main()
