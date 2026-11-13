"""Supplied-control witnesses for the frozen five-state kinematic model."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.analysis import write_csv
from ..stage5a.geometry import Geometry
from ..stage5a.maps import ROOT, body_radius, read_config
from ..stage5a.tracking import State, chord_error_bound, integrate
from ..stage5ar.reference import rk4_position


def curvature(speed: float, pitch: float, yaw_rate: float, pitch_rate: float) -> float:
    """Return spatial curvature for constant positive-speed Euler-angle rates."""
    if speed <= 0 or not all(
        math.isfinite(x) for x in (speed, pitch, yaw_rate, pitch_rate)
    ):
        raise ValueError("Curvature needs finite inputs and positive speed")
    return math.hypot(yaw_rate * math.cos(pitch), pitch_rate) / speed


def output_directory(path: Path) -> Path:
    """Prevent this acceptance program from overwriting historical results."""
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT) and not resolved.is_relative_to(
        ROOT / "results/stage6a"
    ):
        raise ValueError("Stage6A output cannot target historical repository files")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def run_case(spec: dict, protocol: dict, vehicle: dict) -> tuple[dict, list[dict]]:
    """Certify supplied controls, retaining the first rejected candidate interval."""
    cfg = vehicle["kinematics"]
    dt = protocol["step_s"]
    if dt != cfg["step_s"]:
        raise ValueError("Acceptance time step differs from frozen model")
    shape = tuple(
        int(round(length / spacing))
        for length, spacing in zip(
            protocol["extent_m"], protocol["spacing_m"], strict=True
        )
    )
    values = np.zeros(shape, dtype=bool)
    if spec.get("obstacle"):
        values[60:62, 35:45, 26:34] = True
    grid = OccupancyMap(values, spacing=tuple(protocol["spacing_m"]))
    ceiling = None
    if "ceiling_z_m" in spec:
        top = np.zeros(shape, dtype=bool)
        top[:, :, int(spec["ceiling_z_m"] / protocol["spacing_m"][2]) :] = True
        ceiling = OccupancyMap(top, spacing=tuple(protocol["spacing_m"]))
    radius = body_radius(vehicle) + vehicle["vehicle"]["safety_margin_m"]
    geometry = Geometry(grid, radius, ceiling)
    state = State(
        tuple(protocol["start_position_m"]),
        0.0,
        math.radians(spec.get("initial_pitch_deg", 0)),
        float(spec.get("initial_speed_m_s", cfg["speed_m_s"])),
    )
    trace: list[dict] = []
    reason = "ok"
    if state.speed != cfg["speed_m_s"]:
        reason = "frozen_speed"
    for yaw_deg, pitch_deg, duration in spec["controls_deg_s_duration_s"]:
        if reason != "ok":
            break
        count = round(duration / dt)
        if count < 1 or not math.isclose(count * dt, duration, abs_tol=1e-12):
            raise ValueError("Control duration must contain whole frozen time steps")
        if abs(yaw_deg) > cfg["max_yaw_rate_deg_s"]:
            reason = "yaw_rate"
            break
        if abs(pitch_deg) > cfg["max_pitch_rate_deg_s"]:
            reason = "pitch_rate"
            break
        yaw_rate, pitch_rate = math.radians(yaw_deg), math.radians(pitch_deg)
        for _ in range(count):
            following = integrate(state, yaw_rate, pitch_rate, dt)
            bound = chord_error_bound(state.speed, yaw_rate, pitch_rate, dt)
            if abs(following.pitch) > math.radians(cfg["max_pitch_deg"]) + 1e-12:
                reason = "pitch_bound"
            else:
                reason = geometry.segment(
                    state.position, following.position, extra_radius=bound
                ).reason
            trace.append(
                {
                    "start_position": state.position,
                    "position": following.position,
                    "start_yaw_rad": state.yaw,
                    "start_pitch_rad": state.pitch,
                    "yaw_rad": following.yaw,
                    "pitch_rad": following.pitch,
                    "speed_m_s": state.speed,
                    "yaw_rate_rad_s": yaw_rate,
                    "pitch_rate_rad_s": pitch_rate,
                    "accepted": reason == "ok",
                    "reason": reason,
                    "chord_error_bound_m": bound,
                }
            )
            if reason != "ok":
                break
            state = following
    maximum = 0.0
    chosen = sorted({0, len(trace) // 2, len(trace) - 1}) if trace else []
    for index in chosen:
        row = trace[index]
        reference = rk4_position(
            State(
                row["start_position"],
                row["start_yaw_rad"],
                row["start_pitch_rad"],
                row["speed_m_s"],
            ),
            row["yaw_rate_rad_s"],
            row["pitch_rate_rad_s"],
            dt,
            steps=50,
        )
        maximum = max(maximum, math.dist(reference, row["position"]))
    summary = {
        "case_id": spec["id"],
        "expected": spec["expected"],
        "actual": reason,
        "passed": reason == spec["expected"] and maximum < 1e-10,
        "motion_witness_feasible": reason == "ok",
        "integrated_intervals": len(trace),
        "accepted_intervals": sum(row["accepted"] for row in trace),
        "last_accepted_position": state.position,
        "last_accepted_yaw_rad": state.yaw,
        "last_accepted_pitch_rad": state.pitch,
        "last_candidate_position": trace[-1]["position"] if trace else None,
        "independent_rk4_intervals": len(chosen),
        "maximum_rk4_error_m": maximum,
        "effective_radius_m": radius,
        "goal_semantics": (
            "positive endpoint defines a witness goal, not a searched solution"
        ),
    }
    return summary, trace


def main() -> None:
    """Run the twelve preregistered cases once and write compact public evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage6a"))
    args = parser.parse_args()
    local = args.local_dir.resolve()
    if local.is_relative_to(ROOT):
        raise ValueError("Numeric acceptance evidence must remain outside repository")
    local.mkdir(parents=True, exist_ok=False)
    output = output_directory(args.output)
    protocol = read_config("stage6a_feasibility_protocol.json")
    vehicle = read_config("stage5a_protocol.json")
    rows, records = [], []
    for spec in protocol["cases"]:
        summary, trace = run_case(spec, protocol, vehicle)
        rows.append(summary)
        records.append({"spec": spec, "summary": summary, "trace": trace})
    with gzip.open(local / "acceptance.json.gz", "xt", encoding="utf-8") as stream:
        json.dump(records, stream, allow_nan=False)
    write_csv(output / "feasibility_cases.csv", rows)
    result = {
        "passed": all(row["passed"] for row in rows),
        "cases": len(rows),
        "positive_witnesses": sum(row["motion_witness_feasible"] for row in rows),
        "negative_inputs_or_references": sum(
            not row["motion_witness_feasible"] for row in rows
        ),
        "accepted_intervals": sum(row["accepted_intervals"] for row in rows),
        "independent_rk4_intervals": sum(
            row["independent_rk4_intervals"] for row in rows
        ),
        "maximum_rk4_error_m": max(row["maximum_rk4_error_m"] for row in rows),
        "planner_searches": 0,
        "ompl_native_baseline_executed": False,
    }
    (output / "feasibility_acceptance.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result))
    if not result["passed"]:
        raise RuntimeError(
            "Acceptance failed; preserve evidence and review before expansion"
        )


if __name__ == "__main__":
    main()
