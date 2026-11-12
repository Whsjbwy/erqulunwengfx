"""Rebuild compact paired tables from immutable full-resolution replay files."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import numpy as np

from ..stage5a.analysis import write_csv
from .evidence import read_manifest


def read_replays(local: Path) -> list[dict]:
    """Read all traces once, rejecting duplicate task/path/condition identities."""
    records = []
    keys = set()
    for path in sorted((local / "replays").glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            item = json.load(stream)
        row = item["summary"]
        key = (row["job_id"], row["variant"], row["path_id"], row["condition_id"])
        if key in keys:
            raise ValueError("Duplicate replay condition")
        keys.add(key)
        records.append(item)
    return records


def paired_sensitivity(rows: list[dict], conditions: list[dict]) -> list[dict]:
    """Keep the entire paired cohort, including failures and negative changes."""
    index = {}
    for row in rows:
        if row["variant"] != "selected":
            continue
        key = (row["job_id"], row["path_id"], row["condition_id"])
        if key in index:
            raise ValueError("Duplicate sensitivity record")
        index[key] = row
    tasks = {(job, path) for job, path, _ in index}
    if len(index) != len(tasks) * len(conditions):
        raise ValueError("Missing paired execution condition")
    output = []
    for job, path in sorted(tasks):
        baseline = index.get((job, path, "baseline"))
        if baseline is None:
            raise ValueError("Missing baseline for paired replay")
        for condition in conditions:
            row = index.get((job, path, condition["id"]))
            if row is None:
                raise ValueError("Missing preregistered condition")
            paired = {
                **row,
                "baseline_class": baseline["primary_class"],
                "baseline_success": baseline["execution_success"],
                "delta_execution_success": int(row["execution_success"])
                - int(baseline["execution_success"]),
                "class_transition": baseline["primary_class"]
                + " -> "
                + row["primary_class"],
            }
            for key in (
                "final_position_error_m",
                "max_tracking_error_m",
                "rms_tracking_error_m",
                "min_physical_clearance_lower_bound_m",
                "min_mission_clearance_lower_bound_m",
                "yaw_saturation_s",
                "pitch_saturation_s",
                "first_failure_time_s",
            ):
                a, b = row.get(key), baseline.get(key)
                paired["delta_" + key] = (
                    a - b if a is not None and b is not None else None
                )
            output.append(paired)
    return output


def condition_summary(rows: list[dict]) -> list[dict]:
    """Count per map and mode, plus explicitly labelled aggregate summaries."""
    groups = defaultdict(list)
    for row in rows:
        for scene in (row["scene"], "ALL"):
            for mode in (row["mode"], "ALL"):
                groups[(row["condition_id"], scene, mode)].append(row)
    output = []
    for (condition, scene, mode), group in sorted(groups.items()):
        by_map = defaultdict(list)
        for row in group:
            by_map[row["scene"]].append(row["execution_success"])
        output.append(
            {
                "condition_id": condition,
                "scene": scene,
                "mode": mode,
                "independent_maps": len(by_map),
                "frozen_planning_outputs": len(group),
                "strict_successes": sum(row["execution_success"] for row in group),
                "nominal_successes": sum(
                    row["physical_execution_success"] for row in group
                ),
                "recovered": sum(row["delta_execution_success"] == 1 for row in group),
                "lost": sum(row["delta_execution_success"] == -1 for row in group),
                "success_rate_map_mean": mean(
                    mean(values) for values in by_map.values()
                ),
                "failure_counts": dict(Counter(row["primary_class"] for row in group)),
                "all_path_mean_max_error_m": mean(
                    row["max_tracking_error_m"] for row in group
                ),
            }
        )
    return output


def rankdata(values: list[float]) -> np.ndarray:
    """Compute average tied ranks without adding a statistics dependency."""
    array = np.array(values)
    order = np.argsort(array, kind="stable")
    result = np.empty(len(array), dtype=float)
    start = 0
    while start < len(array):
        end = start + 1
        while end < len(array) and array[order[end]] == array[order[start]]:
            end += 1
        result[order[start:end]] = (start + end - 1) / 2
        start = end
    return result


def spearman(left: list[float], right: list[float]) -> float | None:
    """Return a descriptive coefficient, undefined for constant data."""
    if len(left) < 3:
        return None
    a, b = rankdata(left), rankdata(right)
    if np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def geometry_associations(rows: list[dict]) -> list[dict]:
    """Report within-map correlations and six-map means without p-values."""
    features = (
        "max_corner_turn_deg",
        "shortest_segment_m",
        "max_segment_pitch_deg",
        "initial_yaw_mismatch_deg",
        "initial_pitch_mismatch_deg",
        "path_min_mission_clearance_capped_m",
        "length_m",
        "nonzero_segments",
    )
    output = []
    for feature in features:
        map_means = []
        for scene in sorted({row["scene"] for row in rows}):
            group = [row for row in rows if row["scene"] == scene]
            valid = [row for row in group if row.get(feature) is not None]
            x = [row[feature] for row in valid]
            y = [float(row["execution_success"]) for row in valid]
            map_means.append((mean(x), mean(y)))
            output.append(
                {
                    "level": "within_map_paths",
                    "scene": scene,
                    "feature": feature,
                    "n": len(valid),
                    "missing": len(group) - len(valid),
                    "feature_mean": mean(x),
                    "success_rate": mean(y),
                    "spearman_with_success": spearman(x, y),
                    "spearman_with_max_error": spearman(
                        x, [row["max_tracking_error_m"] for row in valid]
                    ),
                    "interpretation": "descriptive_no_causal_or_significance_claim",
                }
            )
        output.append(
            {
                "level": "map_means",
                "scene": "ALL",
                "feature": feature,
                "n": len(map_means),
                "missing": 0,
                "spearman_with_success": spearman(
                    [a for a, _ in map_means], [b for _, b in map_means]
                ),
                "interpretation": "six_fixed_maps_not_generalization",
            }
        )
    return output


def shortcut_rows(pairs: list[dict]) -> list[dict]:
    """Validate lineage and flatten both members, keeping geometry failures."""
    output = []
    seen = set()
    for pair in pairs:
        if pair["raw_path_id"] != pair["shortcut_source_id"]:
            raise ValueError("Shortcut pair is not from the same raw path")
        if pair["job_id"] in seen:
            raise ValueError("Duplicate shortcut pair")
        seen.add(pair["job_id"])
        raw, shortened = pair["raw"], pair["shortcut"]
        row = {
            key: raw[key]
            for key in ("job_id", "scene", "family", "mode", "method", "seed")
        }
        row.update(
            {
                key: pair[key]
                for key in (
                    "raw_path_id",
                    "shortcut_source_id",
                    "shortcut_path_id",
                    "source_indices",
                )
            }
        )
        for label, summary in (("raw", raw), ("shortcut", shortened)):
            row.update(
                {
                    label + "_" + key: value
                    for key, value in summary.items()
                    if key
                    not in ("raw_path_id", "shortcut_source_id", "shortcut_path_id")
                }
            )
        for key in (
            "length_m",
            "nonzero_segments",
            "max_corner_turn_deg",
            "shortest_segment_m",
            "path_min_mission_clearance_capped_m",
        ):
            a, b = shortened.get(key), raw.get(key)
            row["delta_" + key] = a - b if a is not None and b is not None else None
        row["delta_execution_success"] = int(shortened["execution_success"]) - int(
            raw["execution_success"]
        )
        row["class_transition"] = (
            raw["primary_class"] + " -> " + shortened["primary_class"]
        )
        row["both_nominal_valid"] = (
            raw["nominal_body_valid"] and shortened["nominal_body_valid"]
        )
        output.append(row)
    return output


def waterfall(items: list[dict]) -> list[dict]:
    """Keep envelope infeasibility, no path, precheck and execution distinct."""
    grouped = defaultdict(list)
    for item in items:
        row = item["row"]
        if row["phase"] == "holdout":
            grouped[(row["geometry_mode"], row["method"])].append(row)
    output = []
    for (mode, method), rows in sorted(grouped.items()):
        output.append(
            {
                "mode": mode,
                "method": method,
                "registered_tasks": len(rows),
                "certified_reachable": sum(
                    row["reachability"].startswith("certified_reachable")
                    for row in rows
                ),
                "certified_unreachable": sum(
                    row["reachability"].startswith("certified_unreachable")
                    for row in rows
                ),
                "geometric_path": sum(row["strict_geometry_valid"] for row in rows),
                "nominal_precheck": sum(
                    row["execution_eligible"] is True for row in rows
                ),
                "actually_tracked": sum(
                    row["execution_eligible"] is True for row in rows
                ),
                "nominal_arrival": sum(
                    row["physical_execution_success"] is True for row in rows
                ),
                "strict_completion": sum(
                    row["execution_success"] is True for row in rows
                ),
            }
        )
    return output


def analyze(local: Path, output: Path) -> dict:
    """Rebuild tables with mandatory complete P0-P3 gates and paired counts."""
    for phase in ("p0", "manifest", "pilot", "p1", "p2", "p3"):
        if not json.loads(
            (local / f"{phase}_completed.json").read_text(encoding="utf-8")
        )["passed"]:
            raise ValueError("Incomplete diagnostic phase")
    configuration = json.loads(
        (local / "configuration.json").read_text(encoding="utf-8")
    )
    protocol = configuration["diagnostic"]
    records = read_replays(local)
    rows = [item["summary"] for item in records]
    paired = paired_sensitivity(rows, protocol["conditions"])
    manifest = read_manifest(output / "sampling_manifest.csv")
    expanded = {row["job_id"] for row in manifest if row["in_expansion"]}
    if {row["job_id"] for row in paired} != expanded:
        raise ValueError("Replay population differs from the frozen manifest")
    pairs = shortcut_rows(
        json.loads((local / "shortcut_pairs.json").read_text(encoding="utf-8"))
    )
    if {row["job_id"] for row in pairs} != expanded:
        raise ValueError("Shortcut population differs from paired sensitivity cohort")
    baseline = [row for row in paired if row["condition_id"] == "baseline"]
    write_csv(output / "sensitivity_paired.csv", paired)
    write_csv(output / "baseline_diagnostics.csv", baseline)
    write_csv(output / "condition_summary.csv", condition_summary(paired))
    write_csv(output / "shortcut_pairs.csv", pairs)
    write_csv(
        output / "path_geometry_associations.csv", geometry_associations(baseline)
    )
    write_csv(
        output / "failure_locations.csv",
        [row for row in paired if not row["execution_success"]],
    )
    counts = Counter(
        (row["condition_id"], row["scene"], row["mode"], row["primary_class"])
        for row in paired
    )
    write_csv(
        output / "failure_counts.csv",
        [
            {"condition_id": c, "scene": s, "mode": m, "primary_class": r, "count": n}
            for (c, s, m, r), n in sorted(counts.items())
        ],
    )
    accounting = {
        "complete": True,
        "original_planning_trials": 450,
        "holdout_planning_trials": 270,
        "independent_maps": 6,
        "pilot_selected_paths": sum(row["is_selected"] for row in manifest),
        "expanded_selected_paths": len(expanded),
        "sensitivity_replays": len(paired),
        "same_source_shortcut_pairs": len(pairs),
        "shortcut_replays": 2 * len(pairs),
        "unique_saved_replays": len(records),
        "actual_integrated_replays": sum(row["eligible"] for row in rows),
        "resource_timeouts": sum(
            row["primary_class"] == "resource_timeout" for row in rows
        ),
        "new_searches": 0,
        "baseline_frozen_and_history_equivalent": len(baseline),
    }
    (output / "experiment_accounting.json").write_text(
        json.dumps(accounting, indent=2), encoding="utf-8"
    )
    return accounting


def main() -> None:
    """Derive public summary tables without altering any replay record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ar"))
    args = parser.parse_args()
    print(json.dumps(analyze(args.local_dir, args.output)))


if __name__ == "__main__":
    main()
