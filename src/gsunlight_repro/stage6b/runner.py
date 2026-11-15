"""Run preregistered correctness gates before any official-control smoke search."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage5a.geometry import Geometry
from ..stage5a.maps import ROOT, read_config
from .bridge import invoke_native
from .replay import audit_controls, audit_supplied_controls, track_reference
from .scenarios import (
    Scenario,
    analytic_scenarios,
    effective_radius,
    export_scenario,
    historical_scenario,
    mid_segment_scenario,
)


def write_json(path: Path, value: Any) -> None:
    """Write compact stage evidence, rejecting nonfinite invented placeholders."""
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )


@contextmanager
def exclusive_run(folder: Path) -> Iterator[None]:
    """Prevent concurrent workers from modifying the same registered run."""
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "worker.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink()


class Runner:
    """One public evidence directory and one exclusive local numeric record tree."""

    def __init__(
        self, executable: Path, build: Path, local: Path, output: Path
    ) -> None:
        self.executable, self.build, self.local, self.output = (
            p.resolve() for p in (executable, build, local, output)
        )
        if self.local.is_relative_to(ROOT):
            raise ValueError("Full native records must remain outside Git")
        if not self.output.is_relative_to(ROOT / "results/stage6b"):
            raise ValueError("Stage6B cannot target historical result directories")
        self.output.mkdir(parents=True, exist_ok=True)
        self.protocol = read_config("stage6b_protocol.json")
        self.environment = {
            "PATH": str(self.build / "packages/llvm-mingw-20261104-ucrt-x86_64/bin")
            + os.pathsep
            + os.environ["PATH"]
        }

    def require_native_build(self) -> None:
        """Require actual successful official build and adapter CTest records."""
        evidence = json.loads(
            (self.build / "build_status.json").read_text(encoding="utf-8")
        )
        latest = {row["label"]: row for row in evidence["commands"]}
        for name in (
            "ompl-configure",
            "ompl-install",
            "adapter-build",
            "adapter-ctest",
        ):
            if name not in latest or latest[name]["exit_code"] != 0:
                raise RuntimeError(f"B0 prerequisite not actually passed: {name}")
        if not self.executable.is_file():
            raise FileNotFoundError(self.executable)

    def acceptance(self) -> dict[str, Any]:
        """Run the frozen twelve cases and one true middle-collision rejection."""
        self.require_native_build()
        rows: list[dict[str, Any]] = []
        for scenario in [*analytic_scenarios(), mid_segment_scenario()]:
            request = {
                "mode": "replay",
                "scenario": export_scenario(scenario, self.local / "grids"),
                "controls": scenario.witness_controls,
            }
            result = invoke_native(
                self.executable,
                request,
                self.local / "acceptance" / scenario.id,
                environment=self.environment,
            )
            summary, _ = audit_supplied_controls(scenario, result.payload)
            row = {
                **summary,
                "ompl_version": result.payload["ompl_version"],
                "adapter_probes_passed": result.payload.get(
                    "adapter_probes_passed", False
                ),
                "adapter_propagator_calls": result.payload.get(
                    "adapter_propagator_calls", 0
                ),
                **result.timing,
            }
            row["passed"] = bool(
                row["independent_audit_passed"]
                and row["adapter_probes_passed"]
                and row["ompl_version"] == self.protocol["official_ompl_version"]
            )
            rows.append(row)
            write_csv(self.output / "interface_cases.csv", rows)
            print(
                json.dumps({"case": scenario.id, "passed": row["passed"]}), flush=True
            )
            if not row["passed"]:
                write_json(
                    self.output / "interface_acceptance.json",
                    {
                        "passed": False,
                        "failed_case": scenario.id,
                        "searches_started": 0,
                    },
                )
                raise RuntimeError("B1 mismatch: stop before any planning search")
        counterexample = mid_segment_scenario()
        geometry = Geometry(counterexample.scene.grid, effective_radius())
        a, b = counterexample.scene.start, counterexample.scene.goal
        middle = tuple((x + y) / 2 for x, y in zip(a, b, strict=True))
        evidence = {
            "start": a,
            "middle": middle,
            "end": b,
            "start_free": geometry.segment(a, a).valid,
            "end_free": geometry.segment(b, b).valid,
            "middle_free": geometry.segment(middle, middle).valid,
            "middle_gap_m": geometry.clearance(middle, middle),
            "full_segment_certified": geometry.segment(a, b).valid,
            "interpretation": (
                "Rejected interval endpoints are not collision instant positions; "
                "actual middle sphere intersection independently demonstrated."
            ),
        }
        write_json(self.output / "middle_collision.json", evidence)
        summary = {
            "passed": len(rows) == 13 and all(row["passed"] for row in rows),
            "cases": len(rows),
            "accepted_intervals": sum(row["accepted_intervals"] for row in rows),
            "maximum_position_error_m": max(
                row["maximum_native_position_error_m"] for row in rows
            ),
            "maximum_angle_or_speed_error": max(
                row["maximum_native_angle_or_speed_error"] for row in rows
            ),
            "independent_rk4_intervals": sum(
                row["independent_rk4_intervals"] for row in rows
            ),
            "maximum_rk4_error_m": max(row["maximum_rk4_error_m"] for row in rows),
            "actual_adapter_propagator_calls": sum(
                row["adapter_propagator_calls"] for row in rows
            ),
            "searches_started": 0,
        }
        write_json(self.output / "interface_acceptance.json", summary)
        write_json(self.local / "b1_passed.json", summary)
        return summary

    def jobs(self) -> list[tuple[str, Scenario, str, int]]:
        """Build the fixed manifest without leaking witness controls to planners."""
        scenarios = {
            row.id: row for row in analytic_scenarios() if row.expected_reason == "ok"
        }
        for identity in ("F_O1", "F_N1", "F_B1"):
            scenarios[identity] = historical_scenario(identity)
        cfg = self.protocol["planning"]
        return [
            (
                f"{identity}--{algorithm}--seed{label}",
                scenarios[identity],
                algorithm,
                label,
            )
            for identity in cfg["cases"]
            for label in cfg["seed_labels"]
            for algorithm in cfg["algorithms"]
        ]

    def search(self, pilot_only: bool) -> dict[str, Any]:
        """Audit every returned control path, retaining all registered failures."""
        self.require_native_build()
        if not json.loads((self.local / "b1_passed.json").read_text())["passed"]:
            raise RuntimeError("B1 acceptance has not passed")
        cfg = self.protocol["planning"]
        jobs = self.jobs()
        if len(jobs) != cfg["total_trials_maximum"]:
            raise ValueError("Search manifest cardinality differs from preregistration")
        write_json(
            self.output / "search_manifest.json",
            [
                {
                    "job_id": identity,
                    "scenario": scenario.id,
                    "algorithm": algorithm,
                    "seed_label": label,
                    "ompl_seed": cfg["ompl_seed_by_label"][str(label)],
                    "reachability": scenario.reachability,
                }
                for identity, scenario, algorithm, label in jobs
            ],
        )
        rows = []
        for identity, scenario, algorithm, label in jobs:
            if pilot_only and identity not in cfg["pilot"]:
                continue
            folder = self.local / "search" / identity
            summary_file = folder / "condition_summary.json"
            if summary_file.exists():
                recorded = json.loads(
                    (folder / "input.json").read_text(encoding="utf-8")
                )
                expected = self.planning_request(scenario, algorithm, label)
                if recorded != expected:
                    raise ValueError(
                        "Completed task inputs differ from the frozen manifest"
                    )
                row = json.loads(summary_file.read_text(encoding="utf-8"))
            else:
                request = self.planning_request(scenario, algorithm, label)
                started = time.perf_counter()
                result = invoke_native(
                    self.executable, request, folder, environment=self.environment
                )
                native = result.payload
                audit, trace = audit_controls(scenario, native)
                certificate_finish_s = time.perf_counter() - started
                if not audit["independent_audit_passed"] or (
                    native["status"] != "no_solution"
                    and not native["native_certificate"]["valid"]
                ):
                    write_json(folder / "independent_audit_failure.json", audit)
                    raise RuntimeError(
                        f"Returned control mismatch: stop all searches at {identity}"
                    )
                model_before_deadline = bool(audit["model_feasible"])
                deadline_ok = certificate_finish_s <= cfg["wall_budget_s"]
                audit["model_feasible"] = model_before_deadline and deadline_ok
                tracking, los_trace = track_reference(scenario, audit, trace)
                tracking_s = tracking.get(
                    "tracking_and_adaptation_wall_s",
                    tracking.get("reference_adaptation_wall_s", 0.0),
                )
                tracking_deadline_ok = (
                    tracking_s <= self.protocol["reference_contract"]["wall_cap_s"]
                )
                total_ok = (
                    certificate_finish_s + tracking_s
                    <= self.protocol["reference_contract"]["total_pipeline_wall_cap_s"]
                )
                strict_tracking = bool(
                    tracking["was_run"]
                    and tracking["eligible"]
                    and tracking["execution_success"]
                    and tracking_deadline_ok
                    and total_ok
                )
                row = {
                    "job_id": identity,
                    "scenario": scenario.id,
                    "algorithm": algorithm,
                    "seed_label": label,
                    "ompl_seed": request["seed"],
                    "reachability": scenario.reachability,
                    "development_data": True,
                    "native_status": native["status"],
                    "raw_status": native["raw_status"],
                    "model_feasible_before_deadline": model_before_deadline,
                    "model_feasible": audit["model_feasible"],
                    "planning_deadline_rejected": not deadline_ok,
                    "independent_certificate_finish_s": certificate_finish_s,
                    "candidate_return_s": native["candidate_return_s"],
                    "independent_audit_passed": audit["independent_audit_passed"],
                    "control_segments": len(native["controls"]),
                    "accepted_trajectory_intervals": audit["accepted_intervals"],
                    "final_goal_distance_m": audit.get("final_goal_distance_m"),
                    "native_failure_reason": "deadline_rejected"
                    if not deadline_ok
                    else audit["reason"],
                    "maximum_native_node_position_error_m": audit.get(
                        "maximum_native_node_position_error_m"
                    ),
                    "maximum_rk4_error_m": audit.get("maximum_rk4_error_m"),
                    "minimum_gap_lower_bound_m": audit.get("minimum_gap_lower_bound_m"),
                    "propagated_intervals": native["propagated_intervals"],
                    "state_validity_calls": native["state_validity_calls"],
                    "planning_counters": native["planning_counters"],
                    "rejection_counts": native["rejection_counts"],
                    "was_run": tracking["was_run"],
                    "eligible": tracking["eligible"],
                    "los_success_before_deadline": tracking["execution_success"],
                    "los_strict_success": strict_tracking,
                    "los_failure_reason": "execution_deadline_rejected"
                    if not tracking_deadline_ok or not total_ok
                    else tracking["failure_reason"],
                    "tracking_and_adaptation_wall_s": tracking_s,
                    "reference_bridge_length_m": tracking.get(
                        "reference_bridge_length_m"
                    ),
                    "reference_progress_jump_markers_gt1m": tracking.get(
                        "reference_progress_jump_markers_gt1m"
                    ),
                    "maximum_tracking_error_m": tracking.get("max_tracking_error_m"),
                    "first_physical_rejection_time_s": tracking.get(
                        "first_physical_rejection_time_s"
                    ),
                    "first_physical_rejection_position": tracking.get(
                        "first_physical_rejection_position"
                    ),
                    "first_mission_rejection_position": tracking.get(
                        "first_mission_rejection_position"
                    ),
                    "first_margin_rejection_position": tracking.get(
                        "first_margin_rejection_position"
                    ),
                    **result.timing,
                }
                with gzip.open(
                    folder / "independent_record.json.gz", "xt", encoding="utf-8"
                ) as stream:
                    json.dump(
                        {
                            "audit": audit,
                            "native_replay_trace": trace,
                            "tracking": tracking,
                            "los_trace": los_trace,
                        },
                        stream,
                        allow_nan=False,
                    )
                write_json(summary_file, row)
            rows.append(row)
            write_csv(self.output / "planning_runs.csv", rows)
            print(
                json.dumps(
                    {
                        "job": identity,
                        "status": row["native_status"],
                        "M": row["model_feasible"],
                        "S": row["los_strict_success"],
                    }
                ),
                flush=True,
            )
        result = {
            "registered": len(jobs),
            "actually_run": len(rows),
            "complete": len(rows) == len(jobs),
            "model_successes": sum(row["model_feasible"] for row in rows),
            "actual_los_executions": sum(
                row["was_run"] and row["eligible"] for row in rows
            ),
            "strict_los_successes": sum(row["los_strict_success"] for row in rows),
            "pilot_only": pilot_only,
            "scope": (
                "development correctness smoke, not algorithm superiority evidence"
            ),
        }
        write_json(self.output / "experiment_accounting.json", result)
        return result

    def planning_request(
        self, scenario: Scenario, algorithm: str, label: int
    ) -> dict[str, Any]:
        """Use the same full input comparison for new and reused pilot tasks."""
        cfg = self.protocol["planning"]
        return {
            "mode": "plan",
            "algorithm": algorithm,
            "seed": cfg["ompl_seed_by_label"][str(label)],
            "search_budget_s": cfg["search_cap_s"],
            "total_budget_s": cfg["wall_budget_s"],
            "scenario": export_scenario(scenario, self.local / "grids"),
            **{
                key: cfg[key]
                for key in (
                    "propagation_min_steps",
                    "propagation_max_steps",
                    "goal_bias",
                    "selection_radius",
                    "pruning_radius",
                )
            },
        }


def main() -> None:
    """Require an actual native executable and prior gate evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("accept", "search"))
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results/stage6b")
    parser.add_argument("--pilot-only", action="store_true")
    args = parser.parse_args()
    runner = Runner(args.executable, args.build_root, args.local_root, args.output)
    try:
        with exclusive_run(runner.local):
            result = (
                runner.acceptance()
                if args.phase == "accept"
                else runner.search(args.pilot_only)
            )
    except (RuntimeError, ValueError, OSError) as error:
        event = runner.output / f"stopped-{time.time_ns()}.json"
        write_json(
            event,
            {
                "phase": args.phase,
                "error_type": type(error).__name__,
                "error": str(error),
                "continued_searches": False,
            },
        )
        raise
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
