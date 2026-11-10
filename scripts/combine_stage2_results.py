"""Validate and combine stage-two trial parts without editing any input evidence."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)
TrialKey = tuple[str, str, int]
NODE_FIELDS = (
    "run_id",
    "scene_id",
    "method",
    "seed",
    "stored_search_nodes",
    "node_definition",
    "sampled_nodes_value",
    "sampled_nodes_unit",
    "expanded_nodes",
    "generated_candidates",
    "valid_candidates",
    "collision_filtered",
    "capacity_evicted",
    "no_candidate_expansions",
    "paper_counter",
    "pathset_size",
)


def trial_key(record: dict[str, Any]) -> TrialKey:
    """Read a scene/method/integer-seed identity; reject malformed trial records."""
    scene = record.get("scene_id")
    method = record.get("method")
    seed = record.get("seed")
    if (
        not isinstance(scene, str)
        or not scene
        or not isinstance(method, str)
        or not method
        or isinstance(seed, bool)
    ):
        raise ValueError("Trial keys require nonempty scene/method and an integer seed")
    if isinstance(seed, str):
        try:
            seed = int(seed)
        except ValueError as error:
            raise ValueError("Trial seed is not an integer") from error
    if not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("Trial seed must be an integer in [0, 2**32)")
    return scene, method, seed


def read_csv_part(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a complete CSV part, preserving every original field value as text."""
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        if (
            not fields
            or len(fields) != len(set(fields))
            or not {"scene_id", "method", "seed"}.issubset(fields)
        ):
            raise ValueError(f"Missing or duplicate trial-key CSV columns: {path}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"CSV row width does not match its header: {path}")
    return fields, rows


def read_paths_part(path: Path) -> list[dict[str, Any]]:
    """Read JSONL objects; malformed or blank evidence lines are explicit errors."""
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON evidence at {path}:{line_number}"
                ) from error
            if not isinstance(record, dict):
                raise ValueError(f"Evidence must be an object at {path}:{line_number}")
            records.append(record)
    return records


def node_record(row: dict[str, str], evidence: dict[str, Any]) -> dict[str, Any]:
    """Expose observed node counts with method-specific definitions and units."""
    method = row["method"]
    counters = evidence.get("counters") or {}
    events = evidence.get("events") or {}
    native = evidence.get("native_payload") or {}
    if not all(isinstance(value, dict) for value in (counters, events, native)):
        raise ValueError("Counter, event and native-payload evidence must be objects")
    if method == "author_original":
        nodes = native.get("node_count")
        definition = "author Allset rows, excluding special goal"
        unit = "author graph nodes"
    elif method in ("paper_reimplementation", "safety_reference"):
        nodes = events.get("graph_nodes")
        definition = "permanent graph nodes including start and special goal"
        unit = "rays"
    elif method == "astar":
        nodes = counters.get("sampled_nodes")
        definition = "discovered voxel-center states, excluding virtual endpoints"
        unit = "discovered voxel-center states"
    elif method == "rrt_connect":
        nodes = counters.get("sampled_nodes")
        definition = "accepted tree nodes including roots"
        unit = "accepted tree nodes"
    else:
        raise ValueError(f"Unknown method for node-count definitions: {method}")
    return {
        "run_id": row.get("run_id"),
        "scene_id": row["scene_id"],
        "method": method,
        "seed": row["seed"],
        "stored_search_nodes": nodes,
        "node_definition": definition,
        "sampled_nodes_value": counters.get("sampled_nodes"),
        "sampled_nodes_unit": unit,
        **{
            name: counters.get(name)
            for name in (
                "expanded_nodes",
                "generated_candidates",
                "valid_candidates",
                "collision_filtered",
                "capacity_evicted",
                "no_candidate_expansions",
            )
        },
        "paper_counter": events.get("paper_counter"),
        "pathset_size": events.get("pathset_size"),
    }


def validate_targets(inputs: Sequence[Path], targets: Sequence[Path]) -> None:
    """Reject overwrites, public coordinate evidence and conflicting target paths."""
    if len(set(targets)) != len(targets):
        raise ValueError("All three output targets must be different")
    for target in targets:
        if target in inputs:
            raise ValueError(f"An output would overwrite an input: {target}")
        if target.exists():
            raise FileExistsError(f"An output already exists: {target}")
        for other in targets:
            if other != target and target.is_relative_to(other):
                raise ValueError("An output file cannot be another output's directory")
        ancestor = target.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            raise NotADirectoryError(ancestor)
    if targets[1].is_relative_to(REPOSITORY_ROOT.resolve()):
        raise ValueError(
            "Combined coordinate evidence must stay outside the repository"
        )


def combine_results(
    csv_paths: Sequence[Path],
    path_parts: Sequence[Path],
    output: Path,
    combined_paths: Path,
    nodes_output: Path,
    expected_trials: int | None = None,
) -> int:
    """Validate all trial parts before writing three new outputs, returning row count.

    CSV and JSONL lists must be paired in the same order. Headers must agree,
    each pair must have exactly matching unique trial keys, and keys must also
    be unique globally. Original inputs are read only. Unknown counts stay empty
    in CSV, never zero. Invalid data raises ``ValueError``; filesystem failures
    raise the corresponding ``OSError``. No output is created before validation.
    """
    if not csv_paths or len(csv_paths) != len(path_parts):
        raise ValueError(
            "CSV and private JSONL part lists must have equal nonzero length"
        )
    if expected_trials is not None and (
        type(expected_trials) is not int or expected_trials <= 0
    ):
        raise ValueError("Expected trial count must be a positive integer")
    tables = [Path(path).resolve() for path in csv_paths]
    paths = [Path(path).resolve() for path in path_parts]
    targets = [Path(path).resolve() for path in (output, combined_paths, nodes_output)]
    validate_targets([*tables, *paths], targets)
    records = []
    indexed: dict[TrialKey, dict[str, Any]] = {}
    all_keys: set[TrialKey] = set()
    fields = None
    for table, evidence_path in zip(tables, paths, strict=True):
        part_fields, rows = read_csv_part(table)
        if fields is None:
            fields = part_fields
        elif fields != part_fields:
            raise ValueError("CSV part headers must match exactly")
        evidence = read_paths_part(evidence_path)
        row_keys = [trial_key(row) for row in rows]
        evidence_keys = [trial_key(record) for record in evidence]
        if len(row_keys) != len(set(row_keys)) or all_keys.intersection(row_keys):
            raise ValueError("Duplicate CSV trial key")
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("Duplicate private JSONL trial key")
        if set(row_keys) != set(evidence_keys):
            raise ValueError("CSV and matching private JSONL trial keys do not match")
        all_keys.update(row_keys)
        records.extend(rows)
        indexed.update(zip(evidence_keys, evidence, strict=True))
    if not records:
        raise ValueError("No trial records were supplied")
    if expected_trials is not None and len(records) != expected_trials:
        raise ValueError(f"Expected {expected_trials} trials; found {len(records)}")
    records.sort(key=trial_key)
    node_rows = [node_record(row, indexed[trial_key(row)]) for row in records]
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
    with targets[0].open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    with targets[1].open("x", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(indexed[trial_key(row)], ensure_ascii=False) + "\n")
    with targets[2].open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=NODE_FIELDS)
        writer.writeheader()
        writer.writerows(node_rows)
    LOGGER.info(
        "Combined %d unique trials; original parts remain unchanged", len(records)
    )
    return len(records)


def main(argv: list[str] | None = None) -> int:
    """Combine explicitly selected public tables and matching private evidence parts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, nargs="+", required=True)
    parser.add_argument("--paths", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--combined-paths", type=Path, required=True)
    parser.add_argument("--nodes-output", type=Path, required=True)
    parser.add_argument("--expected-trials", type=int)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        combine_results(
            args.csv,
            args.paths,
            args.output,
            args.combined_paths,
            args.nodes_output,
            args.expected_trials,
        )
    except (OSError, ValueError) as error:
        LOGGER.error("Cannot combine trial records: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
