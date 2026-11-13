"""Recheck independent search provenance and full-resolution execution records."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from ..metrics import endpoints_match, path_length
from ..stage5a.analysis import write_csv
from ..stage5a.geometry import Geometry
from ..stage5a.maps import Scene, body_radius, mode_radius
from ..stage5a.tracking import Route, chord_error_bound
from ..stage5ar.audit import check_trace
from ..stage5ar.reference import sampled_curve_evidence
from .maps import generate
from .storage import Records, public_output


def check_safety(record: dict, path: list, scene: Scene, vehicle: dict) -> int:
    """Recertify every saved interval and reconstruct nearest-path errors."""
    trace = record["trace"]
    if not trace:
        return 0
    cfg = vehicle["kinematics"]
    radius = body_radius(vehicle)
    physical = Geometry(scene.grid, radius)
    mission = scene.geometry(radius)
    required = scene.geometry(
        radius + (0.25 if record["meta"]["mode"] == "margin" else 0.0)
    )
    yaw = math.atan2(scene.goal[1] - scene.start[1], scene.goal[0] - scene.start[0])
    if (
        not math.isclose(trace[0]["start_yaw_rad"], yaw, abs_tol=1e-12)
        or trace[0]["start_pitch_rad"] != 0
    ):
        raise ValueError("Initial attitude differs between controller conditions")
    route = Route(path)
    positions = np.array([row["position"] for row in trace])
    delta = positions[:, None] - route.points[None, :-1]
    fraction = np.divide(
        np.einsum("nsi,si->ns", delta, route.edges),
        route.lengths**2,
        out=np.zeros(delta.shape[:2]),
        where=route.lengths > 0,
    ).clip(0, 1)
    errors = np.min(
        np.linalg.norm(delta - fraction[:, :, None] * route.edges, axis=2), axis=1
    )
    for row, error in zip(trace, errors, strict=True):
        if row["speed_m_s"] != cfg["speed_m_s"] or not math.isclose(
            row["cross_track_m"], error, abs_tol=1e-10
        ):
            raise ValueError("Frozen speed or global nearest-path error changed")
        bound = chord_error_bound(
            row["speed_m_s"],
            row["yaw_rate_rad_s"],
            row["pitch_rate_rad_s"],
            cfg["step_s"],
        )
        if not math.isclose(bound, row["chord_error_bound_m"], abs_tol=1e-12):
            raise ValueError("Continuous enclosure differs from frozen bound")
        for label, geometry in (
            ("physical", physical),
            ("mission", mission),
            ("margin", required),
        ):
            verdict = geometry.segment(
                row["start_position"], row["position"], extra_radius=bound
            )
            if verdict.reason != row[label + "_reason"]:
                raise ValueError("Saved continuous safety reason did not recertify")
    return len(trace)


def audit(local: Path, old: Path, output: Path) -> dict:
    """Independently verify all saved paths, identities, bounds and trace metrics."""
    output = public_output(output)
    if not (local / "formal_completed.json").exists():
        raise ValueError("Complete independent validation before final audit")
    cfg = json.loads((local / "configuration.json").read_text(encoding="utf-8"))
    protocol, vehicle = cfg["protocol"], cfg["vehicle"]
    expected = {
        f"independent_{spec['id']}_{method}_{mode}_seed{seed}"
        for spec in cfg["maps"]["maps"]
        for method in protocol["methods"]
        for mode in protocol["modes"]
        for seed in protocol["planning_seeds"]
    }
    files = [
        p
        for p in (local / "planning").glob("*.json")
        if not p.name.endswith(".processing.json")
    ]
    if {p.stem for p in files} != expected or len(files) != 360:
        raise ValueError("Missing/duplicate independent planning tasks")
    scenes = {spec["id"]: generate(spec, cfg["maps"]) for spec in cfg["maps"]["maps"]}
    geometry_count, certified_first = 0, 0
    sources = {}
    peak_memory = 0
    for path in files:
        item = json.loads(path.read_text(encoding="utf-8"))
        scene, search = scenes[item["scene"]], item["search"]
        radius = mode_radius(item["mode"], vehicle)
        if (
            not math.isclose(radius, search["radius_m"], abs_tol=1e-12)
            or search["time_budget_s"] != 10
        ):
            raise ValueError("Effective radius/budget differs from frozen protocol")
        peak_memory = max(peak_memory, search["process_peak_rss_bytes"])
        if item["raw"] is None:
            if (
                item["first_certificate"] is not None
                or search["first_valid_time_s"] is not None
            ):
                raise ValueError("Missing raw path has a false first-certificate claim")
            continue
        geometry = scene.geometry(radius)
        if not geometry.path(item["raw"]).valid or not endpoints_match(
            item["raw"], scene.start, scene.goal
        ):
            raise ValueError("Independent raw path geometry/endpoints failed")
        if not geometry.path(item["first_path"]).valid:
            raise ValueError("First certificate path failed geometry")
        event = item["first_certificate"]
        if event["time_s"] > 10 or event["time_s"] != search["first_valid_time_s"]:
            raise ValueError("First certificate was late or altered")
        if not math.isclose(
            event["length"], path_length(item["first_path"]), abs_tol=1e-9
        ):
            raise ValueError("First certificate length differs from saved coordinates")
        if item["reachability"].startswith("certified_unreachable"):
            raise ValueError("Accepted path contradicted an envelope certificate")
        processed = json.loads(
            (path.parent / (item["job_id"] + ".processing.json")).read_text(
                encoding="utf-8"
            )
        )
        sources[item["job_id"]] = {
            "raw": item["raw"],
            "shortcut": processed["shortcut"],
        }
        reconstructed = [item["raw"][index] for index in processed["source_indices"]]
        if (
            reconstructed != processed["shortcut"]
            or not geometry.path(reconstructed).valid
        ):
            raise ValueError("Shortcut lineage or continuous geometry failed")
        geometry_count += 1
        certified_first += 1
    records = Records(local, old)
    totals = {
        "records_checked": 0,
        "trace_steps_checked": 0,
        "independent_rk4_steps": 0,
        "maximum_rk4_error_m": 0.0,
        "unique_independent_safety_traces": 0,
        "continuous_intervals_recertified": 0,
    }
    chosen = json.loads((local / "selection.json").read_text(encoding="utf-8"))[
        "chosen"
    ]["id"]
    references, reference_cache = [], {}
    for path in sorted(records.directory.glob("*.json.gz")):
        record = records.read(path.name.removesuffix(".json.gz"))
        meta = record["meta"]
        if meta["phase"] == "independent" and meta["controller"] not in (
            "legacy",
            chosen,
        ):
            raise ValueError("Independent set used an unfrozen controller")
        result = check_trace(record, vehicle["kinematics"])
        if meta["phase"] == "independent" and "trace_reference" not in record:
            totals["continuous_intervals_recertified"] += check_safety(
                record,
                sources[meta["job_id"]][meta["processing"]],
                scenes[meta["scene"]],
                vehicle,
            )
            totals["unique_independent_safety_traces"] += 1
        primary = record["summary"]["primary_class"]
        if meta["phase"] == "independent" and primary in (
            "swept_safety_reject",
            "mission_band_reject",
            "margin_only_failure",
        ):
            source = record.get("trace_reference", meta["case_id"])
            if source not in reference_cache:
                label = {
                    "swept_safety_reject": "physical",
                    "mission_band_reject": "mission",
                    "margin_only_failure": "margin",
                }[primary]
                event = next(
                    row for row in record["trace"] if row[label + "_reason"] != "ok"
                )
                radius = (
                    mode_radius(meta["mode"], vehicle)
                    if label == "margin"
                    else body_radius(vehicle)
                )
                reference_cache[source] = {
                    "time_start_s": event["time_start_s"],
                    "time_s": event["time_s"],
                    "radius_checked_m": radius,
                    **sampled_curve_evidence(event, scenes[meta["scene"]], radius),
                }
            references.append(
                {**meta, "primary_class": primary, **reference_cache[source]}
            )
        totals["records_checked"] += 1
        totals["trace_steps_checked"] += result["steps"]
        totals["independent_rk4_steps"] += result["rk4_steps"]
        totals["maximum_rk4_error_m"] = max(
            totals["maximum_rk4_error_m"], result["max_rk4_error_m"]
        )
    result = {
        "status": "passed",
        "planning_tasks_checked": len(files),
        "geometry_paths_checked": geometry_count,
        "first_certificates_checked": certified_first,
        "maximum_planning_process_peak_rss_bytes": peak_memory,
        **totals,
        "failure_curve_reference_conditions": len(references),
        "unique_failure_curve_references": len(reference_cache),
    }
    write_csv(output / "failure_curve_reference.csv", references)
    (output / "independent_audit.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main() -> None:
    """Audit actual independent records without rewriting them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ae"))
    args = parser.parse_args()
    print(json.dumps(audit(args.local_dir, args.old_evidence, args.output)))


if __name__ == "__main__":
    main()
