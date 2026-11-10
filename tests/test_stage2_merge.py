"""Synthetic trial parts verify safe merges and explicit node-count semantics."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

FIELDS = [
    "run_id",
    "scene_id",
    "method",
    "seed",
    "status",
    "strict_valid",
    "raw_path_length",
]


@pytest.fixture
def merge_module() -> ModuleType:
    """Load the standalone merge CLI without invoking it or importing author code."""
    path = Path(__file__).resolve().parents[1] / "scripts/combine_stage2_results.py"
    spec = importlib.util.spec_from_file_location("merge_stage2", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_part(
    directory: Path, name: str, method: str, seed: int, *, timeout: bool = False
) -> tuple[Path, Path]:
    """Write one tiny independent CSV/evidence pair with method-specific counts."""
    table = directory / f"{name}.csv"
    paths = directory / f"{name}.jsonl"
    row = {
        "run_id": name,
        "scene_id": "S0",
        "method": method,
        "seed": str(seed),
        "status": "timeout" if timeout else "ok",
        "strict_valid": "" if timeout else "True",
        "raw_path_length": "" if timeout else "1.250000",
    }
    with table.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)
    evidence = {
        **row,
        "seed": seed,
        "counters": None
        if timeout
        else {
            "sampled_nodes": 50,
            "expanded_nodes": 10,
            "generated_candidates": 20,
            "valid_candidates": 15,
            "collision_filtered": 5,
            "capacity_evicted": 2,
            "no_candidate_expansions": 1,
        },
        "events": None
        if timeout
        else {
            "graph_nodes": 8,
            "paper_counter": 9,
            "pathset_size": 3,
        },
        "native_payload": None if timeout else {"node_count": 12},
        "raw_path": None if timeout else [[0, 0, 0], [1.25, 0, 0]],
    }
    paths.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    return table, paths


def outputs(directory: Path) -> tuple[Path, Path, Path]:
    """Keep all synthetic output paths new and outside the public checkout."""
    return (
        directory / "public/runs.csv",
        directory / "private/paths.jsonl",
        directory / "public/node_counts.csv",
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read emitted CSV values without coercing numbers or empty fields."""
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_merge_preserves_input_bytes_and_values(
    tmp_path: Path, merge_module: ModuleType
) -> None:
    first = write_part(tmp_path, "first", "paper_reimplementation", 2)
    second = write_part(tmp_path, "second", "author_original", 1)
    originals = {path: path.read_bytes() for path in (*first, *second)}
    expected = sorted(
        [*read_rows(first[0]), *read_rows(second[0])], key=merge_module.trial_key
    )
    targets = outputs(tmp_path / "merged")
    count = merge_module.combine_results(
        [first[0], second[0]], [first[1], second[1]], *targets, expected_trials=2
    )
    assert count == 2
    assert read_rows(targets[0]) == expected
    assert all(path.read_bytes() == content for path, content in originals.items())
    nodes = {row["method"]: row for row in read_rows(targets[2])}
    assert nodes["author_original"]["stored_search_nodes"] == "12"
    assert "excluding special goal" in nodes["author_original"]["node_definition"]
    assert nodes["paper_reimplementation"]["stored_search_nodes"] == "8"
    assert (
        "including start and special goal"
        in nodes["paper_reimplementation"]["node_definition"]
    )
    assert nodes["paper_reimplementation"]["sampled_nodes_value"] == "50"
    assert nodes["paper_reimplementation"]["sampled_nodes_unit"] == "rays"
    assert nodes["paper_reimplementation"]["paper_counter"] == "9"
    assert nodes["paper_reimplementation"]["pathset_size"] == "3"
    evidence = [
        json.loads(line) for line in targets[1].read_text(encoding="utf-8").splitlines()
    ]
    assert {merge_module.trial_key(record) for record in evidence} == {
        merge_module.trial_key(row) for row in expected
    }


@pytest.mark.parametrize("method", ["astar", "rrt_connect", "safety_reference"])
def test_node_definitions_remain_distinct(
    tmp_path: Path, merge_module: ModuleType, method: str
) -> None:
    table, paths = write_part(tmp_path, "part", method, 0)
    targets = outputs(tmp_path / "merged")
    merge_module.combine_results([table], [paths], *targets)
    row = read_rows(targets[2])[0]
    assert row["stored_search_nodes"] == ("8" if method == "safety_reference" else "50")
    expected = {
        "astar": "discovered voxel-center states",
        "rrt_connect": "accepted tree nodes",
        "safety_reference": "rays",
    }
    assert row["sampled_nodes_unit"] == expected[method]


def test_timeout_node_counts_stay_unknown(
    tmp_path: Path, merge_module: ModuleType
) -> None:
    table, paths = write_part(tmp_path, "timeout", "author_original", 0, timeout=True)
    targets = outputs(tmp_path / "merged")
    merge_module.combine_results([table], [paths], *targets)
    row = read_rows(targets[2])[0]
    for name in (
        "stored_search_nodes",
        "sampled_nodes_value",
        "expanded_nodes",
        "generated_candidates",
        "valid_candidates",
        "collision_filtered",
        "capacity_evicted",
        "paper_counter",
        "pathset_size",
    ):
        assert row[name] == ""


@pytest.mark.parametrize(
    "problem",
    [
        "duplicate_csv",
        "duplicate_paths",
        "key_mismatch",
        "missing_line",
        "expected_count",
        "headers",
    ],
)
def test_invalid_parts_fail_before_creating_outputs(
    tmp_path: Path, merge_module: ModuleType, problem: str
) -> None:
    first = write_part(tmp_path, "first", "astar", 0)
    second = write_part(tmp_path, "second", "rrt_connect", 1)
    tables = [first[0], second[0]]
    paths = [first[1], second[1]]
    expected_trials = None
    if problem == "duplicate_csv":
        tables = [first[0], first[0]]
        paths = [first[1], first[1]]
    elif problem == "duplicate_paths":
        first[1].write_text(first[1].read_text(encoding="utf-8") * 2, encoding="utf-8")
    elif problem == "key_mismatch":
        evidence = json.loads(first[1].read_text(encoding="utf-8"))
        evidence["seed"] = 9
        first[1].write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    elif problem == "missing_line":
        first[1].write_text("", encoding="utf-8")
    elif problem == "expected_count":
        expected_trials = 3
    else:
        second[0].write_text(
            second[0]
            .read_text(encoding="utf-8")
            .replace("strict_valid", "other_field"),
            encoding="utf-8",
        )
    snapshots = {path: path.read_bytes() for path in set([*tables, *paths])}
    targets = outputs(tmp_path / "not_created")
    with pytest.raises(ValueError):
        merge_module.combine_results(
            tables, paths, *targets, expected_trials=expected_trials
        )
    assert not (tmp_path / "not_created").exists()
    assert all(path.read_bytes() == content for path, content in snapshots.items())


def test_lists_must_pair_and_inputs_must_not_be_overwritten(
    tmp_path: Path, merge_module: ModuleType
) -> None:
    table, paths = write_part(tmp_path, "part", "astar", 0)
    targets = outputs(tmp_path / "not_created")
    with pytest.raises(ValueError, match="equal nonzero"):
        merge_module.combine_results([table], [], *targets)
    with pytest.raises(ValueError, match="overwrite an input"):
        merge_module.combine_results([table], [paths], table, targets[1], targets[2])
    assert not (tmp_path / "not_created").exists()


def test_private_coordinates_cannot_be_written_inside_repository(
    tmp_path: Path, merge_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    table, paths = write_part(tmp_path, "part", "astar", 0)
    repository = tmp_path / "fake_public_checkout"
    monkeypatch.setattr(merge_module, "REPOSITORY_ROOT", repository)
    targets = outputs(repository)
    with pytest.raises(ValueError, match="outside the repository"):
        merge_module.combine_results([table], [paths], *targets)
    assert not repository.exists()


def test_cli_uses_only_explicit_paths(tmp_path: Path, merge_module: ModuleType) -> None:
    table, paths = write_part(tmp_path, "part", "astar", 0)
    targets = outputs(tmp_path / "merged")
    assert (
        merge_module.main(
            [
                "--csv",
                str(table),
                "--paths",
                str(paths),
                "--output",
                str(targets[0]),
                "--combined-paths",
                str(targets[1]),
                "--nodes-output",
                str(targets[2]),
                "--expected-trials",
                "1",
            ]
        )
        == 0
    )
