"""Read-only terminal-state evidence, without new simulations or parameter search."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import numpy as np

from ..stage5a.analysis import write_csv
from ..stage5a.tracking import wrap
from ..stage5ae.runtime import experiment_lock
from .storage import Records, public_output


def goal_alignment(event: dict, goal: list) -> dict:
    """Distinguish the desired bearing from actual bounded-vehicle velocity."""
    offset = np.array(goal) - event["start_position"]
    distance = float(np.linalg.norm(offset))
    yaw, pitch = event["start_yaw_rad"], event["start_pitch_rad"]
    velocity_direction = np.array(
        [
            math.cos(pitch) * math.cos(yaw),
            math.cos(pitch) * math.sin(yaw),
            math.sin(pitch),
        ]
    )
    desired_yaw = math.atan2(offset[1], offset[0])
    desired_pitch = math.atan2(offset[2], math.hypot(offset[0], offset[1]))
    return {
        "goal_distance_m": distance,
        "actual_velocity_goal_cosine": float(velocity_direction @ offset / distance)
        if distance
        else None,
        "yaw_bearing_error_deg": abs(math.degrees(wrap(desired_yaw - yaw))),
        "pitch_bearing_error_deg": abs(math.degrees(desired_pitch - pitch)),
        "goal_bearing_pitch_deg": math.degrees(desired_pitch),
        "actual_pitch_deg": math.degrees(pitch),
    }


def terminal_row(record: dict, goal: list) -> dict:
    """Retain preterminal failures and measured switch states, including no switch."""
    summary, trace = record["summary"], record["trace"]
    switch = summary["terminal_switch_index"]
    failure_time = summary.get("first_failure_time_start_s")
    switch_time = summary["terminal_switch_time_s"]
    row = {
        **record["meta"],
        "execution_success": summary["execution_success"],
        "primary_class": summary["primary_class"],
        "terminal_activated": switch is not None,
        "terminal_switch_index": switch,
        "terminal_switch_time_s": switch_time,
        "first_failure_phase": None
        if failure_time is None
        else "preterminal"
        if switch_time is None or failure_time < switch_time
        else "terminal",
        **{
            field: summary.get(field)
            for field in (
                "terminal_switches",
                "maximum_switch_jump_deg",
                "terminal_distance_increase_steps",
                "minimum_terminal_goal_cosine",
                "final_position_error_m",
                "max_tracking_error_m",
                "last_reference_progress_m",
                "failure_local_reference_gap_m",
                "failure_nearest_error_m",
                "max_corner_turn_deg",
                "max_segment_pitch_deg",
                "initial_yaw_mismatch_deg",
                "initial_pitch_mismatch_deg",
                "yaw_saturation_steps",
                "pitch_saturation_steps",
            )
        },
    }
    if switch is not None:
        if not 0 <= switch < len(trace):
            raise ValueError("Terminal switch lies outside the actual trace")
        row.update(
            {
                "switch_" + key: value
                for key, value in goal_alignment(trace[switch], goal).items()
            }
        )
        row["minimum_terminal_distance_m"] = min(
            row["switch_goal_distance_m"],
            min(math.dist(event["position"], goal) for event in trace[switch:]),
        )
    return row


def diagnose(local: Path, old: Path, ar: Path, output: Path) -> int:
    """Export one compact row per corrected condition, keeping all failures."""
    if not (local / "formal_completed.json").exists():
        raise ValueError("Finish the full prospective matrix before diagnostics")
    records = Records(local, old, ar)
    rows, goals = [], {}
    for file in sorted(records.directory.glob("*.json.gz")):
        with gzip.open(file, "rt", encoding="utf-8") as stream:
            head = json.load(stream)
        meta = head["meta"]
        if meta["controller"] != "los_terminal_v1":
            continue
        job = meta["job_id"]
        if job not in goals:
            directory = old if meta["phase"] == "development" else local
            plan = json.loads(
                (directory / "planning" / (job + ".json")).read_text(encoding="utf-8")
            )
            goals[job] = plan["raw"][-1]
        rows.append(terminal_row(records.read(meta["case_id"]), goals[job]))
    write_csv(public_output(output) / "terminal_mechanisms.csv", rows)
    return len(rows)


def main() -> None:
    """Serialize completed-evidence diagnostics under the experiment lock."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--ar-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5af"))
    args = parser.parse_args()
    with experiment_lock(args.local_dir):
        print(
            json.dumps(
                {
                    "terminal_conditions": diagnose(
                        args.local_dir, args.old_evidence, args.ar_evidence, args.output
                    )
                }
            )
        )


if __name__ == "__main__":
    main()
