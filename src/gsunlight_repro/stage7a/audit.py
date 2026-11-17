"""Extract observations from preserved native/LOS records, without new execution."""

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
from ..stage6c.common import boolean, read_csv, read_json
from ..stage6d.common import load_record, save_json
from . import BASE, PUBLIC

UNKNOWN = "not_recorded"
ABSENT = "not_observed"


def first_event(
    trace: list[dict[str, Any]],
    kind: str,
    tracking_limit: float = 3.0,
) -> int | str:
    """A missing field is unknown, not evidence that no violation occurred."""
    key = {
        "margin": "margin_reason",
        "physical": "physical_reason",
        "mission": "mission_reason",
        "tracking": "cross_track_m",
        "terminal": "terminal_switch",
        "goal": "goal_distance_after_m",
    }[kind]
    if not trace or any(key not in row for row in trace):
        return UNKNOWN
    for i, row in enumerate(trace):
        if kind == "tracking":
            failed = row[key] > tracking_limit
        elif kind == "terminal":
            failed = bool(row[key])
        elif kind == "goal":
            failed = row[key] <= 0.75
        else:
            failed = row[key] != "ok"
        if failed:
            return i
    return ABSENT


def event_time(trace: list[dict[str, Any]], index: int | str) -> float | str:
    """Report the saved candidate interval endpoint, never a collision instant."""
    return trace[index].get("time_s", UNKNOWN) if isinstance(index, int) else index


def observed_max(trace: list[dict[str, Any]], key: str) -> float | str:
    """Keep absence explicit instead of inventing a zero-valued measurement."""
    if not trace or any(key not in row for row in trace):
        return UNKNOWN
    return max(float(row[key]) for row in trace)


def saturation(trace: list[dict[str, Any]], axis: str) -> int | str:
    """Use recorded flags; do not run or reconstruct an alternative controller."""
    key = axis + "_saturated"
    return (
        sum(bool(r[key]) for r in trace)
        if trace and all(key in r for r in trace)
        else UNKNOWN
    )


def reference(
    input_data: dict[str, Any], native: list[dict[str, Any]]
) -> dict[str, Any]:
    """Reconstruct only the recorded position projection and declared goal bridge."""
    scene = input_data["scenario"]
    points = np.asarray(
        [scene["initial"][:3]] + [r["position"] for r in native], dtype=float
    )
    if len(points) < 2 or not np.isfinite(points).all():
        raise ValueError("Recorded native positions are missing or nonfinite")
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    if np.any(lengths <= 1e-12):
        raise ValueError("Unexpected zero native edges: audit indexing explicitly")
    bridge = np.asarray(scene["goal"], dtype=float) - points[-1]
    bridge_length = float(np.linalg.norm(bridge))
    tangent = points[-1] - points[-2]
    join_angle = (
        math.degrees(
            math.acos(
                float(
                    np.clip(
                        tangent @ bridge / (np.linalg.norm(tangent) * bridge_length),
                        -1,
                        1,
                    )
                )
            )
        )
        if bridge_length > 1e-12
        else ABSENT
    )
    return {
        "points": points,
        "native_chord_length_m": float(lengths.sum()),
        "bridge_length_m": bridge_length,
        "bridge_segment_index": len(lengths),
        "bridge_join_tangent_angle_deg": join_angle,
        "length_with_bridge_m": float(lengths.sum() + bridge_length),
    }


def time_aligned_errors(
    native: list[dict[str, Any]],
    los: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare saved equal-time samples only, without native extrapolation."""
    pairs = min(len(native), len(los))
    if not pairs:
        return {"time_aligned_samples": 0, "max_time_aligned_position_error_m": UNKNOWN}
    errors = []
    for a, b in zip(native[:pairs], los[:pairs], strict=True):
        if not math.isclose(a["time_s"], b["time_s"], rel_tol=0, abs_tol=1e-9):
            raise ValueError(
                "Saved native/LOS clocks do not share the assumed0.1s grid"
            )
        errors.append(math.dist(a["position"], b["position"]))
    return {
        "time_aligned_samples": pairs,
        "max_time_aligned_position_error_m": max(errors),
        "time_alignment_scope": "saved_common_time_domain_only",
    }


def describe(
    job: str,
    source: dict[str, str],
    input_data: dict[str, Any],
    record: dict[str, Any],
    margin: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Keep first strict failure and final stop as separate, auditable observations."""
    native, los, tracking = (
        record["native_trace"],
        record["los_trace"],
        record["tracking"],
    )
    if not native or not los or not record["audit"]["model_feasible"]:
        raise ValueError("A selected execution requires complete preserved traces")
    if len(los) != tracking["steps"]:
        raise ValueError("Saved LOS trace length differs from original summary")
    if tracking["failure_reason"] != source["los_failure_reason"]:
        raise ValueError("CSV and original LOS termination reason disagree")
    ref = reference(input_data, native)
    if not math.isclose(
        ref["bridge_length_m"],
        tracking["reference_bridge_length_m"],
        rel_tol=0,
        abs_tol=1e-10,
    ):
        raise ValueError("Reconstructed bridge differs from saved adapter metadata")
    initial = tracking.get("initial_state")
    same_initial = (
        bool(
            np.allclose(initial, input_data["scenario"]["initial"], rtol=0, atol=1e-12)
        )
        if initial is not None
        else UNKNOWN
    )
    events = {
        kind: first_event(los, kind)
        for kind in ("margin", "physical", "mission", "tracking", "terminal", "goal")
    }
    observed = [
        (i, kind)
        for kind, i in events.items()
        if isinstance(i, int) and kind in ("margin", "physical", "mission", "tracking")
    ]
    earliest = min(observed, default=None)
    first_index = earliest[0] if earliest else None
    first_kinds = (
        "+".join(kind for i, kind in observed if i == first_index)
        if earliest
        else ABSENT
    )
    if any(r.get("reference_progress_m") is None for r in los):
        bridge_entry: int | str = UNKNOWN
    else:
        bridge_entry = next(
            (
                i
                for i, r in enumerate(los)
                if ref["bridge_length_m"] > 1e-12
                and r["reference_progress_m"] >= ref["native_chord_length_m"]
            ),
            ABSENT,
        )
    first = los[first_index] if first_index is not None else None
    if first_index is None or ref["bridge_length_m"] <= 1e-12:
        failure_before_bridge: bool | str = ABSENT
    elif isinstance(bridge_entry, int):
        failure_before_bridge = first_index < bridge_entry
    elif bridge_entry == ABSENT:
        failure_before_bridge = True
    else:
        failure_before_bridge = UNKNOWN
    local_native_gap: float | str = UNKNOWN
    if first is not None and isinstance(first.get("active_segment"), int):
        active = first["active_segment"]
        if 0 <= active < len(native):
            local_native_gap = native[active].get("minimum_gap_lower_bound_m", UNKNOWN)
    mission_min = tracking.get("min_mission_clearance_lower_bound_m", UNKNOWN)
    virtual_error = (
        max(math.dist(r["start_position"], r["reference_position"]) for r in los)
        if all("reference_position" in r for r in los)
        else UNKNOWN
    )
    desired_pitch = (
        max(
            abs(
                math.degrees(
                    math.atan2(
                        r["target"][2] - r["start_position"][2],
                        math.hypot(
                            r["target"][0] - r["start_position"][0],
                            r["target"][1] - r["start_position"][1],
                        ),
                    )
                )
            )
            for r in los
        )
        if all("target" in r for r in los)
        else UNKNOWN
    )
    result = {
        "job_id": job,
        "scenario": source["scenario"],
        "condition": source["condition"],
        "native_seed": int(source["native_seed"]),
        "M_final": True,
        "LOS_strict_success": boolean(source["los_strict_success"]),
        "source_record": f"search/{job}/independent_record.json.gz",
        "data_kind": "read_only_saved_nominal_simulation",
        "same_initial_state": same_initial,
        "native_intervals": len(native),
        "los_intervals": len(los),
        "native_duration_s": native[-1]["time_s"],
        "los_duration_s": los[-1]["time_s"],
        "reported_termination_reason": tracking["failure_reason"],
        "reported_termination_time_s": tracking.get("simulation_time_s", UNKNOWN),
        "earliest_strict_failure_kind": first_kinds,
        "earliest_strict_failure_time_s": event_time(los, first_index)
        if first_index is not None
        else ABSENT,
        "earliest_strict_failure_index": first_index
        if first_index is not None
        else ABSENT,
        **{
            f"first_{kind}_candidate_time_s": event_time(los, i)
            for kind, i in events.items()
        },
        "bridge_length_m": ref["bridge_length_m"],
        "native_chord_length_m": ref["native_chord_length_m"],
        "bridge_join_tangent_angle_deg": ref["bridge_join_tangent_angle_deg"],
        "guide_bridge_entry_time_s": event_time(los, bridge_entry),
        "guide_reached_bridge": (
            True
            if isinstance(bridge_entry, int)
            else False
            if bridge_entry == ABSENT
            else UNKNOWN
        ),
        "first_failure_before_guide_bridge": failure_before_bridge,
        "terminal_mode_at_first_failure": first.get("terminal_mode", UNKNOWN)
        if first
        else ABSENT,
        "native_minimum_required_gap_m": record["audit"].get(
            "minimum_gap_lower_bound_m", UNKNOWN
        ),
        "LOS_minimum_body_mission_gap_m": mission_min,
        "LOS_required_gap_lower_bound_derived_m": mission_min - margin
        if isinstance(mission_min, (int, float))
        else UNKNOWN,
        "native_gap_on_first_failure_active_segment_m": local_native_gap,
        "max_global_path_error_m": observed_max(los, "cross_track_m"),
        "max_virtual_reference_position_error_m": virtual_error,
        "yaw_saturation_steps_recorded": saturation(los, "yaw"),
        "pitch_saturation_steps_recorded": saturation(los, "pitch"),
        "peak_observed_pitch_deg": max(abs(math.degrees(r["pitch_rad"])) for r in los),
        "peak_desired_pitch_deg_derived_from_saved_target": desired_pitch,
        "certified_tracking_tube_radius": UNKNOWN,
        "disturbance_history": UNKNOWN,
        "real_vehicle_execution": UNKNOWN,
        **time_aligned_errors(native, los),
        "derived_scope": (
            "geometry_and_statistics_of_saved_arrays_only_no_new_control_or_plant"
        ),
    }
    event_rows = []
    for kind, index in {**events, "guide_bridge": bridge_entry}.items():
        if isinstance(index, int):
            row = los[index]
            event_rows.append(
                {
                    "job_id": job,
                    "event": kind,
                    "interval_index": index,
                    "interval_start_s": row["time_start_s"],
                    "interval_end_s": row["time_s"],
                    "candidate_x": row["position"][0],
                    "candidate_y": row["position"][1],
                    "candidate_z": row["position"][2],
                    "reference_progress_m": row.get("reference_progress_m", UNKNOWN),
                    "terminal_mode": row.get("terminal_mode", UNKNOWN),
                    "source_pointer": f"los_trace[{index}]",
                    "collision_instant": UNKNOWN,
                }
            )
    return result, event_rows


def native_source_consistency(
    input_data: dict[str, Any],
    output: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    """Match saved controls/nodes to saved dense records without integrating them."""
    controls, states, dense = (
        output["controls"],
        output["states"],
        record["native_trace"],
    )
    if output["status"] != "exact" or len(states) != len(controls) + 1:
        raise ValueError("Selected native source is not an exact PathControl")
    if not record["audit"]["independent_audit_passed"]:
        raise ValueError("The inherited independent certificate did not pass")
    if not np.allclose(
        states[0], input_data["scenario"]["initial"], rtol=0, atol=1e-12
    ):
        raise ValueError("Native output initial state differs from original input")
    cursor = 0
    for index, control in enumerate(controls):
        steps = round(control["duration_s"] / 0.1)
        if steps < 1 or not math.isclose(
            steps * 0.1, control["duration_s"], abs_tol=1e-12
        ):
            raise ValueError("Saved duration is not a positive whole step count")
        for row in dense[cursor : cursor + steps]:
            if (
                row["control_index"] != index
                or not row["accepted"]
                or any(
                    not math.isclose(row[key], control[key], rel_tol=0, abs_tol=1e-12)
                    for key in ("yaw_rate_rad_s", "pitch_rate_rad_s")
                )
            ):
                raise ValueError("Native controls and dense source records disagree")
        cursor += steps
        if (
            cursor > len(dense)
            or math.dist(dense[cursor - 1]["position"], states[index + 1][:3]) > 1e-10
        ):
            raise ValueError("Saved native endpoint differs from output node")
        endpoint = dense[cursor - 1]
        node = states[index + 1]
        yaw_error = math.remainder(endpoint["yaw_rad"] - node[3], 2 * math.pi)
        if (
            max(
                abs(yaw_error),
                abs(endpoint["pitch_rad"] - node[4]),
                abs(endpoint["speed_m_s"] - node[5]),
            )
            > 1e-10
        ):
            raise ValueError("Saved native angle/speed differs from output node")
    if cursor != len(dense):
        raise ValueError("Native control duration and dense record count disagree")
    los = record["los_trace"]
    observed = [
        *los[0]["start_position"],
        los[0]["start_yaw_rad"],
        los[0]["start_pitch_rad"],
        los[0]["speed_m_s"],
    ]
    if not np.allclose(observed, input_data["scenario"]["initial"], rtol=0, atol=1e-12):
        raise ValueError("Actual saved LOS initial state differs from native input")
    differences = {}
    count = min(len(dense), len(los))
    for axis in ("yaw", "pitch"):
        key = axis + "_rate_rad_s"
        differences[f"max_equal_time_{axis}_rate_difference_deg_s"] = max(
            abs(math.degrees(a[key] - b[key]))
            for a, b in zip(dense[:count], los[:count], strict=True)
        )
    return {
        "native_output_nodes": len(states),
        "native_output_controls": len(controls),
        "saved_control_node_correspondence_passed": True,
        "actual_saved_initial_state_matches": True,
        **differences,
    }


def run(raw: Path, output: Path = PUBLIC) -> dict[str, Any]:
    """Read exactly the47 saved M_final executions; never replace them with49."""
    if not output.resolve().is_relative_to(PUBLIC):
        raise ValueError("New audit outputs must remain inside results/stage7a")
    cfg = read_config("stage7a_audit.json")
    sources = [
        r for r in read_csv(ROOT / cfg["source_csv"]) if boolean(r["model_feasible"])
    ]
    if len(sources) != cfg["expected_executions"]:
        raise ValueError("Frozen47-execution denominator changed")
    missing = [
        r["job_id"]
        for r in sources
        if any(
            not (raw / "search" / r["job_id"] / name).is_file()
            for name in ("input.json", "output.json", "independent_record.json.gz")
        )
    ]
    save_json(
        output / "source_availability.json",
        {"expected": 47, "missing": missing, "base_commit": BASE},
    )
    if missing:
        raise FileNotFoundError("Saved raw records missing: " + ", ".join(missing))
    rows, events = [], []
    failure_traces: list[tuple[str, list[dict[str, Any]]]] = []
    equivalence = []
    margin = read_config("stage5a_protocol.json")["vehicle"]["safety_margin_m"]
    for source in sources:
        if not (boolean(source["los_was_run"]) and boolean(source["los_eligible"])):
            raise ValueError("A selected execution does not belong to original E47")
        folder = raw / "search" / source["job_id"]
        input_data = read_json(folder / "input.json")
        output_data = read_json(folder / "output.json")
        stored = load_record(folder / "independent_record.json.gz")
        row, found = describe(
            source["job_id"],
            source,
            input_data,
            stored,
            margin,
        )
        row.update(native_source_consistency(input_data, output_data, stored))
        if not row["LOS_strict_success"]:
            representative = next(
                (job for job, trace in failure_traces if trace == stored["los_trace"]),
                source["job_id"],
            )
            equivalence.append(
                {"job_id": source["job_id"], "identical_saved_los_to": representative}
            )
            failure_traces.append((source["job_id"], stored["los_trace"]))
        rows.append(row)
        events.extend(found)
    failed = [r for r in rows if not r["LOS_strict_success"]]
    if len(failed) != cfg["expected_failures"]:
        raise ValueError("Original15 LOS failures changed")
    write_csv(output / "execution_index.csv", rows)
    write_csv(output / "failure_audit.csv", failed)
    write_csv(output / "event_audit.csv", events)
    write_csv(output / "identical_failure_records.csv", equivalence)
    summary = {
        "executions": len(rows),
        "strict_successes": len(rows) - len(failed),
        "failures": len(failed),
        "distinct_complete_saved_failure_traces": len(
            {r["identical_saved_los_to"] for r in equivalence}
        ),
        "original_termination_counts": dict(
            Counter(r["reported_termination_reason"] for r in failed)
        ),
        "earliest_strict_failure_counts": dict(
            Counter(r["earliest_strict_failure_kind"] for r in failed)
        ),
        "failures_before_guide_bridge": sum(
            r["first_failure_before_guide_bridge"] is True for r in failed
        ),
        "failures_with_terminal_mode_at_first_event": sum(
            r["terminal_mode_at_first_failure"] is True for r in failed
        ),
        "missing_records": [],
        "new_planning_searches": 0,
        "new_control_replays": 0,
        "new_controller_implementations": 0,
    }
    save_json(output / "audit_summary.json", summary)
    return summary


def main() -> None:
    """Require explicit existing raw sources and write only new compact results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().raw_root)))


if __name__ == "__main__":
    main()
