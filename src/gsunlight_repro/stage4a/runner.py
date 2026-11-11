"""Serial fresh-process trials with immutable preregistered specifications."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from ..metrics import environment_info
from ..stage3.experiment import memory_usage, terminate_worker
from .anytime import plan
from .engineering import benchmark
from .maps import CONFIG, load_map, map_features, specifications
from .path_metrics import clearance_lower_bound, turn_count
from .runtime import configure_worker, cpu_busy_fraction, system_snapshot

LOGGER = logging.getLogger(__name__)
VERSION = "stage4a-budgeted-static-v1"


def worker(job_file: Path) -> None:
    """Run one actual search; archive unique improvement paths only once."""
    directory = job_file.parent
    configuration = json.loads(
        (directory.parent / "configuration.json").read_text(encoding="utf-8")
    )
    job = json.loads(job_file.read_text(encoding="utf-8"))
    scene = load_map(job["scene"], configuration["maps"])
    scheduling = configure_worker()
    before = system_snapshot()
    initial = memory_usage()
    result = plan(scene, job["method"], job["seed"], configuration["protocol"])
    peak = memory_usage()
    after = system_snapshot()
    diagnostic_started = time.perf_counter()
    best_path = result.pop("best_path")
    path_metrics = {
        "turn_count": turn_count(
            best_path, configuration["protocol"]["turn_threshold_degrees"]
        )
        if best_path
        else None,
        "clearance_lower_bound": clearance_lower_bound(
            best_path, scene.grid, configuration["protocol"]["clearance_sample_step"]
        )
        if best_path
        else None,
    }
    paths = result.pop("paths")
    history = result.pop("history")
    raw_history = result.pop("raw_history")
    checkpoints = result.pop("checkpoints")
    row = {
        "job_id": job["job_id"],
        **map_features(scene),
        **result,
        **path_metrics,
        "initial_rss_bytes": initial["rss_bytes"],
        **peak,
        "system_cpu_busy_fraction": cpu_busy_fraction(before, after),
        "system_process_count_before": before["process_count"],
        "system_process_count_after": after["process_count"],
        "scheduling": scheduling,
        "post_run_diagnostics_s": time.perf_counter() - diagnostic_started,
    }
    evidence = {
        "job": job,
        "row": row,
        "history": history,
        "raw_history": raw_history,
        "checkpoints": checkpoints,
        "paths": paths,
        "environment": environment_info(),
    }
    with (directory / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)


class Runner:
    """Reuse exactly matching stage4a trials, never previous-stage measurements."""

    def __init__(self, local: Path, output: Path) -> None:
        self.local, self.output = local.resolve(), output.resolve()
        repository = Path(__file__).resolve().parents[3]
        if self.local.is_relative_to(repository):
            raise ValueError("Full evidence must be outside the public repository")
        self.local.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        configuration = {
            "protocol": json.loads(
                CONFIG.with_name("stage4a_protocol.json").read_text(encoding="utf-8")
            ),
            "maps": json.loads(CONFIG.read_text(encoding="utf-8")),
        }
        target = self.local / "configuration.json"
        if target.exists():
            if json.loads(target.read_text(encoding="utf-8")) != configuration:
                raise ValueError(
                    "Frozen configuration differs; use a separate run version"
                )
        else:
            target.write_text(json.dumps(configuration, indent=2), encoding="utf-8")
        self.configuration = configuration
        self.protocol = configuration["protocol"]

    def run(self, scene: str, method: str, seed: int) -> dict[str, Any]:
        """Own one child and preserve explicit errors rather than synthetic success."""
        identity = f"{scene}_{method}_seed{seed}"
        job = {
            "job_id": identity,
            "scene": scene,
            "method": method,
            "seed": seed,
            "version": VERSION,
        }
        directory = self.local / identity
        result = directory / "result.json"
        if directory.exists():
            if not result.exists():
                raise FileExistsError(f"Incomplete trial requires review: {directory}")
            previous = json.loads(result.read_text(encoding="utf-8"))
            if previous["job"] != job:
                raise ValueError("Cached trial specification does not match")
            return previous["row"]
        directory.mkdir()
        job_file = directory / "job.json"
        job_file.write_text(json.dumps(job, indent=2), encoding="utf-8")
        environment = dict(
            os.environ,
            PYTHONIOENCODING="utf-8",
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            MKL_NUM_THREADS="1",
            VTK_SMP_MAX_THREADS="1",
        )
        with (directory / "console.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "gsunlight_repro.stage4a.runner",
                    "--job",
                    str(job_file),
                ],
                stdout=log,
                stderr=log,
                env=environment,
            )
            try:
                code = process.wait(timeout=self.protocol["total_budget_s"] + 45)
            except subprocess.TimeoutExpired:
                code = terminate_worker(process, log)
                (directory / "error.json").write_text(
                    json.dumps({"error": "external_guard", "exit_code": code}),
                    encoding="utf-8",
                )
                raise RuntimeError(
                    f"External guard stopped a worker: {identity}"
                ) from None
        if code or not result.exists():
            raise RuntimeError(
                f"Worker failed: {identity}; inspect {directory / 'console.log'}"
            )
        row = json.loads(result.read_text(encoding="utf-8"))["row"]
        LOGGER.info(
            "%s valid=%s first=%s best=%s attempts=%s total=%.3f",
            identity,
            row["strict_valid"],
            row["first_valid_time_s"],
            row["best_length"],
            row["attempts"],
            row["actual_total_s"],
        )
        return row

    def phase(self, phase: str) -> None:
        """Apply the fixed pilot/development/holdout/negative order."""
        if phase == "pilot":
            scenes = self.protocol["pilot_maps"]
            seeds = self.protocol["pilot_seeds"]
            methods = list(self.protocol["angles"])
        else:
            split = {
                "development": "development",
                "holdout": "holdout",
                "negative": "negative",
            }[phase]
            scenes = [
                s["id"]
                for s in specifications(self.configuration["maps"])
                if s["split"] == split
            ]
            seeds = self.protocol["planning_seeds"]
            methods = self.protocol["methods"]
        for seed in seeds:
            for scene in scenes:
                for method in methods:
                    self.run(scene, method, seed)
        marker = self.local / f"{phase}_completed.json"
        marker.write_text(
            json.dumps(
                {
                    "phase": phase,
                    "design_trials": len(scenes) * len(seeds) * len(methods),
                }
            ),
            encoding="utf-8",
        )


def main() -> int:
    """Worker or serial controller CLI; all errors retain full local evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path)
    parser.add_argument("--local-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/stage4a"))
    parser.add_argument(
        "--phase",
        choices=("engineering", "pilot", "development", "holdout", "negative", "all"),
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
    )
    if args.job:
        try:
            worker(args.job)
        except Exception as error:
            traceback.print_exc()
            (args.job.parent / "error.json").write_text(
                json.dumps({"error": f"{type(error).__name__}: {error}"}),
                encoding="utf-8",
            )
            return 1
        return 0
    if not args.local_dir or not args.phase:
        parser.error("Controller needs --local-dir and --phase")
    runner = Runner(args.local_dir, args.output)
    if args.phase == "engineering":
        scheduling = configure_worker()
        result = benchmark(runner.protocol, runner.local, runner.output)
        print(json.dumps({**result, "scheduling": scheduling}))
    else:
        phases = (
            ("pilot", "development", "holdout", "negative")
            if args.phase == "all"
            else (args.phase,)
        )
        for phase in phases:
            runner.phase(phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
