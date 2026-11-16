"""Actual SI acceptance against frozen C++ and independent Python controls."""

from __future__ import annotations

import argparse
import json
import math
import traceback
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT
from ..stage5a.tracking import wrap
from ..stage6b.bridge import invoke_native
from ..stage6b.replay import _replay
from ..stage6b.runner import exclusive_run
from ..stage6b.scenarios import analytic_scenarios, mid_segment_scenario, state_values
from ..stage6c.acceptance import environment
from ..stage6c.common import read_json
from ..stage6d.common import save_json
from ..stage6d.maps import build_scenarios
from . import ADAPTER_ID, PUBLIC
from .cases import AcceptanceCase, boundary_cases, export_scene, json_safe


def native_call(
    executable: Path, dependency: Path, request: dict[str, Any], folder: Path
) -> dict[str, Any]:
    """Reuse only complete measured invocations, never repeat a partial case."""
    request = json_safe(request)
    clock = folder / "bridge_timing.json"
    if clock.exists():
        if (
            read_json(folder / "input.json") != request
            or read_json(clock)["return_code"] != 0
        ):
            raise RuntimeError("Stored native invocation differs or failed")
        return read_json(folder / "output.json")
    native = invoke_native(
        executable, request, folder, environment=environment(dependency)
    )
    save_json(clock, native.timing, exclusive=True)
    return native.payload


def validate_policy(payload: dict[str, Any]) -> None:
    """Check actual configured bounds and unchanged control/space settings."""
    policy = payload["adapter"]
    envelope = math.pi / 9 + 1e-12
    if (
        payload["ompl_version"] != "2.0.2"
        or policy["adapter_id"] != ADAPTER_ID
        or policy["declared_pitch_low_rad"] != -envelope
        or policy["declared_pitch_high_rad"] != envelope
        or policy["nominal_pitch_limit_rad"] != math.pi / 9
        or policy["frozen_pitch_tolerance_rad"] != 1e-12
        or policy["control_low"] != [-math.pi / 18, -math.pi / 36]
        or policy["control_high"] != [math.pi / 18, math.pi / 36]
        or policy["state_dimension"] != 5
        or policy["step_s"] != 0.1
        or policy["minimum_steps"] != 1
        or policy["maximum_steps"] != 50
        or policy["subspace_weights"] != [1, 1, 1]
        or policy["backward_propagation"]
    ):
        raise RuntimeError("Actual adapter policy differs from the registered repair")


def independent(
    case: AcceptanceCase, payload: dict[str, Any], group: str
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Compare real SI states to the unmodified supplied-control Python replay."""
    scenario = case.scenario
    initial_audit, _, _ = _replay(scenario, ())
    audit, trace, _ = _replay(scenario, scenario.witness_controls)
    initial_reason, reason = initial_audit["reason"], audit["reason"]
    # The Python ODE accepts equivalent yaw representations; the frozen binding
    # additionally requires canonical SO(2), as specified by6B validate_state.
    canonical = -math.pi <= scenario.initial.yaw < math.pi
    if (
        all(math.isfinite(v) for v in state_values(scenario.initial))
        and scenario.initial.speed == 1
        and not canonical
    ):
        initial_reason = reason = "yaw_bound"
    expected_source = initial_reason == "ok"
    initial = payload["initial"]
    admitted = initial["mapping_performed"] and initial["si_is_valid"]
    if (
        admitted != expected_source
        or not payload["agreement"]
        or payload["reason"] != reason
    ):
        raise RuntimeError(f"Model/SI acceptance disagrees in {scenario.id}")
    if initial["state"] != json_safe(state_values(scenario.initial)):
        raise RuntimeError("Input round-trip altered a registered state")
    accepted = [row for row in payload["trace"] if row["accepted_steps"] == 1]
    expected = [row for row in trace if row["accepted"]]
    if len(accepted) != len(expected) or payload["accepted_intervals"] != len(expected):
        raise RuntimeError("Actual accepted interval count differs from frozen Python")
    maximum_position, maximum_angle = 0.0, 0.0
    for actual, known in zip(accepted, expected, strict=True):
        values = actual["returned_state"]
        maximum_position = max(
            maximum_position, math.dist(values[:3], known["position"])
        )
        maximum_angle = max(
            maximum_angle,
            abs(wrap(values[3] - known["yaw_rad"])),
            abs(values[4] - known["pitch_rad"]),
            abs(values[5] - known["speed_m_s"]),
        )
    if (
        maximum_position > 1e-10
        or maximum_angle > 1e-12
        or audit["maximum_rk4_error_m"] > 1e-10
    ):
        raise RuntimeError("SI states differ from independent integration or RK4")
    intervals = []
    for row in payload["trace"]:
        index = row["interval_index"]
        known = trace[index] if index < len(trace) else None
        error = (
            math.dist(row["candidate"]["state"][:3], known["position"])
            if known
            else None
        )
        if error is not None and error > 1e-10:
            raise RuntimeError(
                "Rejected candidate differs from independent integration"
            )
        intervals.append(
            {
                "case_id": scenario.id,
                "group": group,
                "interval_index": index,
                "source_interval_index": index + case.source_interval_offset,
                "native_time_start_s": row["time_start_s"],
                "source_time_start_s": (index + case.source_interval_offset) * 0.1,
                "propagation_invoked": row["propagation_invoked"],
                "expected_steps": row["expected_steps"],
                "accepted_steps": row["accepted_steps"],
                "source_si_valid": row["source"]["si_is_valid"],
                "candidate_pitch_rad": row["candidate"]["state"][4],
                "candidate_model_valid": row["candidate"]["model_valid"],
                "candidate_bounds": row["candidate"]["satisfies_bounds"],
                "candidate_si_valid": row["candidate"]["si_is_valid"],
                "returned_si_valid": row["returned_si_valid"],
                "frozen_interval_valid": row["frozen_interval_valid"],
                "frozen_reason": row["frozen_interval_reason"],
                "cpp_model_si_agree": row["agreement"],
                "cpp_position_error_m": row["position_error_m"],
                "python_interval_measured": known is not None,
                "python_interval_valid": known["accepted"] if known else None,
                "python_candidate_position_error_m": error,
            }
        )
    last = payload["trace"][-1] if payload["trace"] else None
    summary = {
        "case_id": scenario.id,
        "category": case.category,
        "mode": case.mode,
        "input_pitch_rad": json_safe(scenario.initial.pitch),
        "input_speed_m_s": json_safe(scenario.initial.speed),
        "model_valid": initial["model_valid"],
        "model_reason": initial["model_reason"],
        "mapping_performed": initial["mapping_performed"],
        "satisfies_bounds": initial["satisfies_bounds"],
        "si_is_valid": initial["si_is_valid"],
        "python_initial_reason": initial_reason,
        "python_final_reason": reason,
        "native_reason": payload["reason"],
        "accepted_intervals": len(accepted),
        "actual_propagator_calls": payload["propagator_calls"],
        "last_actual_steps": last["accepted_steps"] if last else None,
        "last_expected_steps": last["expected_steps"] if last else None,
        "maximum_position_error_m": maximum_position if accepted else None,
        "maximum_angle_or_speed_error": maximum_angle if accepted else None,
        "maximum_rk4_error_m": audit["maximum_rk4_error_m"],
        "input_roundtrip_verified": True,
        "passed": True,
        "planning_searches": 0,
    }
    return summary, intervals, audit


def compare_old(
    old: dict[str, Any], new: dict[str, Any], identity: str, *, legacy: bool
) -> dict[str, Any]:
    """Compare preserved native states rather than a reconstructed old success."""
    states = (
        [row["following"] for row in old["trace"] if row["accepted"]]
        if legacy
        else old["states"]
    )
    actual = [
        row["returned_state"] for row in new["trace"] if row["accepted_steps"] == 1
    ]
    if len(states) != len(actual) or old["reason"] != new["reason"]:
        raise RuntimeError("Old/new away-from-boundary accepted conclusions differ")
    error = max(
        (
            max(abs(a - b) for a, b in zip(x, y, strict=True))
            for x, y in zip(states, actual, strict=True)
        ),
        default=0.0,
    )
    if error > 1e-10:
        raise RuntimeError("Old/new numeric states unexpectedly changed")
    return {
        "case_id": identity,
        "old_source": "preserved_native_output",
        "accepted_states": len(actual),
        "maximum_state_error": error,
        "reason_unchanged": True,
        "passed": True,
    }


def run(
    executable: Path,
    original_probe: Path,
    dependency: Path,
    build: Path,
    legacy: Path,
    old_maps: Path | None,
    local: Path,
    output: Path,
) -> dict[str, Any]:
    """Follow F0/F1/F2 gates, without any planner or solve request."""
    if not output.resolve().is_relative_to(PUBLIC.resolve()):
        raise ValueError("Public acceptance output must remain under results/stage6dr")
    if local.resolve().is_relative_to(ROOT):
        raise ValueError("Native raw evidence must remain outside Git")
    output.mkdir(parents=True, exist_ok=True)
    status = read_json(build / "build_status.json")
    if (
        status["commands"][-1]["label"] != "ctest"
        or status["commands"][-1]["exit_code"]
    ):
        raise RuntimeError("Native four-test gate has not passed")
    references = [legacy / "grids"] + ([old_maps / "grids"] if old_maps else [])
    cache = local / "grids"
    maps = build_scenarios()
    terrain = next(case for case in maps if case.id == "terrain_1")
    scene = export_scene(terrain, references, cache)
    original = native_call(
        original_probe,
        dependency,
        {"mode": "replay", "scenario": scene, "controls": terrain.witness_controls},
        local / "f0_original",
    )
    if not (
        original["mismatch_detected"]
        and original["interval_index"] == 89
        and original["expected_accepted_steps"] == 1
        and original["actual_accepted_steps"] == 0
    ):
        raise RuntimeError("Original frozen failure was not preserved")
    save_json(output / "original_failure_reproduced.json", original)
    rows, interval_rows, comparisons = [], [], []
    groups = [
        ("boundary", boundary_cases()),
        (
            "legacy13",
            [
                AcceptanceCase(case, "legacy13", "replay")
                for case in [*analytic_scenarios(), mid_segment_scenario()]
            ],
        ),
        (
            "maps6",
            [
                AcceptanceCase(case, "supplied_obstacle_witness", "replay")
                for case in sorted(maps, key=lambda case: case.id != "terrain_1")
            ],
        ),
    ]
    manifest = [
        {
            "group": group,
            "case_id": case.scenario.id,
            "mode": case.mode,
            "initial": json_safe(state_values(case.scenario.initial)),
            "controls": json_safe(case.scenario.witness_controls),
            "source_interval_offset": case.source_interval_offset,
        }
        for group, cases in groups
        for case in cases
    ]
    existing = output / "case_manifest.json"
    if existing.exists() and read_json(existing) != manifest:
        raise RuntimeError("Registered acceptance roster changed")
    save_json(existing, manifest)
    for group, cases in groups:
        group_rows = []
        for case in cases:
            request = {
                "mode": case.mode,
                "scenario": export_scene(case.scenario, references, cache),
                "controls": case.scenario.witness_controls,
                "source_interval_offset": case.source_interval_offset,
            }
            payload = native_call(
                executable, dependency, request, local / group / case.scenario.id
            )
            validate_policy(payload)
            row, intervals, audit = independent(case, payload, group)
            group_rows.append(row)
            rows.append({"group": group, **row})
            interval_rows.extend(intervals)
            save_json(
                local / group / case.scenario.id / "independent_audit.json",
                json_safe(audit),
            )
            if group == "legacy13":
                old = read_json(
                    legacy / "acceptance" / case.scenario.id / "output.json"
                )
                comparisons.append(
                    compare_old(old, payload, case.scenario.id, legacy=True)
                )
            if group == "maps6":
                if not audit["goal_reached"] or payload["reason"] != "ok":
                    raise RuntimeError(
                        "A complete supplied obstacle witness did not pass"
                    )
                old_path = (
                    old_maps / "witnesses" / case.scenario.id / "output.json"
                    if old_maps
                    else None
                )
                if old_path and old_path.exists():
                    comparisons.append(
                        compare_old(
                            read_json(old_path), payload, case.scenario.id, legacy=False
                        )
                    )
            write_csv(output / f"{group}_cases.csv", group_rows)
            write_csv(output / "interval_checks.csv", interval_rows)
            print(
                json.dumps(
                    {
                        "group": group,
                        "case": case.scenario.id,
                        "accepted": row["accepted_intervals"],
                        "reason": row["native_reason"],
                        "passed": True,
                    }
                ),
                flush=True,
            )
    if comparisons:
        write_csv(output / "old_new_compatibility.csv", comparisons)
    policy = read_json(local / "maps6/terrain_1/output.json")["adapter"]
    save_json(output / "adapter_policy.json", policy)
    save_json(output / "build_evidence.json", status)
    result = {
        "local_model_interface_passed": True,
        "adapter_id": ADAPTER_ID,
        "original_failure_reproduced": True,
        "boundary_cases": len(groups[0][1]),
        "legacy_cases": 13,
        "legacy_accepted_intervals": sum(
            r["accepted_intervals"] for r in rows if r["group"] == "legacy13"
        ),
        "maps": 6,
        "map_accepted_intervals": sum(
            r["accepted_intervals"] for r in rows if r["group"] == "maps6"
        ),
        "terrain_1_intervals": next(
            r["accepted_intervals"]
            for r in rows
            if r["group"] == "maps6" and r["case_id"] == "terrain_1"
        ),
        "measured_interval_attempts": len(interval_rows),
        "maximum_position_error_m": max(
            r["maximum_position_error_m"] or 0 for r in rows
        ),
        "maximum_rk4_error_m": max(r["maximum_rk4_error_m"] for r in rows),
        "old_new_cases_compared": len(comparisons),
        "new_planning_searches": 0,
        "planning_searches_authorized": 0,
        "h1_authorized": False,
        "final_head_ci": (
            "Required separately; exact-head runtime artifact binds "
            "final MODEL-INTERFACE verdict"
        ),
    }
    save_json(output / "acceptance_summary.json", result)
    return result


def main() -> None:
    """Require explicit roots and preserve an original stopped record on failure."""
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
    parser.add_argument("--old-map-root", type=Path)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    try:
        with exclusive_run(args.local_root):
            print(
                json.dumps(
                    run(
                        args.executable,
                        args.original_probe,
                        args.dependency_root,
                        args.build_root,
                        args.legacy_root,
                        args.old_map_root,
                        args.local_root,
                        args.output,
                    )
                )
            )
    except Exception:
        save_json(
            args.local_root / "stopped.json",
            {
                "error": traceback.format_exc(),
                "model_interface": "MODEL-INTERFACE BLOCKED",
                "new_planning_searches": 0,
            },
            exclusive=True,
        )
        raise


if __name__ == "__main__":
    main()
