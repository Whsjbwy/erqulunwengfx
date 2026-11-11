"""Recheck archived certificates and checkpoint provenance after planning."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from ..collision_checker import validate_path
from ..metrics import endpoints_match, path_length
from .maps import load_map


def audit(local: Path, *, expected_trials: int | None = None) -> dict[str, Any]:
    """Independently revalidate each distinct archived polyline on its map.

    Exact coordinate tuples only avoid repeating the same geometry query;
    no file checksums, coordinate rounding or evidence files are written.
    """
    configuration = json.loads(
        (local / "configuration.json").read_text(encoding="utf-8")
    )
    sources = sorted(local.glob("*/result.json"))
    if expected_trials is not None and len(sources) != expected_trials:
        raise ValueError("Final audit requires the complete registered matrix")
    scenes = {}
    checked: set[tuple] = set()
    entries = 0
    events = 0
    checkpoints = 0
    identities = set()
    for source in sources:
        item = json.loads(source.read_text(encoding="utf-8"))
        row = item["row"]
        identity = (row["scene"], row["method"], row["seed"])
        if identity in identities:
            raise ValueError("Duplicate independent trial in certificate audit")
        identities.add(identity)
        scene_id = row["scene"]
        if scene_id not in scenes:
            scenes[scene_id] = load_map(scene_id, configuration["maps"])
        scene = scenes[scene_id]
        registry = item["paths"]
        for path in registry:
            entries += 1
            key = (scene_id, tuple(tuple(point) for point in path))
            if key not in checked:
                if not validate_path(path, scene.grid).valid:
                    raise ValueError(f"Archived invalid path: {row['job_id']}")
                if not endpoints_match(path, scene.start, scene.goal):
                    raise ValueError(f"Archived endpoint mismatch: {row['job_id']}")
                checked.add(key)
        used = set()
        for name in ("history", "raw_history"):
            previous_time, previous_length = -1.0, math.inf
            for event in item[name]:
                events += 1
                if not 0 <= event["time_s"] <= row["total_budget_s"]:
                    raise ValueError("A late certificate was included")
                if (
                    event["time_s"] < previous_time
                    or event["length"] >= previous_length
                ):
                    raise ValueError("Certificate history is not monotone")
                path_id = event["path_id"]
                if not 0 <= path_id < len(registry):
                    raise ValueError("Certificate references an absent polyline")
                if not math.isclose(
                    path_length(registry[path_id]),
                    event["length"],
                    rel_tol=1e-12,
                    abs_tol=1e-9,
                ):
                    raise ValueError(
                        "Certificate length does not match its coordinates"
                    )
                used.add(path_id)
                previous_time, previous_length = event["time_s"], event["length"]
        if used != set(range(len(registry))):
            raise ValueError("Archived polyline has no certificate provenance")
        if row["strict_valid"] != bool(item["history"]):
            raise ValueError("Solution flag disagrees with certified history")
        first = item["raw_history"][0]["time_s"] if item["raw_history"] else None
        if row["first_valid_time_s"] != first:
            raise ValueError("First solution time was changed after execution")
        for step in item["checkpoints"]:
            checkpoints += 1
            eligible = [
                e for e in item["history"] if e["time_s"] <= step["checkpoint_s"]
            ]
            raw = [
                e for e in item["raw_history"] if e["time_s"] <= step["checkpoint_s"]
            ]
            if step["valid"] != bool(eligible):
                raise ValueError("Checkpoint has a future or missing certificate")
            if step["best_length"] != (eligible[-1]["length"] if eligible else None):
                raise ValueError("Checkpoint length was backfilled")
            if step["raw_best_length"] != (raw[-1]["length"] if raw else None):
                raise ValueError("Raw checkpoint length was backfilled")
    return {
        "independent_trials": len(sources),
        "archived_path_entries": entries,
        "distinct_map_polylines_checked": len(checked),
        "history_events_checked": events,
        "checkpoints_checked": checkpoints,
        "invalid_paths": 0,
        "endpoint_mismatches": 0,
        "late_certificates": 0,
        "checkpoint_inconsistencies": 0,
        "status": "passed",
    }


def main() -> None:
    """Write aggregate audit evidence only after every actual check passes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-trials", type=int, default=402)
    args = parser.parse_args()
    result = audit(args.local_dir, expected_trials=args.expected_trials)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
