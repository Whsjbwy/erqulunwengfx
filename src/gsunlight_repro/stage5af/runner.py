"""Locked Gate1 -> development -> freeze -> prospective216 execution."""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from ..stage3.experiment import memory_usage
from ..stage4a.runtime import configure_worker
from ..stage5a.maps import ROOT, body_radius, mode_radius, read_config
from ..stage5a.planners import plan
from ..stage5ae.diagnostics import detail
from ..stage5ae.maps import generate as old_map
from ..stage5ae.runtime import experiment_lock
from ..stage5ae.storage import write_json
from ..stage5ae.tracking import simulate as frozen
from ..stage5ar.evidence import path_features
from ..stage5ar.runner import shortcut
from .storage import Records, check_prefix, public_output
from .tracking import simulate
from .verification import acceptance

LOGGER = logging.getLogger(__name__)


class Runner:
    """Use immutable original inputs and explicit technical completion markers."""

    def __init__(self, local: Path, old: Path, ar: Path, output: Path) -> None:
        self.local, self.old, self.ar = local, old, ar
        self.output = public_output(output)
        self.settings = read_config("stage5af_protocol.json")
        self.vehicle = read_config("stage5a_protocol.json")
        self.maps = read_config("stage5af_maps.json")
        config = {"settings": self.settings, "vehicle": self.vehicle, "maps": self.maps}
        file = local / "configuration.json"
        if file.exists():
            if json.loads(file.read_text(encoding="utf-8")) != config:
                raise ValueError("Frozen5AF configuration drift")
        else:
            write_json(file, config)
        self.history = json.loads(
            (old / "configuration.json").read_text(encoding="utf-8")
        )
        self.records = Records(local, old, ar)
        self.scenes = {}

    def require(self, phase: str) -> None:
        """No expansion before a fully completed preceding gate."""
        marker = self.local / (phase + "_completed.json")
        if (
            not marker.exists()
            or not json.loads(marker.read_text(encoding="utf-8"))["passed"]
        ):
            raise ValueError(f"Requires completed {phase}")

    def finish(self, phase: str, **values) -> None:
        """Write completion after all actual operations, never before them."""
        file = self.local / (phase + "_completed.json")
        if not file.exists():
            write_json(file, {"phase": phase, "passed": True, **values})

    def gate1(self) -> None:
        """Run mathematical, safety and frozen-adapter acceptance first."""
        result = acceptance()
        write_json(self.output / "gate1_analytic.json", result)
        self.finish(
            "gate1",
            command_cases=len(result["commands"]),
            execution_cases=len(result["executions"]),
        )

    def old_jobs(self) -> list[dict]:
        """Read all306 solved original jobs, without an outcome-based subset."""
        rows = []
        for file in sorted((self.old / "planning").glob("*.json")):
            if file.name.endswith(".processing.json"):
                continue
            row = json.loads(file.read_text(encoding="utf-8"))
            if row["raw"] is not None:
                rows.append(row)
        if len(rows) != 306:
            raise ValueError("Expected all306 frozen geometric solutions")
        return rows

    def scene(self, identity: str):
        """Cache one development map without changing its recipe."""
        if identity not in self.scenes:
            spec = next(
                spec for spec in self.history["maps"]["maps"] if spec["id"] == identity
            )
            self.scenes[identity] = old_map(spec, self.history["maps"])
        return self.scenes[identity]

    def execute(
        self,
        row: dict,
        label: str,
        path: list,
        controller: str,
        scene,
        phase: str,
        baseline: dict | None = None,
    ) -> dict:
        """Run one condition, compare all preterminal steps and save one suffix."""
        identity = f"{row['job_id']}--{label}--{controller}"
        meta = {
            "case_id": identity,
            "job_id": row["job_id"],
            "scene": row["scene"],
            "family": row["family"],
            "method": row["method"],
            "mode": row["mode"],
            "seed": row["seed"],
            "phase": phase,
            "processing": label,
            "controller": controller,
            "path_id": row["job_id"] + "::" + label,
            "raw_path_id": row["job_id"] + "::raw",
            "shortcut_source_id": row["job_id"] + "::raw"
            if label == "shortcut"
            else None,
            "protocol_id": self.settings["version"],
            "vehicle_assumptions": "frozen_stage5a_unidentified_sphere_kinematics",
        }
        if self.records.path(identity).exists():
            existing = self.records.read(identity)
            if existing["meta"] != meta:
                raise ValueError("Existing condition identity changed")
            return existing
        margin = (
            self.vehicle["vehicle"]["safety_margin_m"]
            if row["mode"] == "margin"
            else 0.0
        )
        if controller == "los_terminal_v1":
            result = simulate(path, scene, self.vehicle, margin, self.settings)
        else:
            result = frozen(
                path,
                scene,
                self.vehicle,
                margin,
                {
                    "kind": "legacy" if controller == "legacy" else "los3d",
                    "lookahead_m": 3.0
                    if controller == "legacy"
                    else self.settings["lookahead_m"],
                },
            )
        record = {"meta": meta, "summary": result.summary, "trace": result.trace}
        if result.summary["primary_class"] == "resource_timeout":
            write_json(self.local / (identity + ".error.json"), record)
            raise RuntimeError(
                "Execution guard: stop, preserve evidence and do not expand"
            )
        source = None
        if controller == "los_terminal_v1":
            if baseline is None:
                raise ValueError("Corrected condition lacks paired frozen LOS")
            try:
                count = check_prefix(
                    result.trace,
                    baseline["trace"],
                    result.summary.get("terminal_switch_index"),
                )
            except ValueError:
                write_json(self.local / (identity + ".error.json"), record)
                raise
            result.summary["preterminal_steps_checked"] = count
            source = {
                "stage": "5ae" if phase == "development" else "5af",
                "case_id": f"{row['job_id']}--{label}--los_d2",
            }
        extras, _ = detail(result, path, scene, body_radius(self.vehicle))
        record["summary"] = {
            **result.summary,
            **path_features(path, scene, self.vehicle, row["mode"]),
            **extras,
        }
        reused = self.records.save(identity, record, source)
        LOGGER.info(
            "EXEC %s %s switches=%s prefix=%s",
            identity,
            result.summary["primary_class"],
            result.summary.get("terminal_switches"),
            reused,
        )
        return self.records.read(identity)

    def development(self, pilot: bool = False) -> None:
        """Replay old paths only; never perform another old-map search."""
        self.require("gate1" if pilot else "pilot")
        jobs = self.old_jobs()
        if pilot:
            groups = defaultdict(list)
            for row in jobs:
                groups[row["family"]].append(row)
            jobs = [row for group in groups.values() for row in group[:2]]
            manifest = self.output / "pilot_manifest.json"
            identities = [row["job_id"] for row in jobs]
            if manifest.exists():
                if json.loads(manifest.read_text(encoding="utf-8")) != identities:
                    raise ValueError("Fixed pilot manifest changed")
            else:
                write_json(manifest, identities)
        for row in jobs:
            processed = json.loads(
                (
                    self.old / "planning" / (row["job_id"] + ".processing.json")
                ).read_text(encoding="utf-8")
            )
            for label, path in (
                ("raw", row["raw"]),
                ("shortcut", processed["shortcut"]),
            ):
                baseline = self.records.old.read(f"{row['job_id']}--{label}--los_d2")
                self.execute(
                    row,
                    label,
                    path,
                    "los_terminal_v1",
                    self.scene(row["scene"]),
                    "development",
                    baseline,
                )
        self.finish(
            "pilot" if pilot else "development",
            tasks=len(jobs),
            corrected_conditions=2 * len(jobs),
        )

    def freeze(self) -> None:
        """Record the unchanged one-choice parameters before new-map generation."""
        self.require("development")
        self.require("development_audit")
        target = ROOT / "configs/stage5af_selected.json"
        value = {
            "lookahead_m": self.settings["lookahead_m"],
            "terminal_distance_m": self.settings["terminal_distance_m"],
            "selection": "single preregistered setting; no candidate search",
            "third_processing": False,
        }
        if target.exists():
            if json.loads(target.read_text(encoding="utf-8")) != value:
                raise ValueError("Selection drift")
        else:
            write_json(target, value)
        self.finish("freeze", **value)

    def formal(self, gate: bool = False) -> None:
        """Run the resource gate then216 total, always reusing completed jobs."""
        self.require("freeze" if gate else "gate")
        from .maps import generate, validate

        if not (self.output / "independent_map_audit.json").exists():
            write_json(
                self.output / "independent_map_audit.json",
                validate(self.maps, self.vehicle),
            )
        directory = self.local / "planning"
        directory.mkdir(exist_ok=True)
        for spec in self.maps["maps"]:
            if gate and spec["id"] not in self.settings["gate_maps"]:
                continue
            scene = generate(spec, self.maps)
            for seed in (
                self.settings["gate_seeds"] if gate else self.settings["planning_seeds"]
            ):
                for method in self.settings["methods"]:
                    for mode in self.settings["modes"]:
                        job = f"independent_{spec['id']}_{method}_{mode}_seed{seed}"
                        file = directory / (job + ".json")
                        if file.exists():
                            row = json.loads(file.read_text(encoding="utf-8"))
                        else:
                            random.seed(seed)
                            np.random.seed(seed)
                            result = plan(
                                scene,
                                method,
                                seed,
                                mode,
                                self.vehicle,
                                seconds=self.settings["planning_budget_s"],
                                step=self.settings["step_m"],
                            )
                            paths = result.pop("paths")
                            history = result.pop("raw_history")
                            result.pop("history")
                            result.pop("checkpoints")
                            raw_id = result["raw_path_id"]
                            result["process_peak_rss_bytes"] = memory_usage()[
                                "process_peak_rss_bytes"
                            ]
                            row = {
                                "job_id": job,
                                "scene": spec["id"],
                                "family": spec["family"],
                                "method": method,
                                "seed": seed,
                                "mode": mode,
                                "reachability": scene.reachability(
                                    mode_radius(mode, self.vehicle)
                                ),
                                "search": result,
                                "raw": paths[raw_id] if raw_id is not None else None,
                                "first_certificate": history[0] if history else None,
                                "first_path": paths[history[0]["path_id"]]
                                if history
                                else None,
                            }
                            if (
                                row["raw"] is not None
                                and not scene.geometry(mode_radius(mode, self.vehicle))
                                .path(row["raw"])
                                .valid
                            ):
                                raise RuntimeError("Planner returned unsafe geometry")
                            write_json(file, row)
                        if row["raw"] is not None:
                            post = directory / (job + ".processing.json")
                            if not post.exists():
                                started = time.perf_counter()
                                shortened, indices = shortcut(
                                    row["raw"], scene, mode_radius(mode, self.vehicle)
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
                            for label, path in (
                                ("raw", row["raw"]),
                                ("shortcut", processed["shortcut"]),
                            ):
                                previous = None
                                for controller in self.settings["controllers"]:
                                    record = self.execute(
                                        row,
                                        label,
                                        path,
                                        controller,
                                        scene,
                                        "independent",
                                        previous,
                                    )
                                    if controller == "los_d2":
                                        previous = record
                        LOGGER.info("PLAN %s geometry=%s", job, row["raw"] is not None)
        self.finish("gate" if gate else "formal", planning_trials=18 if gate else 216)


def main() -> None:
    """Acquire ownership before reading history or doing any experiment work."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("gate1", "pilot", "development", "freeze", "gate", "formal"),
        required=True,
    )
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--ar-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5af"))
    args = parser.parse_args()
    local, old, ar = (
        args.local_dir.resolve(),
        args.old_evidence.resolve(),
        args.ar_evidence.resolve(),
    )
    if (
        local.is_relative_to(ROOT)
        or local.is_relative_to(old)
        or local.is_relative_to(ar)
        or old.is_relative_to(local)
        or ar.is_relative_to(local)
    ):
        raise ValueError(
            "Full5AF evidence must be separate from repository and history"
        )
    local.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with experiment_lock(local):
        worker = configure_worker()
        if not (local / "worker.json").exists():
            write_json(local / "worker.json", worker)
        if list(local.glob("*.error.json")):
            raise RuntimeError("Unresolved error evidence; review before resuming")
        runner = Runner(local, old, ar, args.output)
        if args.phase in ("pilot", "development"):
            runner.development(args.phase == "pilot")
        elif args.phase in ("gate", "formal"):
            runner.formal(args.phase == "gate")
        else:
            getattr(runner, args.phase)()


if __name__ == "__main__":
    main()
