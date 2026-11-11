"""Check public synthetic experiment provenance and metric consistency."""

import csv
import json
from itertools import pairwise
from pathlib import Path


def read_rows(name: str) -> list[dict[str, str]]:
    """Read a committed compact table without private author materials."""
    with (Path("results/stage3") / name).open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_phase_views_reference_exact_unique_trials() -> None:
    unique = read_rows("unique_runs.csv")
    index = {row["job_id"]: row for row in unique}
    assert len(index) == len(unique)
    referenced = set()
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
        for row in read_rows(phase + ".csv"):
            referenced.add(row["job_id"])
            source = index[row["job_id"]]
            for field in ("status", "raw_length", "time_to_first_valid_path_s"):
                assert row[field] == source[field]
    assert referenced == set(index)


def test_observed_histories_and_safety_metrics_are_consistent() -> None:
    for row in read_rows("unique_runs.csv"):
        history = json.loads(row["incumbent_history"])
        if row["time_to_first_valid_path_s"]:
            assert history[0]["time_s"] == float(row["time_to_first_valid_path_s"])
            assert history[0]["length"] == float(row["first_valid_path_length"])
            assert all(a["length"] > b["length"] for a, b in pairwise(history))
        else:
            assert row["first_event_observed"] == "False"
        if row["strict_valid"] == "True":
            assert row["common_post_valid"] == "True"
            assert float(row["raw_length"]) > 0
            assert row["baseline_version"]
            assert len(json.loads(row["start"])) == len(json.loads(row["goal"])) == 3
        if row["status"] == "timeout":
            assert row["budget_valid_success"] == "False"


def test_sweeps_include_every_predeclared_seed_and_factor() -> None:
    protocol = json.loads(Path("configs/stage3_protocol.json").read_text())
    for phase, factor, values in (
        ("capacity", "grid_capacity", protocol["capacity"]),
        ("size", "grid_side_length", protocol["side_length"]),
    ):
        rows = read_rows(phase + ".csv")
        actual = {
            (row["scene"], int(row["seed"]), json.loads(row["parameters"])[factor])
            for row in rows
        }
        assert actual == {
            (scene, seed, value)
            for scene in protocol["scenes"]
            for seed in protocol["seeds"]
            for value in values
        }
        assert len(actual) == len(rows)
