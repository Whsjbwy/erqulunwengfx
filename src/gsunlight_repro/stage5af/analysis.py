"""Complete paired ledgers with three denominators and whole-map intervals."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT
from ..stage5ae.analysis import flatten, map_summary
from ..stage5ae.runtime import experiment_lock
from .storage import public_output

CONTROLLERS = ("legacy", "los_d2", "los_terminal_v1")


def planning_rows(directory: Path, phase: str) -> list[dict]:
    """Keep every registered source, including missing paths and negative envelopes."""
    rows = []
    for file in sorted(directory.glob("*.json")):
        if file.name.endswith(".processing.json"):
            continue
        value = json.loads(file.read_text(encoding="utf-8"))
        rows.append(
            {
                **{
                    key: value[key]
                    for key in (
                        "job_id",
                        "scene",
                        "family",
                        "method",
                        "mode",
                        "seed",
                        "reachability",
                    )
                },
                "phase": phase,
                "geometry_success": value["raw"] is not None,
                **value["search"],
                "raw_registry_path_id": value["search"].get("raw_path_id"),
                "raw_path_id": value["job_id"] + "::raw"
                if value["raw"] is not None
                else None,
            }
        )
    return rows


def paired(rows: list[dict]) -> list[dict]:
    """Separate old-LOS and legacy contrasts from processing, retaining losses."""
    index = {(row["job_id"], row["processing"], row["controller"]): row for row in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate condition identity")
    output = []
    for job in sorted({row["job_id"] for row in rows}):
        contrasts = [
            (f"terminal_{p}", (p, "los_d2"), (p, "los_terminal_v1"))
            for p in ("raw", "shortcut")
        ]
        contrasts += [
            (f"legacy_{p}", (p, "legacy"), (p, "los_terminal_v1"))
            for p in ("raw", "shortcut")
        ]
        contrasts += [
            (f"processing_{c}", ("raw", c), ("shortcut", c)) for c in CONTROLLERS
        ]
        for factor, first, second in contrasts:
            if (job, *first) not in index or (job, *second) not in index:
                raise ValueError("Missing paired condition")
            a, b = index[(job, *first)], index[(job, *second)]
            error_a, error_b = (
                a.get("max_tracking_error_m"),
                b.get("max_tracking_error_m"),
            )
            improved = error_a is not None and error_b is not None and error_b < error_a
            output.append(
                {
                    **{
                        key: a[key]
                        for key in (
                            "job_id",
                            "scene",
                            "family",
                            "method",
                            "mode",
                            "phase",
                            "reachability",
                        )
                    },
                    "factor": factor,
                    "first_case_id": a["case_id"],
                    "second_case_id": b["case_id"],
                    "first_success": a["execution_success"],
                    "second_success": b["execution_success"],
                    "delta_success": int(b["execution_success"])
                    - int(a["execution_success"]),
                    "first_class": a["primary_class"],
                    "second_class": b["primary_class"],
                    "second_terminal_switch_time_s": b.get("terminal_switch_time_s"),
                    "preterminal_steps_checked": b.get("preterminal_steps_checked"),
                    "error_improved": improved,
                    "error_improved_but_safety_rejected": improved
                    and b["primary_class"]
                    in (
                        "swept_safety_reject",
                        "mission_band_reject",
                        "margin_only_failure",
                    ),
                }
            )
    return output


def interval(numerator: list[int], denominator: list[int]) -> tuple:
    """Use registered map-cluster bootstrap; undefined ratios remain missing."""
    if not sum(denominator):
        return None, None
    rng = np.random.default_rng(65988)
    indices = rng.integers(0, len(numerator), (2000, len(numerator)))
    den = np.array(denominator)[indices].sum(axis=1)
    num = np.array(numerator)[indices].sum(axis=1)
    values = num[den > 0] / den[den > 0]
    low, high = np.quantile(values, [0.025, 0.975])
    return float(low), float(high)


def clusters(maps: list[dict]) -> list[dict]:
    """Report separate task ratios and map clusters for each controller cell."""
    groups = defaultdict(list)
    for row in maps:
        groups[
            tuple(row[k] for k in ("method", "mode", "processing", "controller"))
        ].append(row)
    output = []
    for key, group in sorted(groups.items()):
        value = dict(
            zip(("method", "mode", "processing", "controller"), key, strict=True)
        )
        value.update(
            map_clusters=len(group),
            known_feasible_tasks=sum(r["known_feasible_tasks"] for r in group),
            execution_eligible=sum(r["execution_eligible"] for r in group),
            execution_successes=sum(r["execution_successes"] for r in group),
        )
        for label, n, d in (
            ("geometry", "geometry_successes", "known_feasible_tasks"),
            ("conditional", "execution_successes", "execution_eligible"),
            ("end_to_end", "execution_successes", "known_feasible_tasks"),
        ):
            ns, ds = [r[n] for r in group], [r[d] for r in group]
            low, high = interval(ns, ds)
            value.update(
                {
                    label + "_rate": sum(ns) / sum(ds) if sum(ds) else None,
                    label + "_ci95_low": low,
                    label + "_ci95_high": high,
                }
            )
        output.append(value)
    return output


def paired_clusters(rows: list[dict]) -> list[dict]:
    """Bootstrap paired end-to-end differences without treating seeds as maps."""
    groups = defaultdict(list)
    for row in rows:
        if row["reachability"].startswith("certified_reachable"):
            groups[(row["method"], row["mode"], row["factor"])].append(row)
    output = []
    for (method, mode, factor), group in sorted(groups.items()):
        maps = defaultdict(list)
        for row in group:
            maps[row["scene"]].append(row)
        ns = [sum(r["delta_success"] for r in g) for g in maps.values()]
        ds = [len(g) for g in maps.values()]
        low, high = interval(ns, ds)
        output.append(
            {
                "method": method,
                "mode": mode,
                "factor": factor,
                "map_clusters": len(maps),
                "paired_tasks": len(group),
                "recovered": sum(r["delta_success"] == 1 for r in group),
                "lost": sum(r["delta_success"] == -1 for r in group),
                "end_to_end_delta": sum(ns) / sum(ds),
                "ci95_low": low,
                "ci95_high": high,
            }
        )
    return output


def enrich(
    planning: list[dict], actual: list[dict], source: Path, phase: str
) -> list[dict]:
    """Add all no-path conditions explicitly instead of inventing tracking runs."""
    present = {(r["job_id"], r["processing"], r["controller"]) for r in actual}
    for plan in planning:
        for processing in ("raw", "shortcut"):
            for controller in CONTROLLERS:
                key = (plan["job_id"], processing, controller)
                if key in present:
                    continue
                if plan["geometry_success"]:
                    raise ValueError("Solved task missing an execution condition")
                actual.append(
                    {
                        **{
                            k: plan[k]
                            for k in (
                                "job_id",
                                "scene",
                                "family",
                                "method",
                                "mode",
                                "seed",
                            )
                        },
                        "case_id": "--".join(key),
                        "phase": phase,
                        "processing": processing,
                        "controller": controller,
                        "was_run": False,
                        "eligible": False,
                        "execution_success": False,
                        "physical_execution_success": False,
                        "primary_class": "envelope_unreachable"
                        if plan["reachability"].startswith("certified_unreachable")
                        else "planning_no_path",
                        "path_id": None,
                        "raw_path_id": None,
                        "length_m": None,
                    }
                )
    plans = {r["job_id"]: r for r in planning}
    for row in actual:
        plan = plans[row["job_id"]]
        post = source / (row["job_id"] + ".processing.json")
        row.update(
            reachability=plan["reachability"],
            first_valid_time_s=plan["first_valid_time_s"],
            planning_actual_total_s=plan["actual_total_s"],
            processing_cost_s=json.loads(post.read_text(encoding="utf-8"))[
                "processing_cost_s"
            ]
            if row["was_run"] and row["processing"] == "shortcut"
            else 0.0
            if row["was_run"]
            else None,
        )
    return actual


def analyze(local: Path, old: Path, output: Path, complete: bool = False) -> dict:
    """Rebuild compact results only after writers have finished a phase."""
    output = public_output(output)
    if not (local / "development_completed.json").exists():
        raise ValueError("Finish development before reporting")
    rows = []
    saved = []
    for path in sorted((local / "replays").glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            record = json.load(stream)
        row = flatten(record)
        row["history_reused"] = record.get("prefix_source", {}).get("stage") == "5ae"
        row["trace_reused"] = "prefix_source" in record
        row.update(
            reused_prefix_steps=record.get("prefix_steps", 0), source_evidence=path.name
        )
        rows.append(row)
        saved.append(record)
    development = [r for r in rows if r["phase"] == "development"]
    independent = [r for r in rows if r["phase"] == "independent"]
    old_plans = planning_rows(old / "planning", "development")
    solved = {p["job_id"] for p in old_plans if p["geometry_success"]}
    for path in sorted((old / "replays").glob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            record = json.load(stream)
        meta = record["meta"]
        if meta["phase"] == "independent" and meta["job_id"] in solved:
            row = flatten(record)
            row.update(
                phase="development",
                source_evidence="stage5ae/replays/" + path.name,
                historical_reference=True,
            )
            development.append(row)
    development = enrich(old_plans, development, old / "planning", "development")
    write_csv(output / "development_runs.csv", development)
    write_csv(
        output / "development_map_summary.csv",
        map_summary(old_plans, development, list(CONTROLLERS)),
    )
    dev_pairs = paired(development)
    write_csv(output / "development_paired.csv", dev_pairs)
    with (ROOT / "results/stage5ae/terminal_diagnostics.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        diagnosed = [
            r
            for r in csv.DictReader(stream)
            if r["controller"] == "los_d2"
            and r["nearest_at_endpoint"] == r["controller_at_endpoint"] == "True"
        ]
    index = {r["case_id"]: r for r in development}
    terminal = []
    for row in diagnosed:
        new = index[row["case_id"].removesuffix("los_d2") + "los_terminal_v1"]
        terminal.append(
            {
                **row,
                "corrected_case_id": new["case_id"],
                "recovered": new["execution_success"],
                "corrected_class": new["primary_class"],
                "corrected_final_error_m": new.get("final_position_error_m"),
                "terminal_switch_time_s": new.get("terminal_switch_time_s"),
                "preterminal_steps_checked": new.get("preterminal_steps_checked"),
            }
        )
    write_csv(output / "terminal54_paired.csv", terminal)
    plans = planning_rows(local / "planning", "independent")
    independent_actual = len(independent)
    if plans:
        independent = enrich(plans, independent, local / "planning", "independent")
        write_csv(output / "planning_runs.csv", plans)
        write_csv(output / "execution_runs.csv", independent)
        maps = map_summary(plans, independent, list(CONTROLLERS))
        pairs = paired(independent)
        write_csv(output / "map_summary.csv", maps)
        write_csv(output / "cluster_summary.csv", clusters(maps))
        write_csv(output / "independent_paired.csv", pairs)
        write_csv(output / "paired_cluster_summary.csv", paired_clusters(pairs))
    for name, group in (("development", development), ("independent", independent)):
        counts = Counter(
            tuple(
                r[k]
                for k in (
                    "scene",
                    "method",
                    "mode",
                    "processing",
                    "controller",
                    "primary_class",
                    "was_run",
                )
            )
            for r in group
        )
        keys = (
            "scene",
            "method",
            "mode",
            "processing",
            "controller",
            "primary_class",
            "was_run",
        )
        write_csv(
            output / (name + "_failure_counts.csv"),
            [
                {**dict(zip(keys, key, strict=True)), "conditions": n}
                for key, n in sorted(counts.items())
            ],
        )
    accounting = {
        "complete": complete,
        "old_planning_tasks_reused": 360,
        "old_solved_tasks": 306,
        "old_reference_execution_conditions": 1224,
        "new_development_conditions": sum(r["phase"] == "development" for r in rows),
        "development_registered_conditions": len(development),
        "independent_planning_trials": len(plans),
        "independent_geometry_successes": sum(r["geometry_success"] for r in plans),
        "independent_actual_execution_conditions": independent_actual,
        "independent_registered_conditions": len(independent),
        "saved_condition_records": len(saved),
        "prefix_reference_records": sum("prefix_source" in r for r in saved),
        "reused_prefix_steps": sum(r.get("prefix_steps", 0) for r in saved),
        "terminal54_recovered": sum(r["recovered"] for r in terminal),
        "additional_unarchived_serialization_attempts": len(
            list((local / "serialization_failure").glob("*.partial"))
        ),
    }
    if complete and (
        len(plans) != 216 or not (local / "formal_completed.json").exists()
    ):
        raise ValueError("Incomplete independent matrix")
    (output / "experiment_accounting.json").write_text(
        json.dumps(accounting, indent=2), encoding="utf-8"
    )
    return accounting


def main() -> None:
    """Derive completed, fully paired evidence without overwriting source data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5af"))
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    if not (args.local_dir / "development_completed.json").exists():
        raise ValueError("Expected completed5AF development evidence")
    with experiment_lock(args.local_dir):
        print(
            json.dumps(
                analyze(args.local_dir, args.old_evidence, args.output, args.complete)
            )
        )


if __name__ == "__main__":
    main()
