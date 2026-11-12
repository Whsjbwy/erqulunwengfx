"""Read immutable historical coordinates and freeze deterministic inventories."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from ..metrics import path_length
from ..stage5a.analysis import read_evidence, write_csv
from ..stage5a.audit import expected_identities
from ..stage5a.maps import ROOT, Scene, body_radius, load_scene, read_config
from ..stage5a.path_features import describe_path
from .replay import classify


def protect_output(path: Path) -> Path:
    """Reject new diagnostic output targeting frozen repository files."""
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT) and not resolved.is_relative_to(
        ROOT / "results/stage5ar"
    ):
        raise ValueError(
            "Diagnostic output cannot overwrite historical repository paths"
        )
    return resolved


def load_history(local: Path) -> tuple[dict, list[dict]]:
    """Require all 450 original tasks and exactly the frozen current inputs."""
    config = json.loads((local / "configuration.json").read_text(encoding="utf-8"))
    if config != {
        "protocol": read_config("stage5a_protocol.json"),
        "maps": read_config("stage5a_maps.json"),
    }:
        raise ValueError("Historical configuration differs from frozen 5A")
    items = read_evidence(local)
    expected = expected_identities(config, read_config("stage5a_selected.json"))
    if len(items) != 450 or {x["row"]["job_id"] for x in items} != expected:
        raise ValueError("Missing, duplicate or unexpected historical records")
    for item in items:
        row, paths = item["row"], item["paths"]
        for role in ("raw_path_id", "selected_path_id"):
            index = row[role]
            if index is not None and (
                not 0 <= index < len(paths) or str(index) not in item["executions"]
            ):
                raise ValueError("Missing path coordinates or original execution")
    return config, items


def compare_public(items: list[dict], path: Path) -> dict:
    """Check every original row field against the published 450-row CSV."""
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    index = {row["job_id"]: row for row in rows}
    if len(rows) != len(index) or set(index) != {x["row"]["job_id"] for x in items}:
        raise ValueError("Public CSV missing/duplicate task")
    fields = 0
    for item in items:
        for key, expected in item["row"].items():
            actual = index[item["row"]["job_id"]][key]
            if isinstance(expected, (dict, list, tuple)):
                same = json.loads(actual) == json.loads(json.dumps(expected))
            elif expected is None:
                same = actual == ""
            elif isinstance(expected, float):
                same = math.isclose(
                    float(actual), expected, rel_tol=1e-12, abs_tol=1e-12
                )
            else:
                same = actual == str(expected)
            if not same:
                raise ValueError(f"Public CSV differs: {item['row']['job_id']} {key}")
            fields += 1
    return {
        "historical_records": len(items),
        "public_fields_compared": fields,
        "status": "passed",
    }


def path_features(path: list, scene: Scene, protocol: dict, mode: str) -> dict:
    """Add certified geometry and capped clearance to historical features."""
    radius = body_radius(protocol)
    physical = scene.geometry(radius)
    required = scene.geometry(radius + protocol["vehicle"]["safety_margin_m"])
    return {
        **describe_path(path, scene.start, scene.goal),
        "length_m": path_length(path),
        "nominal_body_valid": physical.path(path).valid,
        "extra_margin_valid": required.path(path).valid,
        "mode_required_margin_m": protocol["vehicle"]["safety_margin_m"]
        if mode == "margin"
        else 0.0,
        "path_min_physical_clearance_capped_m": min(
            physical.clearance(a, b) for a, b in zip(path[:-1], path[1:], strict=True)
        ),
        "path_min_mission_clearance_capped_m": min(
            physical.clearance(a, b, mission=True)
            for a, b in zip(path[:-1], path[1:], strict=True)
        ),
    }


def inventory(items: list[dict], config: dict, version: str) -> list[dict]:
    """Retain every holdout selected/raw identity, including absent outputs."""
    rows = []
    scenes = {}
    for item in items:
        source = item["row"]
        if source["phase"] != "holdout":
            continue
        scene_id = source["scene"]
        if scene_id not in scenes:
            scenes[scene_id] = load_scene(scene_id, config["maps"])
        scene = scenes[scene_id]
        ids = sorted({source["raw_path_id"], source["selected_path_id"]} - {None})
        for path_id in ids or [None]:
            execution = item["executions"].get(str(path_id), {})
            selected = path_id is not None and path_id == source["selected_path_id"]
            raw = path_id is not None and path_id == source["raw_path_id"]
            rows.append(
                {
                    "job_id": source["job_id"],
                    "scene": scene_id,
                    "family": source["family"],
                    "mode": source["geometry_mode"],
                    "method": source["method"],
                    "seed": source["seed"],
                    "path_id": path_id,
                    "path_uid": f"{source['job_id']}::p{path_id}"
                    if path_id is not None
                    else None,
                    "version": version,
                    "protocol_id": version,
                    "historical_version": source["version"],
                    "is_selected_path": selected,
                    "is_raw_best": raw,
                    "reachability": source["reachability"],
                    "failure_reason": execution.get(
                        "failure_reason", "not_run_no_path"
                    ),
                    "primary_class": classify(execution["failure_reason"])
                    if execution
                    else "not_run_no_path",
                    "historical_execution_success": execution.get("execution_success"),
                    "historical_termination_time_s": execution.get("simulation_time_s"),
                    **(
                        path_features(
                            item["paths"][path_id],
                            scene,
                            config["protocol"],
                            source["geometry_mode"],
                        )
                        if path_id is not None
                        else {"nominal_body_valid": False}
                    ),
                    "is_selected": False,
                    "in_expansion": selected and execution.get("eligible", False),
                    "selection_reason": "",
                }
            )
    return rows


def select_pilot(rows: list[dict], per_family: int) -> list[dict]:
    """Apply preregistered outcome/scene/early-late coverage without new runs."""
    groups = defaultdict(list)
    for row in rows:
        if row["in_expansion"]:
            groups[row["family"]].append(row)
    for group in groups.values():
        select_family(group, per_family)
    return rows


def select_family(group: list[dict], per_family: int) -> None:
    """Select coverage within one family, binding its local selection state."""
    chosen = []

    def order(row: dict) -> tuple:
        return row["historical_termination_time_s"], row["job_id"]

    def add(row: dict, reason: str) -> None:
        if row not in chosen and len(chosen) < per_family:
            chosen.append(row)
            row["is_selected"] = True
            row["selection_reason"] = reason

    for category in sorted({row["primary_class"] for row in group}):
        add(
            min(
                (row for row in group if row["primary_class"] == category),
                key=order,
            ),
            "earliest_in_historical_outcome_class",
        )
    for scene in sorted({row["scene"] for row in group}):
        if not any(row["scene"] == scene for row in chosen):
            add(
                min((row for row in group if row["scene"] == scene), key=order),
                "uncovered_scene",
            )
    remaining = sorted(
        (
            row
            for row in group
            if row not in chosen and row["primary_class"] != "success"
        ),
        key=order,
    )
    earliest = True
    while remaining and len(chosen) < per_family:
        add(
            remaining.pop(0 if earliest else -1),
            "earliest_remaining_failure" if earliest else "latest_remaining_failure",
        )
        earliest = not earliest


def freeze_manifest(path: Path, rows: list[dict]) -> None:
    """Refuse accidental replacement of the preregistered sample manifest."""
    if path.exists():
        raise FileExistsError("Sampling manifest already frozen")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_csv(path, rows)


def read_manifest(path: Path) -> list[dict]:
    """Decode only typed identity/selection columns needed for replay."""
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    keys = [(row["job_id"], row["path_id"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate task/path identity in manifest")
    for row in rows:
        row["path_id"] = int(row["path_id"]) if row["path_id"] else None
        for key in ("is_selected", "in_expansion", "is_selected_path", "is_raw_best"):
            if row[key] not in ("True", "False"):
                raise ValueError("Missing manifest selection flag")
            row[key] = row[key] == "True"
    return rows
