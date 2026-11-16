"""Gate all random searches on the actual new planner binary and frozen oracles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT
from ..stage6b.runner import exclusive_run
from ..stage6b.scenarios import analytic_scenarios, mid_segment_scenario
from ..stage6c.common import read_json
from ..stage6d.common import save_json
from ..stage6d.maps import build_scenarios
from ..stage6dr.acceptance import compare_old, independent, native_call, validate_policy
from ..stage6dr.cases import AcceptanceCase, boundary_cases, export_scene
from . import BINARY_ID, PUBLIC
from .protocol import check_identity, frozen, request_for


def run(
    executable: Path,
    original: Path,
    dependency: Path,
    build: Path,
    legacy: Path,
    references: list[Path],
    local: Path,
    output: Path,
) -> dict[str, Any]:
    """No solver call:69+13+6 replays and three real planner constructions."""
    frozen()
    if local.resolve().is_relative_to(ROOT) or not output.resolve().is_relative_to(
        PUBLIC
    ):
        raise ValueError("Keep raw evidence outside Git and new public evidence in6DS")
    status = read_json(build / "build_status.json")
    if (
        status["commands"][-1]["label"] != "ctest"
        or status["commands"][-1]["exit_code"]
    ):
        raise RuntimeError("Actual native five-test gate has not passed")
    maps = build_scenarios()
    cache = local / "grids"
    terrain = next(c for c in maps if c.id == "terrain_1")
    raw = native_call(
        original,
        dependency,
        {
            "mode": "replay",
            "scenario": export_scene(terrain, references, cache),
            "controls": terrain.witness_controls,
        },
        local / "original_failure",
    )
    if not (
        raw["mismatch_detected"]
        and raw["interval_index"] == 89
        and raw["expected_accepted_steps"] == 1
        and raw["actual_accepted_steps"] == 0
    ):
        raise RuntimeError("The preserved old failure did not reproduce")
    save_json(output / "original_failure.json", raw)
    groups = [
        ("boundary", boundary_cases()),
        (
            "legacy13",
            [
                AcceptanceCase(c, "legacy13", "replay")
                for c in [*analytic_scenarios(), mid_segment_scenario()]
            ],
        ),
        (
            "maps6",
            [
                AcceptanceCase(c, "frozen_witness", "replay")
                for c in sorted(maps, key=lambda c: c.id != "terrain_1")
            ],
        ),
    ]
    rows, intervals, comparisons = [], [], []
    for group, cases in groups:
        for case in cases:
            payload = native_call(
                executable,
                dependency,
                {
                    "mode": case.mode,
                    "scenario": export_scene(case.scenario, references, cache),
                    "controls": case.scenario.witness_controls,
                },
                local / group / case.scenario.id,
            )
            validate_policy(payload)
            if payload["binary_id"] != BINARY_ID:
                raise RuntimeError("Acceptance did not use the actual new binary")
            row, checks, audit = independent(case, payload, group)
            if group == "maps6" and not (
                audit["goal_reached"] and payload["reason"] == "ok"
            ):
                raise RuntimeError("A frozen complete supplied witness failed")
            rows.append(
                {
                    "group": group,
                    **row,
                    "goal_reached": audit["goal_reached"],
                    "minimum_gap_lower_bound_m": audit["minimum_gap_lower_bound_m"],
                }
            )
            intervals.extend(checks)
            if group == "legacy13":
                comparisons.append(
                    compare_old(
                        read_json(
                            legacy / "acceptance" / case.scenario.id / "output.json"
                        ),
                        payload,
                        case.scenario.id,
                        legacy=True,
                    )
                )
            write_csv(output / "cases.csv", rows)
            write_csv(output / "interval_checks.csv", intervals)
        print(f"{group}: {len(cases)} cases passed", flush=True)
    _, tasks = frozen()
    identities = []
    wide = next(c for c in maps if c.id == "wide_1")
    for task in tasks[:3]:
        request = request_for(task, export_scene(wide, references, cache))
        request["mode"] = "planner_check"
        payload = native_call(
            executable, dependency, request, local / "planner_identity" / task["id"]
        )
        check_identity(payload["identity"], task)
        validate_policy(
            {
                "adapter": payload["identity"]["adapter"],
                "ompl_version": payload["ompl_version"],
            }
        )
        if payload["new_planning_searches"] != 0:
            raise RuntimeError("Planner identity acceptance must not solve")
        identities.append({"condition": task["id"], **payload})
    save_json(output / "actual_planner_identity.json", identities)
    write_csv(output / "old13_compatibility.csv", comparisons)
    summary = {
        "passed": True,
        "binary_id": BINARY_ID,
        "boundary_cases": 69,
        "legacy_cases": 13,
        "legacy_accepted_intervals": sum(
            r["accepted_intervals"] for r in rows if r["group"] == "legacy13"
        ),
        "map_accepted_intervals": sum(
            r["accepted_intervals"] for r in rows if r["group"] == "maps6"
        ),
        "terrain_1_intervals": next(
            r["accepted_intervals"] for r in rows if r["case_id"] == "terrain_1"
        ),
        "planner_identity_checks": len(identities),
        "interval_attempts": len(intervals),
        "maximum_position_error_m": max(
            r["maximum_position_error_m"] or 0 for r in rows
        ),
        "maximum_rk4_error_m": max(r["maximum_rk4_error_m"] for r in rows),
        "new_planning_searches": 0,
    }
    if (
        summary["legacy_accepted_intervals"] != 930
        or summary["map_accepted_intervals"] != 2440
    ):
        raise RuntimeError("Complete supplied-control denominator changed")
    save_json(output / "acceptance_summary.json", summary)
    return summary


def main() -> None:
    """Keep the deterministic phase separate from the authorized54-job phase."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "executable",
        "original-probe",
        "dependency-root",
        "build-root",
        "legacy-root",
        "local-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--grid-reference", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, default=PUBLIC / "acceptance")
    args = parser.parse_args()
    with exclusive_run(args.local_root):
        print(
            json.dumps(
                run(
                    args.executable,
                    args.original_probe,
                    args.dependency_root,
                    args.build_root,
                    args.legacy_root,
                    [args.legacy_root / "grids", *args.grid_reference],
                    args.local_root,
                    args.output,
                )
            )
        )


if __name__ == "__main__":
    main()
