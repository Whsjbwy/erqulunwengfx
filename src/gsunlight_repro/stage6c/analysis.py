"""Read-only final audit and descriptive tables for the complete6C records."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT, read_config
from ..stage5a.tracking import Route, State
from ..stage5af.guidance import TerminalLOS
from ..stage5ar.replay import control
from ..stage6b.analysis import REQUIRED_FILES, check_grid, compare
from ..stage6b.replay import audit_controls
from ..stage6b.scenarios import state_values
from .calibration import manifest, validate_events
from .common import (
    PUBLIC,
    boolean,
    read_csv,
    read_json,
    saved_record,
    scenarios,
    write_json,
)
from .recovery import JOB as LOST_CLOCK_JOB
from .reference import (
    certify_los,
    certify_reference,
    dense_reference,
    tail_reference,
    terminal_diagnostics,
)


def audit_commands(path: list, trace: list[dict[str, Any]]) -> None:
    """Recompute frozen commands at saved states, without a new plant simulation."""
    settings = read_config("stage5af_protocol.json")
    guidance = TerminalLOS(
        Route(path), settings["lookahead_m"], settings["terminal_distance_m"]
    )
    cfg = read_config("stage5a_protocol.json")["kinematics"]
    for index, row in enumerate(trace):
        state = State(
            tuple(row["start_position"]),
            row["start_yaw_rad"],
            row["start_pitch_rad"],
            1,
        )
        target, details = guidance.command(state, 0.1)
        if not np.allclose(target, row["target"], rtol=0, atol=1e-10):
            raise ValueError(f"Frozen LOS target differs at interval{index}")
        requested_yaw, requested_pitch, yaw, pitch = control(state, target, cfg)
        for key, value in (
            ("requested_yaw_rate_rad_s", requested_yaw),
            ("requested_pitch_rate_rad_s", requested_pitch),
            ("yaw_rate_rad_s", yaw),
            ("pitch_rate_rad_s", pitch),
        ):
            compare(row[key], value, f"inner_control.{index}.{key}")
        for key in (
            "reference_progress_m",
            "active_segment",
            "terminal_mode",
            "terminal_switch",
        ):
            compare(row[key], details[key], f"guidance.{index}.{key}")


def c1_analysis(source: Path, local: Path, output: Path, cases: dict) -> dict:
    """Check every fixed pair and all four outcomes including explicit zeroes."""
    pairs = read_csv(output / "c1_paired.csv")
    expected = {
        r["job_id"]
        for r in read_csv(ROOT / "results/stage6b/planning_runs.csv")
        if boolean(r["model_feasible"])
    }
    if {r["job_id"] for r in pairs} != expected or len(pairs) != 21:
        raise ValueError("C1 roster is incomplete or selected by outcome")
    counts = {
        name: 0 for name in ("kept_success", "regressed", "recovered", "kept_failure")
    }
    intervals = 0
    for row in pairs:
        record = saved_record(source / "search" / row["job_id"])
        case = cases[row["scenario"]]
        baseline = dense_reference(case, record["native_replay_trace"])
        adapted = tail_reference(baseline)
        import gzip

        with gzip.open(
            local / "c1" / row["job_id"] / "record.json.gz", "rt", encoding="utf-8"
        ) as stream:
            new = json.load(stream)
        if math.dist(new["anchor"], adapted[-2]) > 1e-10:
            raise ValueError("C1 adapter anchor changed")
        for path, trace in (
            (baseline, record["los_trace"]),
            (adapted, new["los_trace"]),
        ):
            geometry = certify_reference(path, case)
            if not geometry["reference_geometry_safe"]:
                raise ValueError("Declared safe reference failed independent check")
            certify_los(trace, case)
            audit_commands(path, trace)
            intervals += len(trace)
        old, changed = (
            boolean(row["baseline_los_success"]),
            boolean(row["adapted_los_success"]),
        )
        measured = new["summary"]
        strict_expected = bool(
            new["tracking"].get("execution_success", False)
            and measured["adaptation_execution_and_audit_wall_s"] <= 20
            and measured["pipeline_wall_s"] <= 30
        )
        if changed != strict_expected:
            raise ValueError("C1 strict clock/controller gate differs")
        outcome = (
            "kept_success"
            if old and changed
            else "regressed"
            if old
            else "recovered"
            if changed
            else "kept_failure"
        )
        if outcome != row["paired_outcome"]:
            raise ValueError("Paired label differs from strict success flags")
        counts[outcome] += 1
    write_csv(
        output / "c1_transition_counts.csv",
        [{"outcome": k, "count": v, "denominator": 21} for k, v in counts.items()],
    )
    result = {
        "pairs": 21,
        "transitions": counts,
        "baseline_S": 11,
        "adapted_S": counts["kept_success"] + counts["recovered"],
        "saved_los_intervals_audited": intervals,
        "new_searches": 0,
        "new_los_simulations": 0,
        "interpretation": (
            "Whole reference adaptation effect; no isolated terminal-time causal claim"
        ),
    }
    write_json(output / "c1_analysis.json", result)
    return result


def analyze(source: Path, local: Path, output: Path) -> dict:
    """Certify saved controls/commands only, then form complete-denominator tables."""
    cases = scenarios()
    c1 = c1_analysis(source, local, output, cases)
    tasks = manifest(read_config("stage6c_protocol.json"))
    rows = read_csv(output / "planning_runs.csv")
    if len(rows) != 72 or {r["job_id"] for r in rows} != {t["job_id"] for t in tasks}:
        raise ValueError("Calibration roster is not exactly the registered72")
    if {p.name for p in (local / "search").iterdir()} != {t["job_id"] for t in tasks}:
        raise ValueError("Extra, missing or partial calibration directory")
    task_by_id = {t["job_id"]: t for t in tasks}
    audits, executions, anytime = [], [], []
    native_intervals = first_intervals = los_intervals = 0
    known_clock_failures = []
    allowed = {
        "mode",
        "algorithm",
        "search_mode",
        "seed",
        "search_budget_s",
        "scenario",
        "selection_radius",
        "pruning_radius",
        "propagation_min_steps",
        "propagation_max_steps",
        "goal_bias",
    }
    for row in rows:
        folder = local / "search" / row["job_id"]
        if {p.name for p in folder.iterdir()} != REQUIRED_FILES:
            raise ValueError(
                "Calibration raw directory does not contain exactly six files"
            )
        raw, summary = (
            read_json(folder / "output.json"),
            read_json(folder / "condition_summary.json"),
        )
        for key, value in summary.items():
            if row[key] != ("" if value is None else str(value)):
                raise ValueError(
                    f"CSV differs from saved summary: {row['job_id']}.{key}"
                )
        task, case = task_by_id[row["job_id"]], cases[row["scenario"]]
        request = read_json(folder / "input.json")
        if set(request) != allowed or set(request["scenario"]) != {
            "id",
            "physical",
            "ceiling",
            "initial",
            "goal",
            "radius_m",
        }:
            raise ValueError("Unexpected planner input or hidden witness")
        expected_parameters = {
            "mode": "plan",
            "algorithm": task["algorithm"],
            "search_mode": task["mode"],
            "seed": task["seed"],
            "search_budget_s": 8.0,
            "selection_radius": task["selection_radius"],
            "pruning_radius": 0.1,
            "propagation_min_steps": 1,
            "propagation_max_steps": 50,
            "goal_bias": 0.05,
        }
        for key, value in expected_parameters.items():
            compare(request[key], value, row["job_id"] + ".request." + key)
        exported = request["scenario"]
        compare(exported["initial"], state_values(case.initial), "initial_state")
        compare(exported["goal"], list(case.scene.goal), "goal")
        check_grid(
            exported["physical"], case.scene.grid, case.physical_key, source.resolve()
        )
        if exported["ceiling"] is not None or raw["ompl_version"] != "2.0.2":
            raise ValueError("Wrong calibration map/version")
        saved = saved_record(folder)
        fresh, trace = audit_controls(case, raw)
        if not fresh["independent_audit_passed"]:
            raise ValueError("Native final path failed read-only re-audit")
        compare(saved["native_replay_trace"], trace, row["job_id"] + ".native_trace")
        native_intervals += len(trace)
        if raw.get("first_path") is not None:
            first, first_trace = audit_controls(
                case, {**raw["first_path"], "status": "exact"}
            )
            if not first["model_feasible"]:
                raise ValueError("First native incumbent failed independent re-audit")
            first_intervals += len(first_trace)
        events = raw["improvement_events"]
        costs = validate_events(events)
        clock = row["best_independent_certificate_finish_s"]
        model = bool(fresh["model_feasible"] and clock and float(clock) <= 10)
        if model != boolean(row["model_feasible"]):
            raise ValueError("Strict native model/clock gate differs")
        if not clock:
            if (
                row["job_id"] != LOST_CLOCK_JOB
                or row["failure_reason"]
                != "instrumentation_failed_missing_original_clock"
            ):
                raise ValueError("Unexpected missing clock")
            known_clock_failures.append(row["job_id"])
        if model and raw["status"] != "exact":
            raise ValueError("Approximate was promoted")
        if task["mode"] == "anytime":
            steps = [event["certificate_intervals"] for event in events]
            anytime.append(
                {
                    "job_id": row["job_id"],
                    "native_status": raw["status"],
                    "strict_model_success": model,
                    "clock_known": bool(clock),
                    "incumbent_updates_including_first_and_plateaus": len(steps),
                    "strict_control_cost_reductions": sum(
                        b < a for a, b in zip(steps[:-1], steps[1:], strict=True)
                    ),
                    "numerical_plateau_updates": sum(
                        b == a for a, b in zip(steps[:-1], steps[1:], strict=True)
                    ),
                    "first_native_cost_m": costs[0] if costs else None,
                    "best_native_cost_m": costs[-1] if costs else None,
                    "native_arc_reduction_m": (steps[0] - steps[-1]) * 0.1
                    if steps
                    else None,
                }
            )
        los = None
        tracking, observed = saved["tracking"], saved["los_trace"]
        execution_clock = summary["execution_and_independent_audit_wall_s"]
        strict_expected = bool(
            model
            and tracking["execution_success"]
            and execution_clock is not None
            and execution_clock <= 20
            and float(clock) + execution_clock <= 30
        )
        if strict_expected != boolean(row["los_strict_success"]):
            raise ValueError("C2 strict clock/controller gate differs")
        if boolean(row["los_was_run"]):
            path = dense_reference(case, trace)
            if not certify_reference(path, case)["reference_geometry_safe"]:
                raise ValueError("C2 eligible reference failed geometry certification")
            los = certify_los(observed, case)
            audit_commands(path, observed)
            los_intervals += len(observed)
            if boolean(row["los_strict_success"]) and not (
                los["full_margin_safe"] and los["goal_reached"]
            ):
                raise ValueError("C2 strict LOS safety false positive")
            execution = {
                "job_id": row["job_id"],
                "strict_success": boolean(row["los_strict_success"]),
                "full_margin_safe": los["full_margin_safe"],
                "simulated_arc_length_m": len(observed) * 0.1,
                "full_margin_certified_prefix_m": (
                    los["first_margin_interval"]
                    if los["first_margin_interval"] is not None
                    else len(observed)
                )
                * 0.1,
                "includes_final_candidate_interval": True,
                "yaw_saturation_steps": tracking["yaw_saturation_steps"],
                "pitch_saturation_steps": tracking["pitch_saturation_steps"],
                **terminal_diagnostics(
                    path, observed, tracking["reference_bridge_length_m"]
                ),
            }
            executions.append(execution)
        elif observed:
            raise ValueError("Unexecuted LOS condition contains a trace")
        audits.append(
            {
                "job_id": row["job_id"],
                "native_status": raw["status"],
                "independent_model_audit_passed": True,
                "native_intervals": len(trace),
                "strict_model_success": model,
                "clock_known": bool(clock),
                "saved_los_intervals": len(observed),
                "los_full_margin_safe": los["full_margin_safe"] if los else None,
                "maximum_rk4_error_m": fresh.get("maximum_rk4_error_m"),
            }
        )
    rates = []
    for name in dict.fromkeys(r["condition"] for r in rows):
        group = [r for r in rows if r["condition"] == name]
        m = sum(boolean(r["model_feasible"]) for r in group)
        e = sum(boolean(r["los_was_run"]) and boolean(r["los_eligible"]) for r in group)
        s = sum(boolean(r["los_strict_success"]) for r in group)
        lengths = [
            float(r["strict_best_certified_cost_m"])
            for r in group
            if boolean(r["model_feasible"])
        ]
        rates.append(
            {
                "condition": name,
                "K": len(group),
                "raw_exact": sum(r["native_status"] == "exact" for r in group),
                "M": m,
                "Gref": sum(r["reference_geometry_safe"] == "True" for r in group),
                "E": e,
                "S": s,
                "M_over_K": m / len(group),
                "S_over_E": s / e if e else None,
                "S_over_K": s / len(group),
                "missing_clock_failures": sum(
                    not r["best_independent_certificate_finish_s"] for r in group
                ),
                "late_certificates": sum(
                    r["planning_deadline_rejected"] == "True" for r in group
                ),
                "strict_cost_median_m": median(lengths) if lengths else None,
                "cost_denominator": len(lengths),
            }
        )
    paired = []
    index = {(r["scenario"], r["native_seed"], r["condition"]): r for r in rows}
    for label, a, b in (
        ("selection_radius", "sst_default_first", "sst_radius2_first"),
        ("anytime", "sst_radius2_first", "sst_radius2_anytime"),
    ):
        for case in read_config("stage6c_protocol.json")["c2"]["cases"]:
            for seed in ("1", "2", "3"):
                x, y = index[case, seed, a], index[case, seed, b]
                old, changed = (
                    boolean(x["model_feasible"]),
                    boolean(y["model_feasible"]),
                )
                paired.append(
                    {
                        "comparison": label,
                        "scenario": case,
                        "native_seed": seed,
                        "first_condition": a,
                        "second_condition": b,
                        "first_M": old,
                        "second_M": changed,
                        "outcome": "kept_success"
                        if old and changed
                        else "regressed"
                        if old
                        else "recovered"
                        if changed
                        else "kept_failure",
                        "first_S": boolean(x["los_strict_success"]),
                        "second_S": boolean(y["los_strict_success"]),
                        "first_cost_m": float(x["strict_best_certified_cost_m"])
                        if old
                        else None,
                        "second_cost_m": float(y["strict_best_certified_cost_m"])
                        if changed
                        else None,
                        "second_instrumentation_failure": y["failure_reason"]
                        == "instrumentation_failed_missing_original_clock",
                    }
                )
    write_csv(output / "rates.csv", rates)
    write_csv(output / "c2_paired_conditions.csv", paired)
    write_csv(output / "anytime_summary.csv", anytime)
    write_csv(output / "c2_execution_metrics.csv", executions)
    write_csv(output / "c2_raw_audit.csv", audits)
    write_csv(
        output / "failure_counts.csv",
        [
            {"failure_reason": k, "count": v, "denominator": 72}
            for k, v in Counter(r["failure_reason"] for r in rows).items()
        ],
    )
    result = {
        "passed": True,
        "C1": c1,
        "registered_C2": 72,
        "actual_C2_directories": len(audits),
        "native_returned_intervals": native_intervals,
        "additional_distinct_first_path_intervals": first_intervals,
        "saved_C2_LOS_intervals": los_intervals,
        "native_status_counts": dict(Counter(r["native_status"] for r in rows)),
        "known_original_clock_failures": known_clock_failures,
        "rates": rates,
        "C2_primary_failures": dict(Counter(r["failure_reason"] for r in rows)),
        "C2_los_full_margin_violations": sum(
            not r["full_margin_safe"] for r in executions
        ),
        "maximum_native_rk4_error_m": max(
            r["maximum_rk4_error_m"] or 0 for r in audits
        ),
        "safety_false_positives": 0,
        "new_searches": 0,
        "new_plant_simulations": 0,
        "development_map_clusters": 1,
        "independent_holdout_maps_generated": 0,
        "raw_root_stop_records": [p.name for p in local.glob("stopped-*.json")],
        "confidence_scope": (
            "Descriptive paired development evidence only; six analytic tasks "
            "share one empty grid, so no map-level generalization "
            "CI/significance claim"
        ),
    }
    write_json(output / "final_trace_audit.json", result)
    return result


def main() -> None:
    """Require all original records and never call solve or simulate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    result = analyze(args.source_root, args.local_root, args.output)
    print(json.dumps({k: v for k, v in result.items() if k not in ("C1", "rates")}))


if __name__ == "__main__":
    main()
