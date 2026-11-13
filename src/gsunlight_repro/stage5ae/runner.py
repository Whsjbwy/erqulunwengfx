"""Gated calibration and serial independent-map experiments with real evidence."""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean

import numpy as np

from ..stage3.experiment import memory_usage
from ..stage4a.runtime import configure_worker
from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT, body_radius, load_scene, mode_radius, read_config
from ..stage5a.planners import plan
from ..stage5a.tracking import track
from ..stage5ar.evidence import compare_public, load_history, path_features
from ..stage5ar.replay import Replay, compare_frozen
from ..stage5ar.runner import shortcut
from ..stage5ar.storage import read_record
from .curves import fillet
from .diagnostics import detail
from .runtime import experiment_lock
from .storage import Records, public_output, write_json
from .tracking import simulate
from .verification import analytic_cases, folded_projection_case

LOGGER = logging.getLogger(__name__)


class Runner:
    """Freeze inputs, enforce E0-E3 gates and never replace failed trials."""

    def __init__(self, history: Path, old: Path, local: Path, output: Path) -> None:
        self.history, self.old, self.local = (
            history.resolve(),
            old.resolve(),
            local.resolve(),
        )
        if self.local.is_relative_to(ROOT) or self.local in (self.history, self.old):
            raise ValueError(
                "Full5AE evidence must be separate from repository/history"
            )
        self.local.mkdir(parents=True, exist_ok=True)
        self.output = public_output(output)
        self.protocol = read_config("stage5ae_protocol.json")
        self.vehicle = read_config("stage5a_protocol.json")
        self.maps = read_config("stage5ae_maps.json")
        configuration = {
            "protocol": self.protocol,
            "vehicle": self.vehicle,
            "maps": self.maps,
        }
        frozen = self.local / "configuration.json"
        if frozen.exists():
            if json.loads(frozen.read_text(encoding="utf-8")) != configuration:
                raise ValueError("Frozen configuration changed; use a new version")
        else:
            write_json(frozen, configuration)
        _, items = load_history(self.history)
        self.items = {item["row"]["job_id"]: item for item in items}
        self.records = Records(self.local, self.old)
        self.scenes = {}

    def require(self, phase: str) -> None:
        """Fail closed on a missing or failed previous gate."""
        marker = self.local / (phase + "_completed.json")
        if (
            not marker.exists()
            or not json.loads(marker.read_text(encoding="utf-8"))["passed"]
        ):
            raise ValueError(f"Requires completed {phase}")

    def finish(self, phase: str, **data) -> None:
        """Write completion only after every operation has actually finished."""
        marker = self.local / (phase + "_completed.json")
        if not marker.exists():
            write_json(marker, {"phase": phase, "passed": True, **data})

    def old_scene(self, identity: str):
        """Reuse frozen old maps exclusively for development/diagnosis."""
        if identity not in self.scenes:
            self.scenes[identity] = load_scene(identity)
        return self.scenes[identity]

    def development_jobs(self) -> list[dict]:
        """Use all157 original eligible selected paths, without new selection."""
        return [
            item["row"]
            for item in self.items.values()
            if item["row"]["phase"] == "holdout" and item["row"]["execution_eligible"]
        ]

    def pilot_jobs(self) -> list[dict]:
        """Choose exactly two old cases per map using historical outcomes only."""
        output = []
        groups = defaultdict(list)
        for row in self.development_jobs():
            groups[row["scene"]].append(row)
        for group in groups.values():
            failures = [row for row in group if not row["execution_success"]]
            successes = [row for row in group if row["execution_success"]]

            def order(row: dict) -> tuple:
                return row["simulation_time_s"], row["job_id"]

            output.append(min(failures, key=order))
            output.append(
                min(successes, key=order) if successes else max(failures, key=order)
            )
        return output

    def e0(self) -> None:
        """Verify analytic cases, fixed historical replay and all failure metadata."""
        analytic = analytic_cases()
        pilot = self.pilot_jobs()
        for row in pilot:
            item = self.items[row["job_id"]]
            path_id = row["selected_path_id"]
            path = item["paths"][path_id]
            scene = self.old_scene(row["scene"])
            margin = 0.25 if row["geometry_mode"] == "margin" else 0.0
            actual = simulate(
                path, scene, self.vehicle, margin, self.protocol["legacy"]
            )
            compare_frozen(actual.summary, item["executions"][str(path_id)])
            compare_frozen(actual.summary, track(path, scene, self.vehicle, margin))
        pairs = {
            row["job_id"]: row
            for row in json.loads(
                (self.old / "shortcut_pairs.json").read_text(encoding="utf-8")
            )
        }
        failures, jumps = [], []
        for file in sorted((self.old / "replays").glob("*.json.gz")):
            record = read_record(file)
            row = record["summary"]
            item = self.items[row["job_id"]]
            path = (
                pairs[row["job_id"]]["shortcut_coordinates"]
                if row["variant"] == "shortcut"
                else item["paths"][row["path_id"]]
            )
            extras, events = detail(
                Replay(row, record["trace"]),
                path,
                self.old_scene(row["scene"]),
                body_radius(self.vehicle),
            )
            identity = {
                key: row[key]
                for key in (
                    "job_id",
                    "scene",
                    "family",
                    "mode",
                    "method",
                    "seed",
                    "path_uid",
                    "variant",
                    "condition_id",
                )
            }
            if not row["execution_success"]:
                failures.append(
                    {**identity, "primary_class": row["primary_class"], **extras}
                )
            jumps.extend({**identity, **event} for event in events)
        write_csv(self.output / "historical_failures.csv", failures)
        write_csv(self.output / "historical_projection_jumps.csv", jumps)
        write_csv(
            self.output / "development_pilot_manifest.csv",
            [
                {
                    key: row[key]
                    for key in (
                        "job_id",
                        "scene",
                        "method",
                        "geometry_mode",
                        "seed",
                        "execution_reason",
                    )
                }
                for row in pilot
            ],
        )
        write_json(self.output / "e0_analytic.json", analytic)
        write_json(
            self.output / "e0_audit.json",
            {
                **compare_public(
                    list(self.items.values()), ROOT / "results/stage5a/runs.csv"
                ),
                "replayed_legacy_paths": len(pilot),
                "historical_failures_augmented": len(failures),
                "projection_jump_markers": len(jumps),
                "synthetic_fold": folded_projection_case(),
            },
        )
        self.finish("e0", historical_failures=len(failures), replayed=len(pilot))

    def execute(
        self,
        row: dict,
        processing: str,
        path: list,
        controller: dict,
        scene,
        phase: str,
        alias: str | None = None,
    ) -> dict:
        """Evaluate one exact path/controller pair, reusing complete evidence."""
        job = row["job_id"]
        identity = f"{job}--{processing}--{controller['id']}"
        mode = row.get("geometry_mode", row.get("mode"))
        meta = {
            "case_id": identity,
            "job_id": job,
            "scene": row["scene"],
            "family": scene.specification["family"],
            "method": row["method"],
            "seed": row["seed"],
            "mode": mode,
            "phase": phase,
            "processing": processing,
            "controller": controller["id"],
            "lookahead_m": controller["lookahead_m"],
            "path_id": job + "::" + processing,
            "raw_path_id": job + "::raw" if processing != "selected" else None,
            "shortcut_source_id": job + "::raw" if processing == "shortcut" else None,
            "protocol_id": self.protocol["protocol_id"],
        }
        if self.records.path(identity).exists():
            record = self.records.read(identity)
            if record["meta"] != meta:
                raise ValueError("Existing execution condition changed")
            return record["summary"]
        old_name = None
        if phase == "development" and controller["kind"] == "legacy":
            old_item = self.items[job]
            index = (
                old_item["row"]["selected_path_id"]
                if processing == "selected"
                else old_item["row"]["raw_path_id"]
            )
            old_name = f"{job}--{processing}-p{index}--baseline.json.gz"
            old_record = read_record(self.old / "replays" / old_name)
            result = Replay(old_record["summary"], old_record["trace"])
        elif alias is not None and self.records.path(alias).exists():
            old_record = self.records.read(alias)
            result = Replay(old_record["summary"], old_record["trace"])
        else:
            result = simulate(
                path, scene, self.vehicle, 0.25 if mode == "margin" else 0.0, controller
            )
        if result.summary["primary_class"] == "resource_timeout":
            write_json(self.local / (identity + ".error.json"), result.summary)
            raise RuntimeError(
                "Execution wall guard reached; review before further phases"
            )
        geometry = path_features(path, scene, self.vehicle, mode)
        extras, _ = detail(result, path, scene, body_radius(self.vehicle))
        summary = {**result.summary, **geometry, **extras}
        record = {"meta": meta, "summary": summary}
        if old_name:
            record["history_reference"] = old_name
        elif alias is not None and self.records.path(alias).exists():
            record["trace_reference"] = alias
        else:
            record["trace"] = result.trace
        self.records.save(identity, record)
        LOGGER.info(
            "%s %s %s %s",
            row["scene"],
            processing,
            controller["id"],
            summary["primary_class"],
        )
        return summary

    def e1(self, pilot: bool) -> None:
        """Run the small controller gate before the complete one-time selection."""
        self.require("e0" if pilot else "e1_pilot")
        jobs = self.pilot_jobs() if pilot else self.development_jobs()
        for controller in [
            self.protocol["legacy"],
            *self.protocol["controller_candidates"],
        ]:
            for row in jobs:
                item = self.items[row["job_id"]]
                self.execute(
                    row,
                    "selected",
                    item["paths"][row["selected_path_id"]],
                    controller,
                    self.old_scene(row["scene"]),
                    "development",
                )
        if not pilot:
            results = [
                record
                for record in self.records.all()
                if record["meta"]["processing"] == "selected"
            ]
            scores = []
            for controller in self.protocol["controller_candidates"]:
                by_map = defaultdict(list)
                for record in results:
                    if record["meta"]["controller"] == controller["id"]:
                        by_map[record["meta"]["scene"]].append(record["summary"])
                if sum(len(rows) for rows in by_map.values()) != 157:
                    raise ValueError("Development candidate cohort incomplete")
                scores.append(
                    {
                        "controller": controller,
                        "strict_map_mean": mean(
                            mean(row["execution_success"] for row in group)
                            for group in by_map.values()
                        ),
                        "nominal_map_mean": mean(
                            mean(row["physical_execution_success"] for row in group)
                            for group in by_map.values()
                        ),
                        "rms_map_mean_m": mean(
                            mean(row["rms_tracking_error_m"] for row in group)
                            for group in by_map.values()
                        ),
                    }
                )
            chosen = max(
                scores,
                key=lambda row: (
                    row["strict_map_mean"],
                    row["nominal_map_mean"],
                    -row["rms_map_mean_m"],
                    -row["controller"]["lookahead_m"],
                ),
            )
            target = self.local / "selection.json"
            if not target.exists():
                write_json(
                    target,
                    {
                        "chosen": chosen["controller"],
                        "all_candidates": scores,
                        "selection_scope": "old_six_maps_only_once",
                    },
                )
        self.finish("e1_pilot" if pilot else "e1", paths=len(jobs))

    def e2(self) -> None:
        """Run same-source processing/controller pairs and bounded fillet references."""
        self.require("e1")
        chosen = json.loads(
            (self.local / "selection.json").read_text(encoding="utf-8")
        )["chosen"]
        processing_rows = []
        for row in self.development_jobs():
            item = self.items[row["job_id"]]
            scene = self.old_scene(row["scene"])
            raw = item["paths"][row["raw_path_id"]]
            started = time.perf_counter()
            shortened, indices = shortcut(
                raw, scene, mode_radius(row["geometry_mode"], self.vehicle)
            )
            cost = time.perf_counter() - started
            for controller in (self.protocol["legacy"], chosen):
                for label, path in (("raw", raw), ("shortcut", shortened)):
                    selected_path = item["paths"][row["selected_path_id"]]
                    alias = (
                        f"{row['job_id']}--selected--{controller['id']}"
                        if path == selected_path
                        else None
                    )
                    self.execute(
                        row, label, path, controller, scene, "development", alias
                    )
            reference = fillet(
                raw,
                scene.geometry(mode_radius(row["geometry_mode"], self.vehicle)),
                1 / math.radians(10),
            )
            processing_rows.append(
                {
                    "job_id": row["job_id"],
                    "scene": row["scene"],
                    "raw_path_id": row["job_id"] + "::raw",
                    "shortcut_source_id": row["job_id"] + "::raw",
                    "shortcut_path_id": row["job_id"] + "::shortcut",
                    "source_indices": indices,
                    "processing_cost_s": cost,
                    **{
                        key: value
                        for key, value in reference.items()
                        if key != "display_points"
                    },
                }
            )
        write_csv(self.output / "processing_reference.csv", processing_rows)
        self.finish(
            "e2", paired_tasks=len(processing_rows), third_formal_processing=False
        )

    def freeze(self) -> None:
        """Publish selection before generating or searching the independent maps."""
        self.require("e2")
        selection = json.loads(
            (self.local / "selection.json").read_text(encoding="utf-8")
        )
        path = ROOT / "configs/stage5ae_selected.json"
        if not path.exists():
            write_json(path, selection)
        elif json.loads(path.read_text(encoding="utf-8")) != selection:
            raise ValueError("Prospective selection differs")
        self.finish("freeze", chosen=selection["chosen"])

    def formal(self, gate: bool) -> None:
        """Execute the independent resource gate, then all360 predeclared tasks."""
        self.require("freeze" if gate else "gate")
        from .maps import generate, validate_maps

        map_audit = self.output / "independent_map_audit.json"
        if not map_audit.exists():
            write_json(map_audit, validate_maps(self.maps, self.vehicle))
        selected = read_config("stage5ae_selected.json")["chosen"]
        directory = self.local / "planning"
        directory.mkdir(exist_ok=True)
        for spec in self.maps["maps"]:
            if gate and spec["id"] not in self.protocol["gate_maps"]:
                continue
            scene = generate(spec, self.maps)
            for seed in (
                self.protocol["gate_seeds"] if gate else self.protocol["planning_seeds"]
            ):
                for method in self.protocol["methods"]:
                    for mode in self.protocol["modes"]:
                        job = f"independent_{spec['id']}_{method}_{mode}_seed{seed}"
                        file = directory / (job + ".json")
                        if file.exists():
                            evidence = json.loads(file.read_text(encoding="utf-8"))
                        else:
                            random.seed(seed)
                            np.random.seed(seed)
                            result = plan(
                                scene,
                                method,
                                seed,
                                mode,
                                self.vehicle,
                                seconds=self.protocol["planning_budget_s"],
                                step=5.0,
                            )
                            result["process_peak_rss_bytes"] = memory_usage()[
                                "process_peak_rss_bytes"
                            ]
                            paths = result.pop("paths")
                            history = result.pop("raw_history")
                            result.pop("history")
                            result.pop("checkpoints")
                            raw_id = result.pop("raw_path_id")
                            result.pop("selected_path_id")
                            raw = paths[raw_id] if raw_id is not None else None
                            if (
                                raw is not None
                                and not scene.geometry(mode_radius(mode, self.vehicle))
                                .path(raw)
                                .valid
                            ):
                                raise RuntimeError(
                                    "Planner returned uncertified geometry"
                                )
                            evidence = {
                                "job_id": job,
                                "scene": spec["id"],
                                "family": spec["family"],
                                "seed": seed,
                                "method": method,
                                "mode": mode,
                                "reachability": scene.reachability(
                                    mode_radius(mode, self.vehicle)
                                ),
                                "search": result,
                                "raw": raw,
                                "first_certificate": history[0] if history else None,
                                "first_path": paths[history[0]["path_id"]]
                                if history
                                else None,
                            }
                            write_json(file, evidence)
                        raw = evidence["raw"]
                        if raw is not None:
                            post = self.local / "planning" / (job + ".processing.json")
                            if not post.exists():
                                started = time.perf_counter()
                                shortened, indices = shortcut(
                                    raw, scene, mode_radius(mode, self.vehicle)
                                )
                                write_json(
                                    post,
                                    {
                                        "shortcut": shortened,
                                        "source_indices": indices,
                                        "processing_cost_s": time.perf_counter()
                                        - started,
                                    },
                                )
                            processed = json.loads(post.read_text(encoding="utf-8"))
                            for controller in (self.protocol["legacy"], selected):
                                for label, path in (
                                    ("raw", raw),
                                    ("shortcut", processed["shortcut"]),
                                ):
                                    alias = (
                                        f"{job}--raw--{controller['id']}"
                                        if label == "shortcut" and path == raw
                                        else None
                                    )
                                    self.execute(
                                        evidence,
                                        label,
                                        path,
                                        controller,
                                        scene,
                                        "independent",
                                        alias,
                                    )
                        LOGGER.info("PLANNING %s geometry=%s", job, raw is not None)
        self.finish("gate" if gate else "formal", planning_trials=36 if gate else 360)


def main() -> None:
    """Run one explicit gate with single-core, normal-priority configuration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        required=True,
        choices=("e0", "e1_pilot", "e1", "e2", "freeze", "gate", "formal"),
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ae"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    runner = Runner(args.history, args.old_evidence, args.local_dir, args.output)
    with experiment_lock(runner.local):
        configure_worker()
        if args.phase in ("e1", "e1_pilot"):
            runner.e1(args.phase == "e1_pilot")
        elif args.phase in ("gate", "formal"):
            runner.formal(args.phase == "gate")
        else:
            getattr(runner, args.phase)()


if __name__ == "__main__":
    main()
