"""Three-denominator, map-clustered paired reporting with missing values intact."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import numpy as np

from ..stage5a.analysis import write_csv
from .storage import Records, public_output

RESERVED = {
    "job_id",
    "scene",
    "family",
    "mode",
    "method",
    "seed",
    "path_id",
    "path_uid",
    "raw_path_id",
    "shortcut_path_id",
    "shortcut_source_id",
    "id",
    "condition_id",
    "variant",
    "version",
    "protocol_id",
}


def flatten(record: dict) -> dict:
    """Protect global pairing identities from imported historical metadata."""
    return {
        "was_run": True,
        **{
            key: value
            for key, value in record["summary"].items()
            if key not in RESERVED
        },
        **record["meta"],
        "history_reused": "history_reference" in record,
        "trace_reused": "trace_reference" in record,
    }


def bootstrap_ratio(numerator: list[int], denominator: list[int]) -> tuple:
    """Resample whole maps; undefined denominators remain undefined."""
    if sum(denominator) == 0:
        return None, None, 0
    rng = np.random.default_rng(65888)
    indices = rng.integers(0, len(numerator), (2000, len(numerator)))
    sums = np.array(denominator)[indices].sum(axis=1)
    values = np.divide(
        np.array(numerator)[indices].sum(axis=1),
        sums,
        out=np.full(len(sums), np.nan),
        where=sums > 0,
    )
    valid = values[np.isfinite(values)]
    low, high = np.quantile(valid, [0.025, 0.975])
    return float(low), float(high), len(valid)


def map_summary(
    planning: list[dict], executions: list[dict], controllers: list[str]
) -> list[dict]:
    """Use the same known-feasible planning denominator across execution pairs."""
    index = {
        (row["job_id"], row["processing"], row["controller"]): row for row in executions
    }
    grouped = defaultdict(list)
    for row in planning:
        grouped[(row["scene"], row["family"], row["method"], row["mode"])].append(row)
    output = []
    for (scene, family, method, mode), group in sorted(grouped.items()):
        known = [
            row
            for row in group
            if row["reachability"].startswith("certified_reachable")
        ]
        for processing in ("raw", "shortcut"):
            for controller in controllers:
                current = [
                    index.get((row["job_id"], processing, controller)) for row in known
                ]
                if any(
                    row is not None
                    and row["eligible"]
                    and not source["geometry_success"]
                    for row, source in zip(current, known, strict=True)
                ):
                    raise ValueError("Execution was credited without geometric output")
                eligible = [
                    row for row in current if row is not None and row["eligible"]
                ]
                successes = sum(row["execution_success"] for row in eligible)
                output.append(
                    {
                        "scene": scene,
                        "family": family,
                        "method": method,
                        "mode": mode,
                        "processing": processing,
                        "controller": controller,
                        "all_planning_tasks": len(group),
                        "known_feasible_tasks": len(known),
                        "envelope_unreachable": sum(
                            row["reachability"].startswith("certified_unreachable")
                            for row in group
                        ),
                        "unknown_tasks": sum(
                            row["reachability"] == "unknown" for row in group
                        ),
                        "geometry_successes": sum(
                            row["geometry_success"] for row in known
                        ),
                        "execution_eligible": len(eligible),
                        "execution_successes": successes,
                        "nominal_successes": sum(
                            row["physical_execution_success"] for row in eligible
                        ),
                        "geometry_rate": sum(row["geometry_success"] for row in known)
                        / len(known)
                        if known
                        else None,
                        "conditional_execution_rate": successes / len(eligible)
                        if eligible
                        else None,
                        "end_to_end_rate": successes / len(known) if known else None,
                        "no_geometry_output": sum(
                            not row["geometry_success"] for row in known
                        ),
                        "failure_counts": dict(
                            Counter(
                                row["primary_class"] if row else "planning_no_path"
                                for row in current
                            )
                        ),
                    }
                )
                result = output[-1]
                times = [
                    row["first_valid_time_s"]
                    for row in known
                    if row["geometry_success"]
                    and row.get("first_valid_time_s") is not None
                ]
                result["mean_first_valid_time_s"] = mean(times) if times else None
                for field in (
                    "length_m",
                    "processing_cost_s",
                    "tracking_wall_s",
                    "simulation_time_s",
                    "final_position_error_m",
                    "max_tracking_error_m",
                    "rms_tracking_error_m",
                    "min_physical_clearance_lower_bound_m",
                    "min_mission_clearance_lower_bound_m",
                    "path_min_mission_clearance_capped_m",
                    "peak_yaw_rate_deg_s",
                    "peak_pitch_rate_deg_s",
                    "peak_pitch_deg",
                ):
                    values = [
                        row[field]
                        for row in eligible
                        if row.get(field) is not None and math.isfinite(row[field])
                    ]
                    result["mean_" + field] = mean(values) if values else None
                steps = sum(row.get("steps", 0) for row in eligible)
                for axis in ("yaw", "pitch"):
                    result[axis + "_saturated_step_fraction"] = (
                        sum(row.get(axis + "_saturation_steps", 0) for row in eligible)
                        / steps
                        if steps
                        else None
                    )
    return output


def cluster_summary(maps: list[dict]) -> list[dict]:
    """Report map means and exploratory map-bootstrap ratio intervals."""
    grouped = defaultdict(list)
    for row in maps:
        grouped[
            (row["method"], row["mode"], row["processing"], row["controller"])
        ].append(row)
    output = []
    for (method, mode, processing, controller), group in sorted(grouped.items()):
        known = [row for row in group if row["known_feasible_tasks"]]
        result = {
            "method": method,
            "mode": mode,
            "processing": processing,
            "controller": controller,
            "independent_maps": len(group),
            "known_feasible_maps": len(known),
            "known_feasible_tasks": sum(row["known_feasible_tasks"] for row in group),
            "geometry_successes": sum(row["geometry_successes"] for row in group),
            "execution_eligible": sum(row["execution_eligible"] for row in group),
            "execution_successes": sum(row["execution_successes"] for row in group),
        }
        for label, nkey, dkey in (
            ("geometry", "geometry_successes", "known_feasible_tasks"),
            ("conditional", "execution_successes", "execution_eligible"),
            ("end_to_end", "execution_successes", "known_feasible_tasks"),
        ):
            numerator, denominator = (
                [row[nkey] for row in known],
                [row[dkey] for row in known],
            )
            low, high, replicates = bootstrap_ratio(numerator, denominator)
            result.update(
                {
                    label + "_ratio": sum(numerator) / sum(denominator)
                    if sum(denominator)
                    else None,
                    label + "_map_mean": mean(
                        row[nkey] / row[dkey] for row in known if row[dkey]
                    )
                    if any(denominator)
                    else None,
                    label + "_ci95_low": low,
                    label + "_ci95_high": high,
                    label + "_valid_bootstrap_replicates": replicates,
                }
            )
        output.append(result)
    return output


def paired_rows(rows: list[dict], selected: str) -> list[dict]:
    """Keep both controller and raw/shortcut contrasts, including losses."""
    index = {(row["job_id"], row["processing"], row["controller"]): row for row in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate task/processing/controller identity")
    output = []
    jobs = sorted({row["job_id"] for row in rows})
    for job in jobs:
        for factor, first, second in (
            ("controller_raw", ("raw", "legacy"), ("raw", selected)),
            ("controller_shortcut", ("shortcut", "legacy"), ("shortcut", selected)),
            ("processing_legacy", ("raw", "legacy"), ("shortcut", "legacy")),
            ("processing_los", ("raw", selected), ("shortcut", selected)),
        ):
            a, b = index.get((job, *first)), index.get((job, *second))
            if a is None or b is None:
                raise ValueError("Missing registered paired condition")
            output.append(
                {
                    "job_id": job,
                    "scene": a["scene"],
                    "family": a["family"],
                    "method": a["method"],
                    "mode": a["mode"],
                    "factor": factor,
                    "reachability": a.get("reachability", "development_only"),
                    "first_success": a["execution_success"],
                    "second_success": b["execution_success"],
                    "delta_success": int(b["execution_success"])
                    - int(a["execution_success"]),
                    "first_class": a["primary_class"],
                    "second_class": b["primary_class"],
                }
            )
    return output


def paired_summary(rows: list[dict]) -> list[dict]:
    """Bootstrap end-to-end paired changes by whole maps, including regressions."""
    grouped = defaultdict(list)
    for row in rows:
        if row["reachability"].startswith("certified_reachable"):
            grouped[(row["method"], row["mode"], row["factor"])].append(row)
    output = []
    for (method, mode, factor), group in sorted(grouped.items()):
        maps = defaultdict(list)
        for row in group:
            maps[row["scene"]].append(row)
        totals = [sum(row["delta_success"] for row in part) for part in maps.values()]
        sizes = [len(part) for part in maps.values()]
        low, high, replicates = bootstrap_ratio(totals, sizes)
        output.append(
            {
                "method": method,
                "mode": mode,
                "factor": factor,
                "known_feasible_maps": len(maps),
                "paired_tasks": len(group),
                "recovered": sum(row["delta_success"] == 1 for row in group),
                "lost": sum(row["delta_success"] == -1 for row in group),
                "both_success": sum(
                    row["first_success"] and row["second_success"] for row in group
                ),
                "both_failure": sum(
                    not row["first_success"] and not row["second_success"]
                    for row in group
                ),
                "end_to_end_delta": sum(totals) / sum(sizes),
                "delta_ci95_low": low,
                "delta_ci95_high": high,
                "valid_bootstrap_replicates": replicates,
            }
        )
    return output


def analyze(local: Path, old: Path, output: Path, complete: bool = False) -> dict:
    """Rebuild public tables without changing a planning or trajectory record."""
    output = public_output(output)
    records = Records(local, old).all()
    rows = [flatten(record) for record in records]
    development = [row for row in rows if row["phase"] == "development"]
    write_csv(output / "development_runs.csv", development)
    dev_groups = defaultdict(list)
    dev_index = {
        (row["job_id"], row["processing"], row["controller"]): row
        for row in development
    }
    for row in development:
        dev_groups[(row["scene"], row["processing"], row["controller"])].append(row)
    dev_summaries = []
    for (scene, processing, controller), group in sorted(dev_groups.items()):
        baseline = [dev_index[(row["job_id"], processing, "legacy")] for row in group]
        dev_summaries.append(
            {
                "scene": scene,
                "family": group[0]["family"],
                "processing": processing,
                "controller": controller,
                "paths": len(group),
                "strict_successes": sum(row["execution_success"] for row in group),
                "nominal_successes": sum(
                    row["physical_execution_success"] for row in group
                ),
                "recovered": sum(
                    row["execution_success"] and not base["execution_success"]
                    for row, base in zip(group, baseline, strict=True)
                ),
                "lost": sum(
                    base["execution_success"] and not row["execution_success"]
                    for row, base in zip(group, baseline, strict=True)
                ),
                "failure_counts": dict(Counter(row["primary_class"] for row in group)),
            }
        )
    write_csv(output / "development_map_summary.csv", dev_summaries)
    selection_path = local / "selection.json"
    selected = (
        json.loads(selection_path.read_text(encoding="utf-8"))["chosen"]["id"]
        if selection_path.exists()
        else None
    )
    if selected:
        paired_dev = [
            row
            for row in development
            if row["processing"] in ("raw", "shortcut")
            and row["controller"] in ("legacy", selected)
        ]
        if paired_dev:
            write_csv(
                output / "development_paired.csv", paired_rows(paired_dev, selected)
            )
    planning = []
    deviation_file = local / "operational_deviation.json"
    deviation = (
        json.loads(deviation_file.read_text(encoding="utf-8"))
        if deviation_file.exists()
        else {}
    )
    for path in sorted((local / "planning").glob("*.json")):
        if path.name.endswith(".processing.json"):
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        planning.append(
            {
                key: value
                for key, value in item.items()
                if key not in ("search", "raw", "first_path", "first_certificate")
            }
            | {
                "geometry_success": item["raw"] is not None,
                "raw_path_id": item["job_id"] + "::raw" if item["raw"] else None,
                **item["search"],
                "known_resource_overlap": item["job_id"]
                in deviation.get("known_planning_overlap_jobs", []),
            }
        )
    write_csv(output / "planning_runs.csv", planning)
    independent = [row for row in rows if row["phase"] == "independent"]
    actual_conditions = len(independent)
    present = {
        (row["job_id"], row["processing"], row["controller"]) for row in independent
    }
    for source in planning:
        for processing in ("raw", "shortcut"):
            for controller in ("legacy", selected):
                key = (source["job_id"], processing, controller)
                if key in present:
                    continue
                if source["geometry_success"]:
                    raise ValueError("A solved task is missing a paired execution")
                independent.append(
                    {
                        "case_id": "--".join(key),
                        "job_id": source["job_id"],
                        "scene": source["scene"],
                        "family": source["family"],
                        "method": source["method"],
                        "mode": source["mode"],
                        "seed": source["seed"],
                        "processing": processing,
                        "controller": controller,
                        "phase": "independent",
                        "was_run": False,
                        "eligible": False,
                        "execution_success": False,
                        "physical_execution_success": False,
                        "primary_class": "envelope_unreachable"
                        if source["reachability"].startswith("certified_unreachable")
                        else "planning_no_path",
                        "path_id": None,
                        "raw_path_id": None,
                        "shortcut_source_id": None,
                    }
                )
    by_job = {row["job_id"]: row for row in planning}
    for row in independent:
        source = by_job[row["job_id"]]
        row.update(
            first_valid_time_s=source["first_valid_time_s"],
            planning_actual_total_s=source["actual_total_s"],
            reachability=source["reachability"],
            job_in_resource_overlap_window=row["job_id"]
            in deviation.get("conservatively_marked_execution_jobs", []),
        )
        post = local / "planning" / (row["job_id"] + ".processing.json")
        row["processing_cost_s"] = (
            json.loads(post.read_text(encoding="utf-8"))["processing_cost_s"]
            if row["processing"] == "shortcut" and row["was_run"]
            else (0.0 if row["was_run"] else None)
        )
    write_csv(output / "execution_runs.csv", independent)
    terminal = []
    for row in independent:
        if row["primary_class"] != "tracking_error_limit":
            continue
        terminal.append(
            {
                **{
                    key: row[key]
                    for key in (
                        "case_id",
                        "scene",
                        "family",
                        "method",
                        "mode",
                        "seed",
                        "controller",
                        "processing",
                    )
                },
                "path_length_m": row["length_m"],
                "nearest_progress_m": row["failure_reference_progress_m"],
                "controller_progress_m": row["failure_controller_progress_m"],
                "nearest_at_endpoint": math.isclose(
                    row["length_m"],
                    row["failure_reference_progress_m"],
                    rel_tol=0,
                    abs_tol=1e-8,
                ),
                "controller_at_endpoint": math.isclose(
                    row["length_m"],
                    row["failure_controller_progress_m"],
                    rel_tol=0,
                    abs_tol=1e-8,
                ),
                "first_failure_time_s": row["first_failure_time_s"],
                "final_position_error_m": row["final_position_error_m"],
            }
        )
    write_csv(output / "terminal_diagnostics.csv", terminal)
    if planning:
        maps = map_summary(planning, independent, ["legacy", selected])
        write_csv(output / "map_summary.csv", maps)
        write_csv(output / "cluster_summary.csv", cluster_summary(maps))
        pairs = paired_rows(independent, selected)
        write_csv(output / "independent_paired.csv", pairs)
        write_csv(output / "paired_cluster_summary.csv", paired_summary(pairs))
        failures = Counter(
            tuple(
                row[key]
                for key in (
                    "scene",
                    "family",
                    "method",
                    "mode",
                    "processing",
                    "controller",
                    "was_run",
                    "primary_class",
                )
            )
            for row in independent
        )
        keys = (
            "scene",
            "family",
            "method",
            "mode",
            "processing",
            "controller",
            "was_run",
            "primary_class",
        )
        write_csv(
            output / "failure_counts.csv",
            [
                {**dict(zip(keys, key, strict=True)), "conditions": value}
                for key, value in sorted(failures.items())
            ],
        )
    accounting = {
        "complete": complete,
        "old_diagnostic_paths": 157,
        "development_condition_records": len(development),
        "independent_planning_trials": len(planning),
        "independent_maps": len({row["scene"] for row in planning}),
        "independent_execution_conditions": actual_conditions,
        "independent_condition_rows": len(independent),
        "not_run_no_path_conditions": len(independent) - actual_conditions,
        "geometry_successes": sum(row["geometry_success"] for row in planning),
        "new_saved_traces": sum(
            "trace" in record
            and "history_reference" not in record
            and "trace_reference" not in record
            for record in records
        ),
        "historical_trace_references": sum(
            "history_reference" in record for record in records
        ),
        "same_trace_references": sum("trace_reference" in record for record in records),
        "additional_unarchived_search_attempts": deviation.get(
            "duplicate_search_attempts", 0
        ),
    }
    if complete and (
        len(planning) != 360 or not (local / "formal_completed.json").exists()
    ):
        raise ValueError("Cannot claim a completed independent matrix")
    (output / "experiment_accounting.json").write_text(
        json.dumps(accounting, indent=2), encoding="utf-8"
    )
    return accounting


def main() -> None:
    """Export actual complete records, with partial status explicit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ae"))
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            analyze(args.local_dir, args.old_evidence, args.output, args.complete)
        )
    )


if __name__ == "__main__":
    main()
