"""Independent reconstruction and continuous recertification of saved results."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import numpy as np

from ..metrics import endpoints_match, path_length
from ..stage5a.analysis import write_csv
from ..stage5a.maps import body_radius, mode_radius
from ..stage5ae.audit import check_safety
from ..stage5ae.maps import generate as old_map
from ..stage5ae.runtime import experiment_lock
from ..stage5ae.storage import write_json
from ..stage5ar.audit import check_trace
from ..stage5ar.reference import sampled_curve_evidence
from .maps import generate
from .storage import Records, check_prefix, public_output


def audit(local: Path, old: Path, ar: Path, output: Path, phase: str) -> dict:
    """Check one completed phase; scientific source files remain read-only."""
    output = public_output(output)
    marker = "development" if phase == "development" else "formal"
    if not (local / (marker + "_completed.json")).exists():
        raise ValueError("Complete phase before audit")
    cfg = json.loads((local / "configuration.json").read_text(encoding="utf-8"))
    previous = json.loads((old / "configuration.json").read_text(encoding="utf-8"))
    records = Records(local, old, ar)
    scenes = {}
    sources = {}
    plans = []
    directory = old / "planning" if phase == "development" else local / "planning"
    for file in sorted(directory.glob("*.json")):
        if file.name.endswith(".processing.json"):
            continue
        value = json.loads(file.read_text(encoding="utf-8"))
        plans.append(value)
        search = value["search"]
        if search["time_budget_s"] != 10 or not math.isclose(
            search["radius_m"],
            mode_radius(value["mode"], cfg["vehicle"]),
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("Planning budget or effective radius changed")
        if value["raw"] is None:
            if (
                value["first_certificate"] is not None
                or search["first_valid_time_s"] is not None
            ):
                raise ValueError("Missing path has a false first-certificate claim")
            continue
        post = json.loads(
            (directory / (value["job_id"] + ".processing.json")).read_text(
                encoding="utf-8"
            )
        )
        if [value["raw"][i] for i in post["source_indices"]] != post["shortcut"]:
            raise ValueError("Shortcut source changed")
        sources[value["job_id"]] = {"raw": value["raw"], "shortcut": post["shortcut"]}
    if phase == "independent":
        expected = {
            f"independent_{s['id']}_{m}_{r}_seed{k}"
            for s in cfg["maps"]["maps"]
            for m in cfg["settings"]["methods"]
            for r in cfg["settings"]["modes"]
            for k in cfg["settings"]["planning_seeds"]
        }
        if len(plans) != 216 or {p["job_id"] for p in plans} != expected:
            raise ValueError("Incomplete planning matrix")
    failures = []
    count = steps = intervals = prefix = terminal = rk4 = 0
    maximum = 0.0
    actual_ids = set()
    for file in sorted(records.directory.glob("*.json.gz")):
        with gzip.open(file, "rt", encoding="utf-8") as stream:
            head = json.load(stream)
        meta = head["meta"]
        if meta["phase"] != phase:
            continue
        record = records.read(meta["case_id"])
        summary, trace = record["summary"], record["trace"]
        if meta["scene"] not in scenes:
            document = previous["maps"] if phase == "development" else cfg["maps"]
            spec = next(s for s in document["maps"] if s["id"] == meta["scene"])
            scenes[meta["scene"]] = (
                old_map(spec, document)
                if phase == "development"
                else generate(spec, document)
            )
        scene = scenes[meta["scene"]]
        path = sources[meta["job_id"]][meta["processing"]]
        result = check_trace(record, cfg["vehicle"]["kinematics"])
        intervals += check_safety(record, path, scene, cfg["vehicle"])
        count += 1
        steps += result["steps"]
        rk4 += result["rk4_steps"]
        maximum = max(maximum, result["max_rk4_error_m"])
        if meta["controller"] == "los_terminal_v1":
            source_id = f"{meta['job_id']}--{meta['processing']}--los_d2"
            baseline = (
                records.old.read(source_id)
                if phase == "development"
                else records.read(source_id)
            )
            switch = summary["terminal_switch_index"]
            prefix += check_prefix(trace, baseline["trace"], switch)
            if summary["terminal_switches"] != int(switch is not None):
                raise ValueError("Switch count drift")
            if switch is not None:
                for row in trace[switch:]:
                    if not np.allclose(row["target"], scene.goal, rtol=0, atol=1e-12):
                        raise ValueError("Terminal command misses actual goal")
                    terminal += 1
        primary = summary["primary_class"]
        if primary in (
            "swept_safety_reject",
            "mission_band_reject",
            "margin_only_failure",
        ):
            label = {
                "swept_safety_reject": "physical",
                "mission_band_reject": "mission",
                "margin_only_failure": "margin",
            }[primary]
            event = next(r for r in trace if r[label + "_reason"] != "ok")
            radius = (
                mode_radius(meta["mode"], cfg["vehicle"])
                if label == "margin"
                else body_radius(cfg["vehicle"])
            )
            failures.append(
                {
                    **meta,
                    "primary_class": primary,
                    "radius_checked_m": radius,
                    "time_start_s": event["time_start_s"],
                    "time_s": event["time_s"],
                    **sampled_curve_evidence(event, scene, radius),
                }
            )
        actual_ids.add(meta["case_id"])
    controllers = (
        ("los_terminal_v1",)
        if phase == "development"
        else cfg["settings"]["controllers"]
    )
    expected_ids = {
        f"{job}--{p}--{c}"
        for job in sources
        for p in ("raw", "shortcut")
        for c in controllers
    }
    if actual_ids != expected_ids:
        raise ValueError("Missing or extra execution records")
    geometries = 0
    for value in plans:
        if value["job_id"] not in sources:
            continue
        scene = scenes[value["scene"]]
        geometry = scene.geometry(mode_radius(value["mode"], cfg["vehicle"]))
        for path in sources[value["job_id"]].values():
            if not geometry.path(path).valid or not endpoints_match(
                path, scene.start, scene.goal
            ):
                raise ValueError("Path geometry/endpoints failed")
        event = value["first_certificate"]
        if event["time_s"] != value["search"]["first_valid_time_s"]:
            raise ValueError("First-certificate time differs from actual search")
        if event["time_s"] > 10 or not math.isclose(
            event["length"], path_length(value["first_path"]), abs_tol=1e-9
        ):
            raise ValueError("First certificate late/changed")
        if (
            not geometry.path(value["first_path"]).valid
            or not endpoints_match(value["first_path"], scene.start, scene.goal)
            or value["reachability"].startswith("certified_unreachable")
        ):
            raise ValueError("Invalid geometric claim")
        geometries += 1
    result = {
        "passed": True,
        "phase": phase,
        "planning_tasks": len(plans),
        "geometric_tasks": geometries,
        "new_condition_records_checked": count,
        "trace_steps_checked": steps,
        "continuous_intervals_recertified": intervals,
        "independent_rk4_steps": rk4,
        "maximum_rk4_error_m": maximum,
        "preterminal_steps_rechecked": prefix,
        "terminal_goal_targets_checked": terminal,
        "first_safety_intervals_checked": len(failures),
    }
    (output / (phase + "_audit.json")).write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    write_csv(output / (phase + "_failure_reference.csv"), failures)
    marker = local / (phase + "_audit_completed.json")
    if not marker.exists():
        write_json(marker, result)
    return result


def main() -> None:
    """Lock the directory throughout the independent audit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("development", "independent"), required=True
    )
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--ar-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5af"))
    args = parser.parse_args()
    if not (args.local_dir / "development_completed.json").exists():
        raise ValueError("Expected completed5AF development evidence")
    with experiment_lock(args.local_dir):
        print(
            json.dumps(
                audit(
                    args.local_dir,
                    args.old_evidence,
                    args.ar_evidence,
                    args.output,
                    args.phase,
                )
            )
        )


if __name__ == "__main__":
    main()
