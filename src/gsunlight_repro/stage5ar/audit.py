"""Independent reconstruction of trace metrics and sampled RK4 state steps."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from ..stage5a.tracking import State
from .evidence import protect_output
from .reference import rk4_position
from .replay import classify
from .storage import read_record


def check_trace(record: dict, cfg: dict) -> dict:
    """Check every recorded step and independently integrate first/middle/last."""
    summary, trace = record["summary"], record["trace"]
    if summary["primary_class"] != classify(summary["failure_reason"]):
        raise ValueError("Summary failure category differs from detailed reason")
    if len(trace) != summary["steps"]:
        raise ValueError("Trace step count differs from outcome")
    if not summary["eligible"]:
        if trace:
            raise ValueError("Precheck rejection must not have an integrated trace")
        return {"steps": 0, "rk4_steps": 0, "max_rk4_error_m": 0.0}
    step = cfg["step_s"]
    errors = [row["cross_track_m"] for row in trace]
    reconstructed = {
        "max_tracking_error_m": max(errors, default=0),
        "rms_tracking_error_m": math.sqrt(
            sum(value**2 for value in errors) / len(errors)
        )
        if errors
        else 0,
        "yaw_saturation_steps": sum(row["yaw_saturated"] for row in trace),
        "pitch_saturation_steps": sum(row["pitch_saturated"] for row in trace),
    }
    for key, value in reconstructed.items():
        if not math.isclose(value, summary[key], rel_tol=1e-12, abs_tol=1e-10):
            raise ValueError(f"Trace metric does not reconstruct: {key}")
    for index, row in enumerate(trace):
        if not math.isclose(row["time_s"], (index + 1) * step, abs_tol=1e-10):
            raise ValueError("Trace time sequence changed")
        if index and not np.allclose(
            row["start_position"], trace[index - 1]["position"], rtol=0, atol=1e-12
        ):
            raise ValueError("Trace positions are discontinuous")
        if (
            abs(row["yaw_rate_rad_s"]) > math.radians(cfg["max_yaw_rate_deg_s"]) + 1e-12
            or abs(row["pitch_rate_rad_s"])
            > math.radians(cfg["max_pitch_rate_deg_s"]) + 1e-12
        ):
            raise ValueError("Trace angular rate violates frozen limits")
        if abs(row["pitch_rad"]) > math.radians(cfg["max_pitch_deg"]) + 1e-12:
            raise ValueError("Trace pitch violates frozen limits")
        if index < len(trace) - 1 and (
            row["physical_reason"] != "ok"
            or row["mission_reason"] != "ok"
            or row["cross_track_m"] > cfg["max_cross_track_m"]
        ):
            raise ValueError("Tracker continued after a terminal rejection")
    if summary["execution_success"]:
        if not summary["reached"] or any(row["margin_reason"] != "ok" for row in trace):
            raise ValueError("Strict completion lacks arrival or full margin")
    maximum = 0.0
    selected = sorted({0, len(trace) // 2, len(trace) - 1}) if trace else []
    for index in selected:
        row = trace[index]
        state = State(
            tuple(row["start_position"]),
            row["start_yaw_rad"],
            row["start_pitch_rad"],
            row["speed_m_s"],
        )
        reference = rk4_position(
            state, row["yaw_rate_rad_s"], row["pitch_rate_rad_s"], step, steps=50
        )
        error = float(np.linalg.norm(reference - row["position"]))
        maximum = max(maximum, error)
        if error > 1e-10:
            raise ValueError("Trace step differs from independent RK4 reference")
    return {"steps": len(trace), "rk4_steps": len(selected), "max_rk4_error_m": maximum}


def audit(local: Path, output: Path) -> dict:
    """Reconstruct all trace summaries after P3 without modifying any records."""
    output = protect_output(output)
    if not (local / "p3_completed.json").exists():
        raise ValueError("Complete P3 before final trace audit")
    config = json.loads((local / "configuration.json").read_text(encoding="utf-8"))
    results = []
    referenced = 0
    for path in sorted((local / "replays").glob("*.json.gz")):
        record = read_record(path)
        results.append(
            check_trace(record, config["historical"]["protocol"]["kinematics"])
        )
        referenced += int("trace_reference" in record)
    result = {
        "status": "passed",
        "replay_records_checked": len(results),
        "trace_reference_records": referenced,
        "recorded_steps_checked_including_references": sum(
            row["steps"] for row in results
        ),
        "independent_rk4_steps": sum(row["rk4_steps"] for row in results),
        "maximum_rk4_error_m": max(row["max_rk4_error_m"] for row in results),
        "tolerance_m": 1e-10,
    }
    (output / "trace_audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main() -> None:
    """Validate immutable step traces using the original stated units."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ar"))
    args = parser.parse_args()
    print(json.dumps(audit(args.local_dir, args.output)))


if __name__ == "__main__":
    main()
