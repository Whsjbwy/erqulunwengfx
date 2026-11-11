"""Derive transparent coverage, execution failures and prospective step selection."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, stdev

from .maps import body_radius, load_scene, read_config


def write_csv(path: Path, rows: list[dict]) -> None:
    """Serialize compact tables, preserving absent lengths as empty fields."""
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list, tuple))
                    else value
                    for key, value in row.items()
                }
            )


def read_evidence(local: Path) -> list[dict]:
    """Read exactly one immutable result per actual independent trial."""
    evidence = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(local.glob("*/result.json"))
    ]
    identities = [item["row"]["job_id"] for item in evidence]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate independent trial identities")
    return evidence


def choose_steps(evidence: list[dict], protocol: dict) -> dict:
    """Use only development nominal-body data and the preregistered tie rule."""
    rows = [item["row"] for item in evidence]
    development = [row for row in rows if row["phase"] == "development"]
    pilot = [row for row in rows if row["phase"] == "pilot"]
    if (
        len(development) != protocol["expected_development_trials"]
        or len(pilot) != protocol["expected_pilot_trials"]
    ):
        raise ValueError(
            "Selection requires all135 functional and45 development trials"
        )
    if any(row["phase"] == "holdout" for row in rows):
        raise ValueError("Do not select parameters after a held-out result exists")
    selected = {"rrt_connect": protocol["default_step_m"]}
    details = {}
    for method in ("rrt_star", "informed_rrt_star"):
        groups = {
            step: {
                (row["scene"], row["seed"]): row
                for row in development
                if row["method"] == method and row["step_m"] == step
            }
            for step in protocol["development_steps_m"]
        }
        if any(len(group) != 9 for group in groups.values()):
            raise ValueError("Development method/step tasks are incomplete")
        baseline, alternate = groups[5], groups[3]
        count5 = sum(row["strict_geometry_valid"] for row in baseline.values())
        count3 = sum(row["strict_geometry_valid"] for row in alternate.values())
        paired: dict[str, list[float]] = defaultdict(list)
        for key in baseline:
            if (
                baseline[key]["strict_geometry_valid"]
                and alternate[key]["strict_geometry_valid"]
            ):
                paired[key[0]].append(
                    alternate[key]["best_length"] - baseline[key]["best_length"]
                )
        difference = (
            mean(mean(values) for values in paired.values()) if paired else None
        )
        selected[method] = (
            3
            if count3 > count5
            or (count3 == count5 and difference is not None and difference < -1e-9)
            else 5
        )
        details[method] = {
            "step3_valid": count3,
            "step5_valid": count5,
            "paired_map_mean_length3_minus5_m": difference,
            "joint_tasks": sum(len(v) for v in paired.values()),
        }
    negative = [
        row for row in rows if row["reachability"].startswith("certified_unreachable")
    ]
    open_rows = [row for row in pilot if row["family"] == "empty"]
    gate = (
        all(not row["strict_geometry_valid"] for row in negative)
        and all(row["execution_success"] for row in open_rows)
        and all(row["execution_reason"] != "execution_resource_timeout" for row in rows)
    )
    return {
        "selection_scope": "Complete pilot/development only; no held-out outcomes",
        "resource_gate_passed": gate,
        "steps_m": selected,
        "development_comparisons": details,
        "pilot_trials": len(pilot),
        "development_trials": len(development),
        "known_negative_false_positives": sum(
            row["strict_geometry_valid"] for row in negative
        ),
        "maximum_planning_peak_rss_bytes": max(
            row["planning_peak_rss_bytes"] for row in rows
        ),
        "maximum_tracking_wall_s_per_trial": max(
            row["tracking_wall_s"] for row in rows
        ),
        "maximum_planning_overshoot_s": max(
            row["deadline_overshoot_s"] for row in rows
        ),
        "formal_maps": 6,
        "formal_seeds_per_map": 5,
        "formal_trials": 270,
        "formal_budget_s": 30,
        "planning_budget_upper_total_s": 8100,
        "core_commit": "2096266",
    }


def summaries(rows: list[dict]) -> list[dict]:
    """Keep geometric coverage and conditional execution denominators adjacent."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if row["phase"] == "holdout":
            groups[
                (row["scene"], row["family"], row["geometry_mode"], row["method"])
            ].append(row)
    output = []
    for (scene, family, mode, method), group in sorted(groups.items()):
        solved = [row for row in group if row["strict_geometry_valid"]]
        eligible = [row for row in group if row["execution_eligible"]]
        lengths = [row["best_length"] for row in solved]
        output.append(
            {
                "scene": scene,
                "family": family,
                "geometry_mode": mode,
                "method": method,
                "trials": len(group),
                "reachability": group[0]["reachability"],
                "reported_solutions": sum(row["reported_success"] for row in group),
                "geometric_solutions": len(solved),
                "nominal_body_valid": sum(
                    row["nominal_body_valid"] is True for row in group
                ),
                "nominal_margin_valid": sum(
                    row["nominal_margin_valid"] is True for row in group
                ),
                "execution_eligible": len(eligible),
                "execution_successes": sum(
                    row["execution_success"] is True for row in group
                ),
                "physical_execution_successes": sum(
                    row["physical_execution_success"] is True for row in group
                ),
                "execution_rate_of_eligible": mean(
                    row["execution_success"] for row in eligible
                )
                if eligible
                else None,
                "first_time_median_s_solved_only": median(
                    row["first_valid_time_s"] for row in solved
                )
                if solved
                else None,
                "best_length_mean_solved_only": mean(lengths) if lengths else None,
                "best_length_sample_std_solved_only": stdev(lengths)
                if len(lengths) > 1
                else None,
                "actual_planning_mean_s": mean(row["actual_total_s"] for row in group),
                "queries_mean": mean(row["query_calls"] for row in group),
                "tracking_wall_mean_s": mean(row["tracking_wall_s"] for row in group),
            }
        )
    return output


def paired_rows(rows: list[dict]) -> list[dict]:
    """Retain failed pairs; length comparisons exist only for joint solutions."""
    grouped: dict[tuple, dict] = defaultdict(dict)
    for row in rows:
        if row["phase"] == "holdout":
            grouped[(row["scene"], row["geometry_mode"], row["seed"])][
                row["method"]
            ] = row
    pairs = [
        ("rrt_star", "rrt_connect"),
        ("informed_rrt_star", "rrt_connect"),
        ("informed_rrt_star", "rrt_star"),
    ]
    output = []
    for (scene, mode, seed), methods in sorted(grouped.items()):
        for left, right in pairs:
            if left not in methods or right not in methods:
                continue
            a, b = methods[left], methods[right]
            joint = a["strict_geometry_valid"] and b["strict_geometry_valid"]
            output.append(
                {
                    "scene": scene,
                    "family": a["family"],
                    "geometry_mode": mode,
                    "reachability": a["reachability"],
                    "seed": seed,
                    "left": left,
                    "right": right,
                    "left_geometry": a["strict_geometry_valid"],
                    "right_geometry": b["strict_geometry_valid"],
                    "left_execution": a["execution_success"],
                    "right_execution": b["execution_success"],
                    "joint_geometry": joint,
                    "length_reduction_left_relative_right": (
                        b["best_length"] - a["best_length"]
                    )
                    / b["best_length"]
                    if joint
                    else None,
                }
            )
    return output


def paired_map_summary(pairs: list[dict]) -> list[dict]:
    """Average paired gains within maps before comparing maps of each family."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for row in pairs:
        grouped[
            (
                row["scene"],
                row["family"],
                row["geometry_mode"],
                row["left"],
                row["right"],
            )
        ].append(row)
    output = []
    for (scene, family, mode, left, right), group in sorted(grouped.items()):
        joint = [row for row in group if row["joint_geometry"]]
        output.append(
            {
                "scene": scene,
                "family": family,
                "geometry_mode": mode,
                "left": left,
                "right": right,
                "reachability": group[0]["reachability"],
                "pairs": len(group),
                "joint_valid_pairs": len(joint),
                "left_geometric_rate": mean(row["left_geometry"] for row in group),
                "right_geometric_rate": mean(row["right_geometry"] for row in group),
                "left_execution_rate_all_tasks": mean(
                    row["left_execution"] is True for row in group
                ),
                "right_execution_rate_all_tasks": mean(
                    row["right_execution"] is True for row in group
                ),
                "mean_relative_length_gain_joint_only": mean(
                    row["length_reduction_left_relative_right"] for row in joint
                )
                if joint
                else None,
            }
        )
    return output


def analyze(local: Path, output: Path) -> dict:
    """Derive small public tables; never write to any original result.json."""
    evidence = read_evidence(local)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    histories, curves, executions = [], [], []
    for item in evidence:
        row = item["row"]
        row = {**row, **{"c_" + key: value for key, value in row["counters"].items()}}
        rows.append(row)
        identity = {
            key: row[key]
            for key in (
                "job_id",
                "scene",
                "family",
                "phase",
                "geometry_mode",
                "method",
                "seed",
            )
        }
        for history_name in ("history", "raw_history"):
            histories.extend(
                {**identity, "history_type": history_name, **event}
                for event in item[history_name]
            )
        curves.extend({**identity, **point} for point in item["checkpoints"])
        for path_id, execution in item["executions"].items():
            executions.append(
                {
                    **identity,
                    "path_id": int(path_id),
                    "is_selected": int(path_id) == row["selected_path_id"],
                    "is_raw_best": int(path_id) == row["raw_path_id"],
                    **{
                        key: value
                        for key, value in execution.items()
                        if key != "trajectory"
                    },
                }
            )
    write_csv(output / "runs.csv", rows)
    write_csv(output / "incumbent_history.csv", histories)
    write_csv(output / "anytime_curves.csv", curves)
    write_csv(output / "executions.csv", executions)
    write_csv(output / "map_summary.csv", summaries(rows))
    pairs = paired_rows(rows)
    write_csv(output / "paired_comparisons.csv", pairs)
    write_csv(output / "paired_map_summary.csv", paired_map_summary(pairs))
    failures = []
    for row in rows:
        category = (
            "executed"
            if row["execution_success"]
            else "geometry_infeasible_envelope"
            if row["reachability"].startswith("certified_unreachable")
            else "planning_budget_no_path"
            if not row["strict_geometry_valid"]
            else row["execution_reason"]
        )
        failures.append(
            {
                key: row.get(key)
                for key in (
                    "job_id",
                    "phase",
                    "scene",
                    "family",
                    "method",
                    "geometry_mode",
                    "seed",
                    "reachability",
                    "reported_success",
                    "strict_geometry_valid",
                    "nominal_body_valid",
                    "execution_eligible",
                    "execution_success",
                    "termination_reason",
                    "execution_reason",
                    "actual_total_s",
                    "tracking_wall_s",
                    "counters",
                )
            }
            | {"failure_category": category}
        )
    write_csv(output / "failure_log.csv", failures)
    counts = Counter(
        (
            row["phase"],
            row["family"],
            row["method"],
            row["geometry_mode"],
            row["failure_category"],
        )
        for row in failures
    )
    write_csv(
        output / "failure_counts.csv",
        [
            {
                "phase": key[0],
                "family": key[1],
                "method": key[2],
                "geometry_mode": key[3],
                "category": key[4],
                "count": value,
            }
            for key, value in sorted(counts.items())
        ],
    )
    phase_counts = Counter(row["phase"] for row in rows)
    negative = [
        row for row in rows if row["reachability"].startswith("certified_unreachable")
    ]
    accounting = {
        "actual_independent_trials": len(rows),
        "phase_counts": dict(phase_counts),
        "expected_phase_counts": {"pilot": 135, "development": 45, "holdout": 270},
        "complete": dict(phase_counts)
        == {"pilot": 135, "development": 45, "holdout": 270},
        "technical_errors": len(list(local.glob("*/error.json"))),
        "known_negative_trials": len(negative),
        "known_negative_false_positives": sum(
            row["strict_geometry_valid"] for row in negative
        ),
        "accepted_geometry_trials": sum(row["strict_geometry_valid"] for row in rows),
        "note": (
            "Mixed phases/radii/negative cases; "
            "do not interpret this total as one success rate"
        ),
    }
    (output / "experiment_accounting.json").write_text(
        json.dumps(accounting, indent=2), encoding="utf-8"
    )
    return accounting


def export_map_features(local: Path, output: Path) -> None:
    """Describe frozen geometry and scale proofs without publishing voxel copies."""
    config = json.loads((local / "configuration.json").read_text(encoding="utf-8"))
    protocol = config["protocol"]
    radius = body_radius(protocol)
    rows = []
    for spec in config["maps"]["maps"]:
        scene = load_scene(spec["id"], config["maps"])
        rows.append(
            {
                **spec,
                "shape": scene.grid.shape,
                "spacing": scene.grid.spacing,
                "start": scene.start,
                "goal": scene.goal,
                "task_class": "near_seabed"
                if spec["family"] == "near_seabed"
                else "general_3d",
                "physical_occupied_fraction": float(scene.grid.occupancy.mean()),
                "mission_ceiling_fraction": float(scene.ceiling.occupancy.mean())
                if scene.ceiling
                else None,
                "point_reachability": scene.reachability(0),
                "body_reachability": scene.reachability(radius),
                "margin_reachability": scene.reachability(
                    radius + protocol["vehicle"]["safety_margin_m"]
                ),
                "seabed_height_min_m": float(scene.heights.min())
                if scene.heights is not None
                else None,
                "seabed_height_max_m": float(scene.heights.max())
                if scene.heights is not None
                else None,
            }
        )
    write_csv(output / "map_features.csv", rows)


def main() -> None:
    """Analyze actual completed records or freeze development-only step choices."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5a"))
    parser.add_argument("--select", type=Path)
    parser.add_argument("--figures", action="store_true")
    args = parser.parse_args()
    if args.select:
        if list(args.local_dir.glob("*/error.json")):
            raise ValueError("Resolve recorded technical errors before selection")
        selection = choose_steps(
            read_evidence(args.local_dir), read_config("stage5a_protocol.json")
        )
        with args.select.open("x", encoding="utf-8") as stream:
            json.dump(selection, stream, ensure_ascii=False, indent=2)
        print(json.dumps(selection, ensure_ascii=False))
    else:
        print(json.dumps(analyze(args.local_dir, args.output)))
        export_map_features(args.local_dir, args.output)
        if args.figures:
            from .plots import plot_results

            config = json.loads(
                (args.local_dir / "configuration.json").read_text(encoding="utf-8")
            )
            plot_results(read_evidence(args.local_dir), config, args.output)


if __name__ == "__main__":
    main()
