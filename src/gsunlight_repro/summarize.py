"""Aggregate actual trials without treating invalid-path length as quality."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def aggregate(
    rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Summarize by scene/method; missing paths remain unknown, never zero length.

    Diagnostic event labels can coexist in one trial. Their counts measure
    observed events, not isolated causal explanations for failure.
    """
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[(row["scene_id"], row["method"])].append(row)
    summaries, failures = [], []
    for (scene, method), trials in sorted(groups.items()):
        valid = [row for row in trials if row["strict_valid"] == "True"]
        lengths = [float(row["raw_path_length"]) for row in valid]
        times = [
            float(row["search_seconds"]) for row in trials if row["search_seconds"]
        ]
        categories = Counter(
            label for row in trials for label in json.loads(row["failure_categories"])
        )
        terminations = Counter(row["termination_reason"] for row in trials)
        summaries.append(
            {
                "scene_id": scene,
                "method": method,
                "runs": len(trials),
                "reported_successes": sum(
                    row["reported_success"] == "True" for row in trials
                ),
                "reported_unknown": sum(not row["reported_success"] for row in trials),
                "strict_valid_paths": len(valid),
                "strict_invalid_paths": sum(
                    row["strict_valid"] == "False" for row in trials
                ),
                "no_path_evidence": sum(not row["strict_valid"] for row in trials),
                "budget_valid_successes": sum(
                    row["budget_valid_success"] == "True" for row in trials
                ),
                "common_post_valid": sum(
                    row["common_post_valid"] == "True" for row in trials
                ),
                "valid_raw_length_mean": statistics.mean(lengths) if lengths else None,
                "valid_raw_length_sample_std": statistics.stdev(lengths)
                if len(lengths) > 1
                else None,
                "search_seconds_mean_available": statistics.mean(times)
                if times
                else None,
                "search_seconds_observed": len(times),
                "timeouts": sum(row["status"] == "timeout" for row in trials),
                "budget_exhausted": sum(
                    row["status"] == "budget_exhausted" for row in trials
                ),
                "errors": sum(row["status"] in ("error", "crash") for row in trials),
            }
        )
        for category, count in sorted(categories.items()):
            failures.append(
                {
                    "scene_id": scene,
                    "method": method,
                    "kind": "observed_event",
                    "label": category,
                    "run_count": count,
                }
            )
        for reason, count in sorted(terminations.items()):
            failures.append(
                {
                    "scene_id": scene,
                    "method": method,
                    "kind": "termination_reason",
                    "label": reason,
                    "run_count": count,
                }
            )
    return summaries, failures


def main(argv: list[str] | None = None) -> int:
    """Write compact summary and event tables from an existing benchmark CSV."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--failures-output", type=Path, required=True)
    args = parser.parse_args(argv)
    with args.input.open(encoding="utf-8", newline="") as stream:
        summaries, failures = aggregate(list(csv.DictReader(stream)))
    for target, records in ((args.output, summaries), (args.failures_output, failures)):
        if not records:
            raise ValueError("No records to summarize")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
