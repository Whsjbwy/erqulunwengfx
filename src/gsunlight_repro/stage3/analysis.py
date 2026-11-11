"""Derive diagnostic tables and figures from immutable trial results."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

from ..scenarios import load_scenario
from .plots import plot_incumbents, plot_paths, plot_sensitivity


def path_departure_angles(path: Sequence[Sequence[float]]) -> list[float]:
    """Measure edge angles to the goal direction on an already validated path."""
    if not path:
        return []
    goal = path[-1]
    angles = []
    for first, second in pairwise(path):
        product = math.dist(first, second) * math.dist(first, goal)
        if product == 0:
            continue
        edge = tuple(b - a for a, b in zip(first, second, strict=True))
        target = tuple(g - a for a, g in zip(first, goal, strict=True))
        dot = sum(a * b for a, b in zip(edge, target, strict=True))
        cross = (
            edge[1] * target[2] - edge[2] * target[1],
            edge[2] * target[0] - edge[0] * target[2],
            edge[0] * target[1] - edge[1] * target[0],
        )
        angles.append(math.degrees(math.atan2(math.hypot(*cross), dot)))
    return angles


def completion_metrics(row: dict[str, Any]) -> dict[str, Any]:
    """Derive legacy completion without inventing an unobserved first event."""
    seconds = row.get("search_seconds")
    budget = row.get("time_budget_s")
    known = seconds not in (None, "") and budget not in (None, "")
    valid = row.get("strict_valid") in (True, "True")
    reported = row.get("reported_success") in (True, "True")
    return {
        "budget_valid_success": bool(
            row["status"] == "ok"
            and valid
            and reported
            and float(seconds) <= float(budget)
        )
        if known
        else None,
        "first_event_observed": row.get("time_to_first_valid_path_s") not in (None, ""),
    }


def write_table(path: Path, rows: list[dict]) -> None:
    """Write a derived table preserving nulls and structured metadata explicitly."""
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                k: json.dumps(v, sort_keys=True)
                if isinstance(v, (list, tuple, dict))
                else v
                for k, v in row.items()
            }
            for row in rows
        )


def summarize_phases(output: Path) -> list[dict]:
    """Summarize phase views while retaining unknown metric denominators."""
    summaries = []
    for phase in (
        "s3",
        "capacity",
        "size",
        "astar",
        "sampling",
        "stop",
        "profile",
        "baselines",
        "holdout",
    ):
        source = output / f"{phase}.csv"
        if not source.exists():
            continue
        groups = defaultdict(list)
        for row in csv.DictReader(source.open(encoding="utf-8")):
            groups[
                (
                    row["scene"],
                    row["method"],
                    row.get("parameters"),
                    row.get("time_budget_s"),
                    row.get("max_nodes"),
                    row.get("measurement"),
                )
            ].append(row)
        for key, group in groups.items():
            design_view_rows = len(group)
            group = list({row["job_id"]: row for row in group}.values())
            times = [
                float(r["time_to_first_valid_path_s"])
                for r in group
                if r.get("time_to_first_valid_path_s")
            ]
            lengths = [
                float(r["last_valid_path_length"])
                for r in group
                if r.get("last_valid_path_length")
            ]
            common = [
                float(r["common_post_length"])
                for r in group
                if r.get("common_post_length")
            ]
            completion = [completion_metrics(r)["budget_valid_success"] for r in group]
            summaries.append(
                {
                    "phase": phase,
                    "scene": key[0],
                    "method": key[1],
                    "parameters": key[2],
                    "time_budget_s": key[3],
                    "max_nodes": key[4],
                    "measurement": key[5],
                    "runs": len(group),
                    "design_view_rows": design_view_rows,
                    "valid_by_budget": sum(
                        r.get("valid_solution_found_by_budget") == "True" for r in group
                    )
                    if any(
                        r.get("valid_solution_found_by_budget") in ("True", "False")
                        for r in group
                    )
                    else None,
                    "valid_by_budget_known_runs": sum(
                        r.get("valid_solution_found_by_budget") in ("True", "False")
                        for r in group
                    ),
                    "budget_valid_success": sum(value is True for value in completion)
                    if any(value is not None for value in completion)
                    else None,
                    "budget_completion_known_runs": sum(
                        value is not None for value in completion
                    ),
                    "normal_by30": sum(
                        r.get("normal_completion_by_30s") == "True" for r in group
                    ),
                    "strict_valid": sum(r.get("strict_valid") == "True" for r in group),
                    "first_time_median_s": statistics.median(times) if times else None,
                    "first_time_min_s": min(times) if times else None,
                    "first_time_max_s": max(times) if times else None,
                    "last_length_mean": statistics.mean(lengths) if lengths else None,
                    "common_post_length_mean": statistics.mean(common)
                    if common
                    else None,
                    "generated_candidates": sum(
                        int(r.get("generated_candidates") or 0) for r in group
                    ),
                    "capacity_evicted": sum(
                        int(r.get("capacity_evicted") or 0) for r in group
                    ),
                    "collision_filtered": sum(
                        int(r.get("collision_filtered") or 0) for r in group
                    ),
                    "expanded_nodes": sum(
                        int(r.get("expanded_nodes") or 0) for r in group
                    ),
                    "terminations": dict(
                        Counter(r["termination_reason"] for r in group)
                    ),
                }
            )
    return summaries


def write_candidate_tables(evidence: list[dict], root: Path, output: Path) -> None:
    """Aggregate bounded event logs without interpreting eviction as causality."""
    spatial = Counter()
    event_summaries = []
    for item in evidence:
        path = root / item["job"]["job_id"] / "events.jsonl"
        if not path.exists():
            continue
        by_kind = defaultdict(list)
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            by_kind[event["event"]].append(event)
            if event["event"] in ("evicted", "expanded", "open_at_stop"):
                spatial[
                    (item["job"]["job_id"], event["event"], tuple(event["spatial_bin"]))
                ] += 1
        for kind, events in by_kind.items():
            points = [e["point"] for e in events if "point" in e]
            event_summaries.append(
                {
                    "job_id": item["job"]["job_id"],
                    "parameters": item["job"]["parameters"],
                    "event": kind,
                    "count": len(events),
                    "distinct_capacity_cells": len(
                        {tuple(e["grid"]) for e in events if "grid" in e}
                    ),
                    "min_time_s": min(e["time_s"] for e in events),
                    "max_time_s": max(e["time_s"] for e in events),
                    **{
                        f"{axis}_{bound}": operation(p[i] for p in points)
                        if points
                        else None
                        for i, axis in enumerate("xyz")
                        for bound, operation in (("min", min), ("max", max))
                    },
                }
            )
    write_table(output / "candidate_event_summary.csv", event_summaries)
    write_table(
        output / "candidate_spatial_counts.csv",
        [
            {"job_id": job, "event": event, "spatial_bin": str(cell), "count": count}
            for (job, event, cell), count in sorted(spatial.items())
        ],
    )


def write_profile_tables(evidence: list[dict], rows: list[dict], output: Path) -> None:
    """Compare actual fixed-work controls and exclusive profiling categories."""
    profiles = [
        {
            "job_id": r["job_id"],
            "measurement": r["measurement"],
            "search_seconds": r.get("search_seconds"),
            "expanded_nodes": r.get("expanded_nodes"),
            **(r.get("profiler") or {}),
        }
        for r in rows
        if r["phase"] == "profile"
    ]
    write_table(output / "profiling.csv", profiles)
    controls = {
        item["job"]["measurement"]: item
        for item in evidence
        if item["job"]["phase"] == "profile"
    }
    if set(controls) == {"unobserved", "observed", "profile"}:
        reference = controls["unobserved"]["result"]
        comparison = {
            field + "_equal": all(
                item["result"][field] == reference[field] for item in controls.values()
            )
            for field in (
                "raw_path",
                "status",
                "termination_reason",
                "counters",
                "parameters",
            )
        }
        comparison["call_seconds"] = {
            key: item["row"]["call_seconds"] for key, item in controls.items()
        }
        comparison["note"] = (
            "Fixed-work profiling controls only; timing is not a baseline ranking."
        )
        (output / "profiling_equivalence.json").write_text(
            json.dumps(comparison, indent=2), encoding="utf-8"
        )


def analyze(root: Path, output: Path) -> dict[str, Any]:
    """Aggregate all completed trials; figures always use predeclared seed zero."""
    output.mkdir(parents=True, exist_ok=True)
    evidence = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(root.glob("*/result.json"))
    ]
    rows = []
    scenarios = {}
    for item in evidence:
        row = dict(item["row"])
        scene_key = (item["job"]["map_config"], item["job"]["scene"])
        if scene_key not in scenarios:
            scenarios[scene_key] = load_scenario(Path(scene_key[0]), scene_key[1])
        scenario = scenarios[scene_key]
        row.update(
            start=scenario.start,
            goal=scenario.goal,
            map_seed=scenario.map_seed,
            shape=scenario.grid.shape,
            origin=scenario.grid.origin,
            spacing=scenario.grid.spacing,
            resolved_parameters=item.get("result", {}).get("parameters"),
            planner_events=item.get("result", {}).get("events"),
            result_version=item.get("result", {}).get("version"),
            baseline_version=(
                "stage2-safety-v1"
                if row["method"] == "safety_reference"
                else "stage2-paper-v1"
            )
            if item["job"]["stop_first"]
            else item.get("result", {}).get("version"),
            diagnostic_version="stage3-stop-first-v1"
            if item["job"]["stop_first"]
            else "stage3-unobserved-control-v1"
            if row["measurement"] == "unobserved"
            else "stage3-observer-v1",
            stop_on_first_valid=item["job"]["stop_first"],
            map_config=item["job"]["map_config"],
            **completion_metrics(row),
        )
        rows.append(row)
    write_table(output / "unique_runs.csv", rows)
    summaries = summarize_phases(output)
    write_table(output / "summary.csv", summaries)
    write_table(
        output / "failure_counts.csv",
        [
            {"scene": scene, "method": method, "stop_reason": reason, "count": count}
            for (scene, method, reason), count in Counter(
                (r["scene"], r["method"], r["termination_reason"]) for r in rows
            ).items()
        ],
    )
    write_candidate_tables(evidence, root, output)
    history_rows = [
        {
            "job_id": r["job_id"],
            "scene": r["scene"],
            "method": r["method"],
            "seed": r["seed"],
            **step,
        }
        for r in rows
        for step in r.get("incumbent_history", [])
    ]
    write_table(output / "incumbent_history.csv", history_rows)
    geometry = []
    for item in evidence:
        if item["job"]["parameters"].get("half_cone_degrees") != 45:
            continue
        path = item.get("result", {}).get("raw_path")
        if not path:
            continue
        angles = path_departure_angles(path)
        geometry.append(
            {
                "job_id": item["job"]["job_id"],
                "seed": item["job"]["seed"],
                "edge_departure_angles_degrees": angles,
                "max_angle_degrees": max(angles) if angles else None,
                "edges_above_reference_30_degrees": sum(a > 30 + 1e-6 for a in angles),
                "note": "Post-run geometry only; not a reachability proof",
            }
        )
    write_table(output / "sampling_path_geometry.csv", geometry)
    write_profile_tables(evidence, rows, output)
    plot_incumbents(rows, output)
    plot_sensitivity(summaries, output)
    plot_paths(evidence, root, output)
    totals = {
        "unique_trials": len(rows),
        "phase_view_rows": sum(r["design_view_rows"] for r in summaries),
        "summary_groups": len(summaries),
        "strict_valid_returned_paths": sum(r.get("strict_valid") is True for r in rows),
        "invalid_returned_paths": sum(
            bool(item.get("result", {}).get("raw_path"))
            and item["row"].get("strict_valid") is not True
            for item in evidence
        ),
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "errors": sum(r["status"] in ("error", "hard_timeout") for r in rows),
    }
    (output / "experiment_accounting.json").write_text(
        json.dumps(totals, indent=2), encoding="utf-8"
    )
    return totals


def main() -> None:
    """CLI for rederivable compact tables and fixed-seed figures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage3"))
    args = parser.parse_args()
    print(json.dumps(analyze(args.local_dir, args.output)))


if __name__ == "__main__":
    main()
