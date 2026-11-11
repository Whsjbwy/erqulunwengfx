"""Revalidate original snapshots, time provenance and deterministic executions."""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path

from ..metrics import endpoints_match, path_length
from ..stage4a.runtime import configure_worker
from .analysis import read_evidence, write_csv
from .maps import Scene, body_radius, load_scene, read_config
from .tracking import track


def check_record(item: dict, scene: Scene, protocol: dict) -> Counter:
    """Fail closed on any unsafe path, inconsistent history or success flag."""
    row, paths = item["row"], item["paths"]
    counters = Counter(trials=1)
    geometry = scene.geometry(row["radius_m"])
    for path in paths:
        if not geometry.path(path).valid or not endpoints_match(
            path, scene.start, scene.goal
        ):
            raise ValueError("Archived path failed finite-body endpoint/geometry audit")
        counters["path_entries"] += 1
    used = set()
    for name in ("history", "raw_history"):
        previous_time, previous_length = -1.0, math.inf
        for event in item[name]:
            if (
                not previous_time <= event["time_s"] <= row["time_budget_s"]
                or not event["length"] < previous_length
            ):
                raise ValueError("Nonmonotone or late certificate")
            path_id = event["path_id"]
            if not 0 <= path_id < len(paths) or not math.isclose(
                path_length(paths[path_id]),
                event["length"],
                rel_tol=1e-12,
                abs_tol=1e-9,
            ):
                raise ValueError("Certificate refers to an absent path or wrong length")
            used.add(path_id)
            previous_time, previous_length = event["time_s"], event["length"]
            counters["history_events"] += 1
    if used != set(range(len(paths))):
        raise ValueError("An archived path lacks certification provenance")
    if row["strict_geometry_valid"] != bool(item["history"]):
        raise ValueError("Geometric success disagrees with certified history")
    first = item["raw_history"][0]["time_s"] if item["raw_history"] else None
    if row["first_valid_time_s"] != first:
        raise ValueError("First-solution time was changed")
    for prefix, history in (
        ("raw", item["raw_history"]),
        ("selected", item["history"]),
    ):
        if row[prefix + "_path_id"] != (history[-1]["path_id"] if history else None):
            raise ValueError("Selected path is not the recorded incumbent")
    if not math.isclose(
        row["actual_total_s"],
        sum(
            row[key]
            for key in ("search_and_bookkeeping_s", "validation_s", "shortcut_s")
        ),
        abs_tol=1e-8,
    ):
        raise ValueError("Planning time accounting does not sum to the total")
    for checkpoint in item["checkpoints"]:
        eligible = [
            event
            for event in item["history"]
            if event["time_s"] <= checkpoint["checkpoint_s"]
        ]
        if checkpoint["valid"] != bool(eligible) or checkpoint["best_length"] != (
            eligible[-1]["length"] if eligible else None
        ):
            raise ValueError("Checkpoint was backfilled or lost a certified solution")
        counters["checkpoints"] += 1
    body = body_radius(protocol)
    for path_id, execution in item["executions"].items():
        counters["executions"] += 1
        if execution["execution_success"]:
            if (
                not execution["physical_execution_success"]
                or not scene.geometry(body).path(paths[int(path_id)]).valid
            ):
                raise ValueError(
                    "Execution success lacks nominal-body geometric eligibility"
                )
            margin = (
                protocol["vehicle"]["safety_margin_m"]
                if row["geometry_mode"] == "margin"
                else 0
            )
            if (
                execution["min_physical_clearance_lower_bound_m"] < margin - 1e-9
                or execution["min_mission_clearance_lower_bound_m"] < margin - 1e-9
            ):
                raise ValueError(
                    "Successful execution lacks the required continuous clearance"
                )
            if any(
                execution[key]
                for key in (
                    "rate_limit_violations",
                    "pitch_limit_violations",
                    "speed_limit_violations",
                )
            ):
                raise ValueError("Successful execution violated an input/state limit")
            if (
                execution["final_position_error_m"]
                > protocol["kinematics"]["goal_tolerance_m"]
            ):
                raise ValueError("Successful execution did not reach the position goal")
            counters["accepted_executions"] += 1
    selected = item["executions"].get(str(row["selected_path_id"]))
    if row["execution_success"] != (
        selected["execution_success"] if selected else None
    ):
        raise ValueError("Summary changed the selected path's execution outcome")
    return counters


def expected_identities(config: dict, selected: dict) -> set[str]:
    """Enumerate all predeclared combinations, including every negative seed."""
    protocol = config["protocol"]
    identities = set()
    for spec in config["maps"]["maps"]:
        phase = spec["split"]
        seeds = (
            protocol["planning_seeds"]
            if phase == "holdout"
            else protocol["pilot_seeds"]
        )
        modes = ["body"] if phase == "development" else protocol["geometry_modes"]
        for method in protocol["methods"]:
            steps = (
                protocol["development_steps_m"]
                if phase == "development" and method != "rrt_connect"
                else [
                    selected["steps_m"][method]
                    if phase == "holdout"
                    else protocol["default_step_m"]
                ]
            )
            for seed in seeds:
                for mode in modes:
                    for step in steps:
                        identities.add(
                            f"{phase}_{spec['id']}_{method}_{mode}_seed{seed}_step{step:g}"
                        )
    return identities


def audit(local: Path, output: Path, *, replay_selected: bool = False) -> dict:
    """Recheck the complete original matrix without changing its result files."""
    configure_worker()
    config = json.loads((local / "configuration.json").read_text(encoding="utf-8"))
    evidence = read_evidence(local)
    expected = expected_identities(config, read_config("stage5a_selected.json"))
    if {item["row"]["job_id"] for item in evidence} != expected or len(evidence) != 450:
        raise ValueError("Final audit requires the complete450 registered tasks")
    if list(local.glob("*/error.json")):
        raise ValueError("Unresolved technical errors prevent a final safety audit")
    counters: Counter = Counter()
    scenes: dict[str, Scene] = {}
    replay_rows = []
    for item in evidence:
        row = item["row"]
        scene_id = row["scene"]
        if scene_id not in scenes:
            scenes[scene_id] = load_scene(scene_id, config["maps"])
        scene = scenes[scene_id]
        counters.update(check_record(item, scene, config["protocol"]))
        reachability = scene.reachability(row["radius_m"])
        if reachability != row["reachability"] or (
            reachability.startswith("certified_unreachable")
            and row["strict_geometry_valid"]
        ):
            raise ValueError(
                "Scale feasibility certificate was contradicted or changed"
            )
        if replay_selected and row["selected_path_id"] is not None:
            path_id = row["selected_path_id"]
            original = item["executions"][str(path_id)]
            margin = (
                config["protocol"]["vehicle"]["safety_margin_m"]
                if row["geometry_mode"] == "margin"
                else 0
            )
            started = time.perf_counter()
            replay = track(item["paths"][path_id], scene, config["protocol"], margin)
            for key in (
                "eligible",
                "execution_success",
                "physical_execution_success",
                "failure_reason",
                "steps",
                "rate_limit_violations",
                "pitch_limit_violations",
                "speed_limit_violations",
                "yaw_saturation_steps",
                "pitch_saturation_steps",
            ):
                if original.get(key) != replay.get(key):
                    raise ValueError(
                        f"Execution replay disagrees on {key}: {row['job_id']}"
                    )
            for key in (
                "min_physical_clearance_lower_bound_m",
                "min_mission_clearance_lower_bound_m",
                "max_tracking_error_m",
                "final_position_error_m",
            ):
                if key in original and not math.isclose(
                    original[key], replay[key], abs_tol=1e-9
                ):
                    raise ValueError(f"Execution replay changed {key}: {row['job_id']}")
            replay_rows.append(
                {
                    "job_id": row["job_id"],
                    "path_id": path_id,
                    "same_outcome_and_metrics": True,
                    "replay_wall_s": time.perf_counter() - started,
                }
            )
    result = {
        **dict(counters),
        "replayed_selected_paths": len(replay_rows),
        "invalid_paths": 0,
        "late_certificates": 0,
        "execution_flag_inconsistencies": 0,
        "status": "passed",
    }
    if replay_selected:
        write_csv(output / "execution_replay.csv", replay_rows)
    (output / "certificate_audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main() -> None:
    """Run an additional audit outside all original planning budgets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5a"))
    parser.add_argument("--replay-selected", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            audit(args.local_dir, args.output, replay_selected=args.replay_selected)
        )
    )


if __name__ == "__main__":
    main()
