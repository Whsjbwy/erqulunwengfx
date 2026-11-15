"""Serial preregistered first-solution/anytime calibration of official trees."""

from __future__ import annotations

import argparse
import ctypes
import gzip
import json
import random
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..stage5a.analysis import write_csv
from ..stage5a.maps import read_config
from ..stage6b.bridge import invoke_native
from ..stage6b.replay import audit_controls, track_reference
from ..stage6b.runner import exclusive_run
from ..stage6b.scenarios import analytic_scenarios, export_scenario
from .acceptance import environment
from .common import PUBLIC, read_json, write_json
from .reference import certify_los


def manifest(protocol: dict) -> list[dict[str, Any]]:
    """Freeze all conditions independently of outcomes, including the four pilots."""
    cfg = protocol["c2"]
    return [
        {
            "job_id": f"{case}--{condition['id']}--seed{seed}",
            "scenario": case,
            "seed": seed,
            "condition": condition["id"],
            **condition,
        }
        for case in cfg["cases"]
        for seed in cfg["native_seeds"]
        for condition in cfg["conditions"]
    ]


def available_memory() -> int:
    """Read Windows available physical RAM without CIM or changing settings."""
    from ctypes import wintypes

    class Memory(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total",
                "available",
                "page_total",
                "page_available",
                "virtual_total",
                "virtual_available",
                "extended",
            )
        ]

    value = Memory()
    value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        raise OSError("Cannot measure available physical RAM")
    return value.available


def run(
    source: Path,
    dependency: Path,
    build: Path,
    executable: Path,
    local: Path,
    output: Path,
    pilot_only: bool,
) -> dict:
    """Run each registered job once and reuse complete pilot evidence verbatim."""
    if not read_json(output / "c1_summary.json")["c2_gate_passed"]:
        raise ValueError("C1 gate has not passed")
    if not read_json(output / "c2_interface_acceptance.json")["passed"]:
        raise ValueError("New native adapter has not passed13 cases")
    build_status = read_json(build / "build_status.json")
    if (
        build_status["commands"][-1]["label"] != "ctest"
        or build_status["commands"][-1]["exit_code"]
    ):
        raise ValueError("New native CTest evidence is not successful")
    protocol = read_config("stage6c_protocol.json")
    cfg = protocol["c2"]
    tasks = manifest(protocol)
    manifest_path = output / "c2_manifest.json"
    if manifest_path.exists() and read_json(manifest_path) != tasks:
        raise ValueError("Existing preregistered roster differs")
    write_json(manifest_path, tasks)
    cases = {
        case.id: case for case in analytic_scenarios() if case.expected_reason == "ok"
    }
    rows, curves = [], []
    native_environment = environment(dependency)
    for task in tasks[:4] if pilot_only else tasks:
        scenario = cases[task["scenario"]]
        request = {
            "mode": "plan",
            "algorithm": task["algorithm"],
            "search_mode": task["mode"],
            "seed": task["seed"],
            "search_budget_s": cfg["native_search_cap_s"],
            "scenario": export_scenario(scenario, source / "grids"),
            **{key: task[key] for key in ("selection_radius", "pruning_radius")},
            **{
                key: cfg[key]
                for key in (
                    "propagation_min_steps",
                    "propagation_max_steps",
                    "goal_bias",
                )
            },
        }
        folder = local / "search" / task["job_id"]
        summary_path = folder / "condition_summary.json"
        if summary_path.exists():
            if read_json(folder / "input.json") != request:
                raise ValueError("Recorded pilot request differs from frozen inputs")
            row = read_json(summary_path)
            payload = read_json(folder / "output.json")
        else:
            if available_memory() < 4 * 2**30:
                raise RuntimeError("Physical RAM resource gate failed")
            random.seed(task["seed"])
            np.random.seed(task["seed"])
            started = time.perf_counter()
            native = invoke_native(
                executable, request, folder, environment=native_environment
            )
            payload = native.payload
            first_audit, first_finished = None, None
            if payload.get("first_path") is not None:
                first_audit, _ = audit_controls(
                    scenario, {**payload["first_path"], "status": "exact"}
                )
                first_finished = time.perf_counter() - started
                if not first_audit["model_feasible"]:
                    raise ValueError(
                        "Official first incumbent failed independent certificate"
                    )
            audit, trace = audit_controls(scenario, payload)
            certificate_finished = time.perf_counter() - started
            if not audit["independent_audit_passed"]:
                raise ValueError(
                    "Official returned path failed independent certificate"
                )
            if payload.get("first_path_is_final"):
                first_audit, first_finished = audit, certificate_finished
            exact = bool(audit["model_feasible"])
            model = bool(exact and certificate_finished <= 10.0)
            events = payload["improvement_events"]
            costs = [float(event["cost"]) for event in events]
            if any(b >= a - 1e-9 for a, b in zip(costs[:-1], costs[1:], strict=True)):
                raise ValueError("Official incumbent cost history is not improving")
            duration = sum(
                float(control["duration_s"]) for control in payload["controls"]
            )
            if exact and (
                not costs or not np.isclose(costs[-1], duration, rtol=0, atol=1e-9)
            ):
                raise ValueError("Final incumbent cost differs from returned controls")
            tracking, los_trace = (
                {
                    "was_run": False,
                    "eligible": False,
                    "execution_success": False,
                    "failure_reason": "not_run_no_budget_qualified_model_path",
                },
                [],
            )
            los_audit = None
            execution_wall = None
            if model:
                execution_started = time.perf_counter()
                tracking, los_trace = track_reference(scenario, audit, trace)
                if tracking["was_run"]:
                    los_audit = certify_los(los_trace, scenario)
                    if tracking["execution_success"] and not (
                        los_audit["full_margin_safe"] and los_audit["goal_reached"]
                    ):
                        raise ValueError(
                            "LOS strict success is a safety false positive"
                        )
                execution_wall = time.perf_counter() - execution_started
            strict = bool(
                model
                and tracking["execution_success"]
                and execution_wall is not None
                and execution_wall <= 20
                and certificate_finished + execution_wall <= 30
            )
            reason = (
                "planning_deadline"
                if certificate_finished > 10
                else audit["reason"]
                if not model
                else "execution_deadline"
                if execution_wall is not None and execution_wall > 20
                else "pipeline_deadline"
                if execution_wall is not None
                and certificate_finished + execution_wall > 30
                else tracking["failure_reason"]
            )
            row = {
                "job_id": task["job_id"],
                "scenario": task["scenario"],
                "condition": task["condition"],
                "algorithm": task["algorithm"],
                "search_mode": task["mode"],
                "native_seed": task["seed"],
                "data_role": "development",
                "selection_radius": task["selection_radius"],
                "pruning_radius": task["pruning_radius"],
                "native_status": payload["status"],
                "raw_status": payload["raw_status"],
                "model_feasible_before_deadline": exact,
                "model_feasible": model,
                "planning_deadline_rejected": certificate_finished > 10,
                "first_native_certificate_s": events[0]["native_certificate_finish_s"]
                if events
                else None,
                "first_independent_certificate_finish_s": first_finished,
                "best_independent_certificate_finish_s": certificate_finished,
                "candidate_return_s": payload["candidate_return_s"],
                "native_certificate_finish_s": payload["native_certificate_finish_s"],
                "first_native_cost_m": costs[0] if costs else None,
                "raw_returned_arc_length_m": duration if payload["controls"] else None,
                "strict_best_certified_cost_m": duration if model else None,
                "improvement_events": len(events),
                "propagated_intervals": payload["propagated_intervals"],
                "collision_queries": payload["collision_queries"],
                "box_distance_tests": payload["box_distance_tests"],
                "peak_native_rss_bytes": payload["peak_native_rss_bytes"],
                "maximum_rk4_error_m": audit.get("maximum_rk4_error_m"),
                "minimum_gap_lower_bound_m": audit.get("minimum_gap_lower_bound_m"),
                "reference_geometry_safe": (
                    bool(tracking.get("reference_chords_certified", False))
                    if model
                    else None
                ),
                "los_was_run": tracking["was_run"],
                "los_eligible": tracking["eligible"],
                "los_strict_success": strict,
                "los_failure_reason": tracking["failure_reason"],
                "execution_and_independent_audit_wall_s": execution_wall,
                "pipeline_wall_s": certificate_finished + execution_wall
                if execution_wall is not None
                else certificate_finished,
                "failure_reason": reason,
                **native.timing,
            }
            with gzip.open(
                folder / "independent_record.json.gz", "xt", encoding="utf-8"
            ) as stream:
                json.dump(
                    {
                        "first_audit": first_audit,
                        "audit": audit,
                        "native_replay_trace": trace,
                        "tracking": tracking,
                        "los_audit": los_audit,
                        "los_trace": los_trace,
                    },
                    stream,
                    ensure_ascii=False,
                    allow_nan=False,
                )
            write_json(summary_path, row)
        rows.append(row)
        curves.extend(
            {
                "job_id": task["job_id"],
                "condition": task["condition"],
                "scenario": task["scenario"],
                "native_seed": task["seed"],
                "event": i,
                "certificate_scope": "native_full_control_replay",
                **event,
            }
            for i, event in enumerate(payload["improvement_events"])
        )
        write_csv(output / "planning_runs.csv", rows)
        if curves:
            write_csv(output / "native_cost_events.csv", curves)
        if len(rows) <= 4:
            size = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
            if row["peak_native_rss_bytes"] > 2**30 or size > 5 * 2**20:
                raise RuntimeError("Pilot RSS/record size resource gate failed")
        accounting = {
            "registered": len(tasks),
            "actually_run": len(rows),
            "complete": len(rows) == len(tasks),
            "pilot_only": pilot_only,
            "native_M": sum(r["model_feasible"] for r in rows),
            "reference_Gref": sum(r["reference_geometry_safe"] is True for r in rows),
            "actual_E": sum(r["los_was_run"] and r["los_eligible"] for r in rows),
            "strict_S": sum(r["los_strict_success"] for r in rows),
        }
        write_json(output / "c2_accounting.json", accounting)
        print(
            json.dumps(
                {
                    "job": task["job_id"],
                    "status": row["native_status"],
                    "M": row["model_feasible"],
                    "S": row["los_strict_success"],
                    "cost": row["strict_best_certified_cost_m"],
                }
            ),
            flush=True,
        )
    return accounting


def main() -> None:
    """Require real C0/C1/native acceptance and stop with preserved error evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "source-root",
        "dependency-root",
        "build-root",
        "executable",
        "local-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    parser.add_argument("--pilot-only", action="store_true")
    args = parser.parse_args()
    try:
        with exclusive_run(args.local_root):
            result = run(
                args.source_root,
                args.dependency_root,
                args.build_root,
                args.executable,
                args.local_root,
                args.output,
                args.pilot_only,
            )
    except Exception as error:
        write_json(
            args.local_root / f"stopped-{time.time_ns()}.json",
            {"error_type": type(error).__name__, "error": str(error)},
        )
        raise
    print(json.dumps(result))


if __name__ == "__main__":
    main()
