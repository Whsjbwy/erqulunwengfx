"""Derive compact auditable tables without modifying trial evidence."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .maps import load_map, map_features, specifications
from .statistics import decide, paired_estimate

COMPARISONS = (
    ("A2", "A1"),
    ("A4", "A3"),
    ("A3", "A1"),
    ("A4", "A2"),
    ("A4", "rrt_restart"),
    ("A1", "rrt_restart"),
    ("rrt_restart", "rrt_first"),
)


def write_table(path: Path, rows: list[dict]) -> None:
    """Serialize structured fields as JSON; retain missing numbers as empty."""
    if not rows:
        return
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                k: json.dumps(v, sort_keys=True, ensure_ascii=False)
                if isinstance(v, (list, tuple, dict))
                else v
                for k, v in row.items()
            }
            for row in rows
        )


def pair_rows(curves: list[dict]) -> list[dict]:
    """Match by scene, seed and actual budget checkpoint, never by successful seed."""
    indexed = {
        (r["scene"], r["seed"], r["method"], r["checkpoint_s"]): r for r in curves
    }
    if len(indexed) != len(curves):
        raise ValueError("Duplicate curve identity")
    rows = []
    for left_method, right_method in COMPARISONS:
        for (scene, seed, method, cutoff), left in indexed.items():
            if method != left_method:
                continue
            right = indexed.get((scene, seed, right_method, cutoff))
            if right is None:
                continue
            joint = left["valid"] and right["valid"]
            rows.append(
                {
                    "comparison": left_method + "_vs_" + right_method,
                    "scene": scene,
                    "seed": seed,
                    "split": left["split"],
                    "family": left["family"],
                    "checkpoint_s": cutoff,
                    "left_valid": left["valid"],
                    "right_valid": right["valid"],
                    "left_length": left["best_length"],
                    "right_length": right["best_length"],
                    "relative_length_gain": (right["best_length"] - left["best_length"])
                    / right["best_length"]
                    if joint
                    else None,
                }
            )
    return rows


def map_summary(curves: list[dict], runs: list[dict]) -> list[dict]:
    """Report each map's coverage beside conditional quality and first-time data."""
    groups = defaultdict(list)
    indexed_runs = {(r["scene"], r["method"], r["seed"]): r for r in runs}
    for row in curves:
        groups[(row["scene"], row["method"], row["checkpoint_s"])].append(row)
    output = []
    for (scene, method, cutoff), group in sorted(groups.items()):
        valid = [r for r in group if r["valid"]]
        native = [indexed_runs[(scene, method, r["seed"])] for r in group]
        first = [
            r["first_valid_time_s"]
            for r in native
            if r["first_valid_time_s"] is not None
        ]
        output.append(
            {
                "scene": scene,
                "split": group[0]["split"],
                "family": group[0]["family"],
                "method": method,
                "checkpoint_s": cutoff,
                "tasks": len(group),
                "valid_tasks": len(valid),
                "rate": len(valid) / len(group),
                "rate_definition": "false_positive_rate"
                if group[0]["split"] == "negative"
                else "valid_solution_rate",
                "mean_length_on_valid": statistics.mean(r["best_length"] for r in valid)
                if valid
                else None,
                "first_time_median_on_solved": statistics.median(first)
                if first
                else None,
                "first_times_observed": len(first),
                "mean_actual_total_s": statistics.mean(
                    r["actual_total_s"] for r in native
                ),
                "mean_oracle_calls": statistics.mean(
                    r["oracle_query_calls"] for r in native
                ),
            }
        )
    return output


def analyze(local: Path, output: Path, *, figures: bool = True) -> dict[str, Any]:
    """Produce design-complete and partial summaries with explicit completeness."""
    output.mkdir(parents=True, exist_ok=True)
    configuration = json.loads(
        (local / "configuration.json").read_text(encoding="utf-8")
    )
    protocol = configuration["protocol"]
    evidence = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(local.glob("*/result.json"))
    ]
    runs = [item["row"] for item in evidence]
    if len({r["job_id"] for r in runs}) != len(runs):
        raise ValueError("Duplicate independent trial")
    curves, history = [], []
    for item in evidence:
        row = item["row"]
        identity = {
            k: row[k]
            for k in ("job_id", "scene", "split", "family", "scale", "method", "seed")
        }
        curves.extend({**identity, **step} for step in item["checkpoints"])
        history.extend({**identity, **event} for event in item["history"])
    expected = {
        (s["id"], method, seed)
        for s in specifications(configuration["maps"])
        for method in protocol["methods"]
        for seed in protocol["planning_seeds"]
    }
    expected.update(
        ("S1", method, seed)
        for method in protocol["angles"]
        for seed in protocol["pilot_seeds"]
    )
    actual = {(r["scene"], r["method"], r["seed"]) for r in runs}
    if actual - expected:
        raise ValueError(
            "Unregistered experimental tasks must not enter primary tables"
        )
    write_table(output / "runs.csv", runs)
    angle_rows = []
    for row in runs:
        if row["method"] in protocol["angles"]:
            theory = protocol["angles"][row["method"]]["theory_rays"]
            angle_rows.append(
                {
                    **row,
                    "theory_rays_per_complete_cone": theory,
                    "theory_distinct_directions_per_cone": theory - 35,
                }
            )
    write_table(output / "angle_controls.csv", angle_rows)
    write_table(output / "anytime_curves.csv", curves)
    write_table(output / "incumbent_history.csv", history)
    write_table(output / "map_level_summary.csv", map_summary(curves, runs))
    failures = []
    for row in runs:
        if row["strict_valid"]:
            reason = (
                "valid_incumbent_at_deadline"
                if row["termination_reason"] == "time_budget"
                else "first_attempt_valid"
            )
        elif row["split"] == "negative":
            reason = "certified_negative_no_false_positive"
        else:
            reason = "budget_or_first_attempt_without_valid_solution"
        failures.append(
            {
                **{
                    k: row[k]
                    for k in (
                        "job_id",
                        "scene",
                        "split",
                        "method",
                        "seed",
                        "attempts",
                        "attempt_terminations",
                        "attempt_statuses",
                        "generated_candidates",
                        "valid_candidates",
                        "collision_filtered",
                        "capacity_evicted",
                        "no_candidate_expansions",
                        "expanded_nodes",
                        "seen_capacity_cells",
                        "spatial_coverage_bins20",
                        "post_interrupted",
                        "invalid_candidates",
                    )
                },
                "trial_classification": reason,
            }
        )
    write_table(output / "failure_audit.csv", failures)
    timing_fields = (
        "job_id",
        "scene",
        "split",
        "method",
        "seed",
        "actual_total_s",
        "deadline_overshoot_s",
        "search_and_bookkeeping_s",
        "external_validation_s",
        "shortcut_s",
        "post_run_audit_s",
        "post_run_diagnostics_s",
        "ray_and_collision_busy_s",
        "logical_ray_queries",
        "physical_ray_evaluations",
        "oracle_query_calls",
        "oracle_queried_segments",
        "initial_rss_bytes",
        "process_peak_rss_bytes",
        "system_cpu_busy_fraction",
        "system_process_count_before",
        "system_process_count_after",
        "scheduling",
    )
    write_table(
        output / "timing_breakdown.csv",
        [{k: r[k] for k in timing_fields} for r in runs],
    )
    pairs = pair_rows(curves)
    write_table(output / "paired_comparisons.csv", pairs)
    complete = actual == expected
    summaries = []
    heldout_expected = sum(
        s["split"] == "holdout" for s in specifications(configuration["maps"])
    ) * len(protocol["planning_seeds"])
    for left, right in COMPARISONS:
        comparison = left + "_vs_" + right
        for cutoff in protocol["checkpoints_s"]:
            selected = [
                p
                for p in pairs
                if p["comparison"] == comparison
                and p["split"] == "holdout"
                and p["checkpoint_s"] == cutoff
            ]
            if len(selected) == heldout_expected:
                summaries.append(
                    {
                        "comparison": comparison,
                        "checkpoint_s": cutoff,
                        **paired_estimate(
                            selected,
                            protocol["bootstrap_repetitions"],
                            protocol["bootstrap_seed"],
                        ),
                    }
                )
    write_table(output / "statistical_summary.csv", summaries)
    primary = next(
        (
            s
            for s in summaries
            if s["comparison"] == "A4_vs_rrt_restart" and s["checkpoint_s"] == 30
        ),
        {},
    )
    invalid = sum(r["invalid_candidates"] for r in runs)
    decision = decide(
        primary, protocol["go_gate"], complete=complete, invalid_paths=invalid
    )
    (output / "decision.json").write_text(
        json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_table(
        output / "map_features.csv",
        [
            map_features(load_map(s["id"], configuration["maps"]))
            for s in specifications(configuration["maps"])
        ],
    )
    accounting = {
        "expected_unique_trials": len(expected),
        "actual_unique_trials": len(actual),
        "complete": complete,
        "accepted_solution_trials": sum(r["strict_valid"] for r in runs),
        "invalid_candidates": invalid,
        "technical_error_records": len(list(local.glob("*/error.json"))),
        "split_trial_counts": dict(Counter(r["split"] for r in runs)),
        "recommendation": decision["recommendation"],
    }
    (output / "experiment_accounting.json").write_text(
        json.dumps(accounting, indent=2), encoding="utf-8"
    )
    if figures and runs:
        from .plots import plot_results

        plot_results(
            evidence, curves, summaries, output, protocol, configuration["maps"]
        )
    return accounting


def main() -> None:
    """CLI for read-only evidence aggregation and reproducible static figures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage4a"))
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()
    print(json.dumps(analyze(args.local_dir, args.output, figures=not args.no_figures)))


if __name__ == "__main__":
    main()
