"""Run predeclared diagnostics in fresh processes, keeping all old artifacts frozen."""

from __future__ import annotations

import argparse
import cProfile
import csv
import ctypes
import json
import logging
import os
import pstats
import subprocess
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from .. import astar, paper_planner, rrt_connect, safety_planner
from ..benchmark import assess_path
from ..metrics import environment_info, path_length
from ..planning import PlanningLimits
from ..postprocessing import shortcut_path
from ..scenarios import load_scenario
from .observation import FirstValidFound, Observation

LOGGER = logging.getLogger(__name__)


def terminate_worker(process: subprocess.Popen, log: TextIO) -> int:
    """Stop only this worker tree, including the Windows venv interpreter child."""
    finished = process.poll()
    if finished is not None:
        return finished
    if os.name == "nt":
        outcome = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=log,
            stderr=log,
            check=False,
        )
        if outcome.returncode and process.poll() is None:
            raise RuntimeError("Windows could not stop the timed-out worker tree")
    else:
        process.kill()
    return process.wait(timeout=5)


def memory_usage() -> dict[str, int | None]:
    """Read this Windows process RSS and lifetime peak, including import/map cost."""
    if os.name != "nt":
        return {"rss_bytes": None, "process_peak_rss_bytes": None}

    class Memory(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            )
        ]

    info = Memory()
    info.cb = ctypes.sizeof(info)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    api = ctypes.WinDLL("psapi", use_last_error=True)
    api.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(Memory),
        ctypes.c_ulong,
    ]
    if not api.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(info), info.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "rss_bytes": info.WorkingSetSize,
        "process_peak_rss_bytes": info.PeakWorkingSetSize,
    }


def profiling_summary(profile: cProfile.Profile) -> dict[str, float]:
    """Group exclusive Python self-time, avoiding nested cumulative double counting."""
    groups = {
        name: 0.0
        for name in (
            "ray_sampling",
            "collision",
            "grid",
            "choose_sun",
            "path_validation",
            "other",
        )
    }
    for (filename, _, function), data in pstats.Stats(profile).stats.items():
        key = (
            "collision"
            if "collision_checker.py" in filename
            else "ray_sampling"
            if "sampling.py" in filename
            else "grid"
            if "grid_candidates.py" in filename
            else "choose_sun"
            if function == "_choose_sun"
            else "path_validation"
            if function in ("_free", "reconstruct", "validated_path")
            else "other"
        )
        groups[key] += data[2]
    total = sum(groups.values())
    return {
        **{f"{k}_self_seconds": v for k, v in groups.items()},
        **{f"{k}_fraction": v / total if total else 0 for k, v in groups.items()},
    }


def execute(job: dict[str, Any], directory: Path) -> dict[str, Any]:
    """Execute one actual trial with map loading outside the search timer."""
    scenario = load_scenario(Path(job["map_config"]), job["scene"])
    limits = PlanningLimits(job["seconds"], job["max_nodes"], 10000)
    method = job["method"]
    options = job["parameters"]
    observer = Observation(
        scenario.grid,
        scenario.start,
        scenario.goal,
        options,
        directory / "events.jsonl" if job["detail"] else None,
        job["stop_first"],
    )
    planner = {
        "safety_reference": safety_planner.plan,
        "paper_reimplementation": paper_planner.plan,
        "astar": astar.plan,
        "rrt_connect": rrt_connect.plan,
    }[method]
    initial_memory = memory_usage()
    started = time.perf_counter()
    profile = cProfile.Profile() if job["measurement"] == "profile" else None
    if profile:
        profile.enable()
    try:
        if (
            method in ("safety_reference", "paper_reimplementation")
            and job["measurement"] != "unobserved"
        ):
            with observer.installed():
                try:
                    result = planner(
                        scenario.grid,
                        scenario.start,
                        scenario.goal,
                        job["seed"],
                        limits,
                        options,
                    )
                except FirstValidFound:
                    result = observer.first_result(method, limits)
        else:
            result = planner(
                scenario.grid,
                scenario.start,
                scenario.goal,
                job["seed"],
                limits,
                options,
            )
    finally:
        if profile:
            profile.disable()
    call_seconds = time.perf_counter() - started
    measured_memory = memory_usage()
    verdict = assess_path(result.raw_path, scenario.grid, scenario.start, scenario.goal)
    metrics = (
        observer.metrics(result, job["seconds"])
        if observer.started
        else {
            "time_to_first_valid_path_s": None,
            "first_valid_path_length": None,
            "first_valid_expanded_nodes": None,
            "last_valid_path_length": None,
            "time_to_last_improvement_s": None,
            "incumbent_history": [],
            "valid_solution_found_by_30s": None,
            "valid_solution_found_by_budget": None,
            "normal_completion_by_30s": result.status == "ok" and call_seconds <= 30,
            "search_stop_reason": result.termination_reason,
        }
    )
    if method in ("astar", "rrt_connect") and verdict["valid"]:
        confirmed = time.perf_counter() - started
        metrics.update(
            time_to_first_valid_path_s=confirmed,
            first_valid_path_length=verdict["length"],
            first_valid_expanded_nodes=result.counters.expanded_nodes,
            last_valid_path_length=verdict["length"],
            time_to_last_improvement_s=confirmed,
            valid_solution_found_by_30s=confirmed <= 30,
            valid_solution_found_by_budget=confirmed <= job["seconds"],
            incumbent_history=[{"time_s": confirmed, "length": verdict["length"]}],
        )
    common_path = (
        shortcut_path(result.raw_path, scenario.grid) if verdict["valid"] else None
    )
    row = {
        "job_id": job["job_id"],
        "phase": job["phase"],
        "scene": job["scene"],
        "method": method,
        "seed": job["seed"],
        "measurement": job["measurement"],
        "parameters": options,
        "time_budget_s": job["seconds"],
        "max_nodes": job["max_nodes"],
        "status": result.status,
        "termination_reason": result.termination_reason,
        "reported_success": result.reported_success,
        "strict_valid": verdict["valid"],
        "raw_length": verdict["length"],
        "common_post_length": path_length(common_path) if common_path else None,
        "common_post_valid": assess_path(
            common_path, scenario.grid, scenario.start, scenario.goal
        )["valid"],
        "search_seconds": result.search_seconds,
        "call_seconds": call_seconds,
        "initial_rss_bytes": initial_memory["rss_bytes"],
        **measured_memory,
        **asdict(result.counters),
        **metrics,
        "first_time_definition": "verified internal goal path"
        if observer.started
        else "first returned path after independent validation"
        if method in ("astar", "rrt_connect")
        else "not observed",
        "profiler": profiling_summary(profile) if profile else None,
        "diagnostic_only": True,
    }
    evidence = {
        "job": job,
        "row": row,
        "result": asdict(result),
        "raw_validation": verdict,
        "common_post_path": common_path,
        "environment": environment_info(),
    }
    (directory / "result.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return evidence


class Experiment:
    """Dispatch immutable jobs serially and reuse only identical stage-three specs."""

    def __init__(self, root: Path, output: Path) -> None:
        self.root, self.output = root.resolve(), output.resolve()
        repository = Path(__file__).resolve().parents[3]
        self.protocol = json.loads(
            (repository / "configs/stage3_protocol.json").read_text(encoding="utf-8")
        )
        if self.root.is_relative_to(repository):
            raise ValueError("Full experiment evidence must be outside the repository")
        self.root.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        phase: str,
        scene: str,
        method: str = "safety_reference",
        seed: int = 0,
        parameters: dict | None = None,
        seconds: int = 30,
        nodes: int = 100000,
        measurement: str = "observed",
        stop: bool = False,
        map_config: str = "configs/stage2_maps.json",
    ) -> dict:
        parameters = parameters or {}
        identity = "_".join(
            [
                scene,
                method,
                str(seed),
                str(seconds),
                str(nodes),
                measurement,
                str(int(stop)),
                *[f"{k}-{v}" for k, v in sorted(parameters.items())],
            ]
        )
        job = {
            "job_id": identity,
            "phase": phase,
            "scene": scene,
            "method": method,
            "seed": seed,
            "parameters": parameters,
            "seconds": seconds,
            "max_nodes": nodes,
            "measurement": measurement,
            "stop_first": stop,
            "detail": scene == "S1" and seed == 0,
            "map_config": map_config,
        }
        directory = self.root / identity
        result_file = directory / "result.json"
        if directory.exists():
            if not result_file.is_file():
                raise FileExistsError(
                    f"Incomplete trial requires explicit review: {directory}"
                )
            evidence = json.loads(result_file.read_text(encoding="utf-8"))
            previous = dict(evidence["job"])
            previous["phase"] = phase
            if previous != job:
                raise ValueError("Existing trial specification differs")
            return evidence["row"]
        directory.mkdir()
        (directory / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
        with (directory / "console.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gsunlight_repro.stage3.experiment",
                    "--job",
                    str(directory / "job.json"),
                ],
                stdout=log,
                stderr=log,
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
            try:
                code = process.wait(timeout=seconds + 15)
            except subprocess.TimeoutExpired:
                code = terminate_worker(process, log)
                row = {
                    "job_id": identity,
                    "phase": phase,
                    "scene": scene,
                    "method": method,
                    "seed": seed,
                    "parameters": parameters,
                    "status": "hard_timeout",
                    "reported_success": None,
                    "strict_valid": None,
                    "termination_reason": "external_guard",
                    "exit_code": code,
                }
                result_file.write_text(
                    json.dumps({"job": job, "row": row}), encoding="utf-8"
                )
        if code != 0 and not result_file.exists():
            raise RuntimeError(f"Trial failed; inspect {directory / 'console.log'}")
        row = json.loads(result_file.read_text(encoding="utf-8"))["row"]
        LOGGER.info(
            "%s %s seed=%s %s first=%s status=%s reason=%s",
            phase,
            scene,
            seed,
            parameters,
            row.get("time_to_first_valid_path_s"),
            row["status"],
            row["termination_reason"],
        )
        return row

    def table(self, phase: str, rows: list[dict]) -> None:
        """Write a derived phase table; underlying individual results stay immutable."""
        keys = list(dict.fromkeys(k for row in rows for k in row))
        with (self.output / f"{phase}.csv").open(
            "w", encoding="utf-8", newline=""
        ) as stream:
            writer = csv.DictWriter(stream, fieldnames=keys)
            writer.writeheader()
            writer.writerows(
                {
                    k: json.dumps(v, sort_keys=True)
                    if isinstance(v, (dict, list))
                    else v
                    for k, v in row.items()
                }
                for row in rows
            )

    def phase(self, phase: str) -> None:
        """Execute only the predeclared settings for the requested phase."""
        rows = []
        base = {
            "grid_capacity": self.protocol["reference_capacity"],
            "grid_side_length": self.protocol["reference_side_length"],
        }
        if phase == "s3":
            for method in ("paper_reimplementation", "safety_reference"):
                for seed in self.protocol["s3_seeds"]:
                    rows.append(self.run(phase, "S3", method, seed, base))
        elif phase in ("capacity", "size", "sampling"):
            if phase == "sampling":
                prior = list(
                    csv.DictReader((self.output / "capacity.csv").open())
                ) + list(csv.DictReader((self.output / "size.csv").open()))
                if any(
                    r["scene"] == "S1" and r["valid_solution_found_by_budget"] == "True"
                    for r in prior
                ):
                    LOGGER.info(
                        "Sampling trigger not met; A/B already has valid S1 paths"
                    )
                    return
                settings = [
                    {**base, "distance_step": v} if v != 5 else base
                    for v in self.protocol["distance_step_diagnostic"]
                ] + [
                    {**base, "half_cone_degrees": v} if v != 30 else base
                    for v in self.protocol["half_cone_diagnostic"]
                ]
                scenes = ("S1",)
            else:
                settings = (
                    [{**base, "grid_capacity": v} for v in self.protocol["capacity"]]
                    if phase == "capacity"
                    else [
                        {**base, "grid_side_length": v}
                        for v in self.protocol["side_length"]
                    ]
                )
                scenes = self.protocol["scenes"]
            for options in settings:
                for scene in scenes:
                    for seed in self.protocol["seeds"]:
                        rows.append(
                            self.run(phase, scene, seed=seed, parameters=options)
                        )
        elif phase == "astar":
            for scene in self.protocol["astar_scenes"]:
                for nodes in self.protocol["astar_nodes"]:
                    row = self.run(phase, scene, "astar", nodes=nodes)
                    rows.append(row)
                    if row.get("strict_valid"):
                        break
                    if row["termination_reason"] == "time_budget":
                        rows.append(
                            self.run(phase, scene, "astar", seconds=60, nodes=nodes)
                        )
                        break
        elif phase == "profile":
            for measurement in ("unobserved", "observed", "profile"):
                rows.append(
                    self.run(
                        phase,
                        "S3",
                        parameters={**base, "n_max": 10},
                        measurement=measurement,
                    )
                )
        elif phase == "stop":
            prior = list(csv.DictReader((self.output / "s3.csv").open()))
            if not any(
                r.get("time_to_first_valid_path_s")
                and float(r["time_to_first_valid_path_s"])
                < self.protocol["early_solution_seconds"]
                for r in prior
            ):
                LOGGER.info("Early-solution trigger not met")
                return
            for method in ("paper_reimplementation", "safety_reference"):
                for seed in self.protocol["s3_seeds"]:
                    rows.append(self.run(phase, "S3", method, seed, base, stop=True))
        elif phase == "baselines":
            for scene in self.protocol["scenes"]:
                for seed in self.protocol["seeds"]:
                    rows.append(self.run(phase, scene, "rrt_connect", seed))
        elif phase == "holdout":
            candidates: dict[str, dict] = {}
            for name in ("capacity", "size"):
                for row in csv.DictReader((self.output / f"{name}.csv").open()):
                    options = json.loads(row["parameters"])
                    key = json.dumps(options, sort_keys=True)
                    group = candidates.setdefault(
                        key, {"parameters": options, "keys": set(), "success": 0}
                    )
                    trial = (row["scene"], row["seed"])
                    if trial not in group["keys"]:
                        group["keys"].add(trial)
                        group["success"] += (
                            row["valid_solution_found_by_budget"] == "True"
                        )
            reference = candidates[json.dumps(base, sort_keys=True)]
            best = min(
                candidates.values(),
                key=lambda x: (
                    -x["success"],
                    x["parameters"]["grid_capacity"],
                    abs(x["parameters"]["grid_side_length"] - 5),
                ),
            )
            selected = (
                best["parameters"] if best["success"] > reference["success"] else base
            )
            (self.output / "holdout_selection.json").write_text(
                json.dumps(
                    {
                        "baseline": base,
                        "selected": selected,
                        "reference_success": reference["success"],
                        "selected_success": best["success"],
                        "rule": "dev only; strict improvement required",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            options_list = [base] + ([selected] if selected != base else [])
            for scene in ("H1", "H2"):
                for options in options_list:
                    for seed in self.protocol["holdout_seeds"]:
                        rows.append(
                            self.run(
                                phase,
                                scene,
                                seed=seed,
                                parameters=options,
                                map_config="configs/stage3_holdout_maps.json",
                            )
                        )
                for seed in self.protocol["holdout_seeds"]:
                    rows.append(
                        self.run(
                            phase,
                            scene,
                            "rrt_connect",
                            seed,
                            map_config="configs/stage3_holdout_maps.json",
                        )
                    )
        else:
            raise ValueError(f"Unknown phase: {phase}")
        self.table(phase, rows)


def main() -> int:
    """CLI for either a single fresh worker or a predeclared serial phase."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path)
    parser.add_argument(
        "--phase",
        choices=(
            "s3",
            "capacity",
            "size",
            "astar",
            "profile",
            "stop",
            "baselines",
            "sampling",
            "holdout",
        ),
    )
    parser.add_argument("--local-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/stage3"))
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
    )
    if args.job:
        try:
            execute(json.loads(args.job.read_text(encoding="utf-8")), args.job.parent)
        except Exception:
            traceback.print_exc()
            return 1
    else:
        if not args.local_dir or not args.phase:
            parser.error("Phase execution needs --local-dir and --phase")
        Experiment(args.local_dir, args.output).phase(args.phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
