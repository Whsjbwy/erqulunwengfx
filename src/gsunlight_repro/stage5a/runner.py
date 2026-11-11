"""Fresh-process staged experiments with immutable single-copy local evidence."""

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

from ..metrics import endpoints_match, environment_info
from ..stage3.experiment import memory_usage, terminate_worker
from ..stage4a.runtime import configure_worker, cpu_busy_fraction, system_snapshot
from .maps import ROOT, body_radius, load_scene, mode_radius, read_config
from .planners import plan
from .tracking import track

LOGGER = logging.getLogger(__name__)


def worker(job_file: Path) -> None:
    """Plan once, revalidate snapshots and separately execute raw/selected paths."""
    directory = job_file.parent
    job = json.loads(job_file.read_text(encoding="utf-8"))
    config = json.loads(
        (directory.parent / "configuration.json").read_text(encoding="utf-8")
    )
    protocol = config["protocol"]
    scheduling = configure_worker()
    loaded = time.perf_counter()
    scene = load_scene(job["scene"], config["maps"])
    reachability = {
        mode: scene.reachability(mode_radius(mode, protocol))
        for mode in protocol["geometry_modes"]
    }
    generation_s = time.perf_counter() - loaded
    before = system_snapshot()
    initial = memory_usage()
    result = plan(
        scene,
        job["method"],
        job["seed"],
        job["geometry_mode"],
        protocol,
        seconds=job["seconds"],
        step=job["step_m"],
    )
    if result["strict_geometry_valid"] and reachability[
        job["geometry_mode"]
    ].startswith("certified_unreachable"):
        raise RuntimeError("Planner contradicted an analytic infeasibility certificate")
    planning_peak = memory_usage()
    after = system_snapshot()
    paths, history, raw_history, checkpoints = (
        result.pop(key) for key in ("paths", "history", "raw_history", "checkpoints")
    )
    audit_started = time.perf_counter()
    validator = scene.geometry(result["radius_m"])
    for path in paths:
        if not validator.path(path).valid or not endpoints_match(
            path, scene.start, scene.goal
        ):
            raise RuntimeError(
                "Archived planning path failed independent full-path recheck"
            )
    for event in history + raw_history:
        if event["time_s"] > job["seconds"]:
            raise RuntimeError("A late certificate was credited")
    audit_s = time.perf_counter() - audit_started
    evaluated = {}
    margin = (
        protocol["vehicle"]["safety_margin_m"]
        if job["geometry_mode"] == "margin"
        else 0.0
    )
    for path_id in (result["raw_path_id"], result["selected_path_id"]):
        if path_id is not None and str(path_id) not in evaluated:
            evaluated[str(path_id)] = track(paths[path_id], scene, protocol, margin)
    selected = evaluated.get(str(result["selected_path_id"]))
    raw = evaluated.get(str(result["raw_path_id"]))
    selected_path = paths[result["selected_path_id"]] if selected is not None else None
    body_valid = (
        scene.geometry(body_radius(protocol)).path(selected_path).valid
        if selected_path is not None
        else None
    )
    margin_valid = (
        scene.geometry(body_radius(protocol) + protocol["vehicle"]["safety_margin_m"])
        .path(selected_path)
        .valid
        if selected_path is not None
        else None
    )
    row = {
        **job,
        **result,
        "family": scene.specification["family"],
        "split": scene.specification["split"],
        "map_seed": scene.specification["seed"],
        "shape": scene.grid.shape,
        "spacing": scene.grid.spacing,
        "start": scene.start,
        "goal": scene.goal,
        "opening_m": scene.specification.get("opening_m"),
        "reachability": reachability[job["geometry_mode"]],
        "reachability_all_scales": reachability,
        "generation_and_witness_s": generation_s,
        "post_run_audit_s": audit_s,
        "nominal_body_valid": body_valid,
        "nominal_margin_valid": margin_valid,
        "execution_eligible": selected["eligible"] if selected else None,
        "execution_success": selected["execution_success"] if selected else None,
        "physical_execution_success": selected["physical_execution_success"]
        if selected
        else None,
        "execution_reason": selected["failure_reason"]
        if selected
        else "not_run_no_path",
        "raw_execution_success": raw["execution_success"] if raw else None,
        "raw_execution_reason": raw["failure_reason"] if raw else "not_run_no_path",
        "tracking_wall_s": sum(item["tracking_wall_s"] for item in evaluated.values()),
        "initial_rss_bytes": initial["rss_bytes"],
        "planning_rss_bytes": planning_peak["rss_bytes"],
        "planning_peak_rss_bytes": planning_peak["process_peak_rss_bytes"],
        "post_tracking_peak_rss_bytes": memory_usage()["process_peak_rss_bytes"],
        "scheduling": scheduling,
        "system_cpu_busy_fraction": cpu_busy_fraction(before, after),
        "system_process_count_before": before["process_count"],
        "system_process_count_after": after["process_count"],
    }
    if selected:
        for key in (
            "simulation_time_s",
            "min_physical_clearance_lower_bound_m",
            "min_mission_clearance_lower_bound_m",
            "max_tracking_error_m",
            "rms_tracking_error_m",
            "peak_yaw_rate_deg_s",
            "peak_pitch_rate_deg_s",
            "peak_pitch_deg",
            "yaw_saturation_steps",
            "pitch_saturation_steps",
            "rate_limit_violations",
            "pitch_limit_violations",
            "speed_limit_violations",
            "required_clearance_satisfied",
        ):
            row[key] = selected.get(key)
    evidence = {
        "job": job,
        "row": row,
        "paths": paths,
        "history": history,
        "raw_history": raw_history,
        "checkpoints": checkpoints,
        "executions": evaluated,
        "environment": environment_info(),
    }
    with (directory / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)


class Runner:
    """Reuse only exact completed5A jobs; refuse ambiguous partial directories."""

    def __init__(self, local: Path, output: Path) -> None:
        self.local, self.output = local.resolve(), output.resolve()
        if self.local.is_relative_to(ROOT):
            raise ValueError("Full evidence must stay outside the public repository")
        self.local.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        self.config = {
            "protocol": read_config("stage5a_protocol.json"),
            "maps": read_config("stage5a_maps.json"),
        }
        configuration = self.local / "configuration.json"
        if configuration.exists():
            if json.loads(configuration.read_text(encoding="utf-8")) != self.config:
                raise ValueError(
                    "Frozen configuration changed; use a new experiment version"
                )
        else:
            with configuration.open("x", encoding="utf-8") as stream:
                json.dump(self.config, stream, ensure_ascii=False, indent=2)
        self.protocol = self.config["protocol"]

    def run(
        self,
        scene: str,
        method: str,
        seed: int,
        mode: str,
        *,
        phase: str,
        seconds: float,
        step: float,
    ) -> dict:
        """Own one child, recording actual errors instead of fabricated rows."""
        identity = f"{phase}_{scene}_{method}_{mode}_seed{seed}_step{step:g}"
        job = {
            "job_id": identity,
            "scene": scene,
            "method": method,
            "seed": seed,
            "geometry_mode": mode,
            "phase": phase,
            "seconds": seconds,
            "step_m": step,
            "version": self.protocol["version"],
        }
        directory = self.local / identity
        result = directory / "result.json"
        if directory.exists():
            if not result.exists():
                raise FileExistsError(f"Incomplete trial requires review: {directory}")
            previous = json.loads(result.read_text(encoding="utf-8"))
            if previous["job"] != job:
                raise ValueError(
                    "Existing trial differs from the requested specification"
                )
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
        allowance = seconds + 2 * self.protocol["kinematics"]["wall_guard_s"] + 45
        with (directory / "console.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    "-m",
                    "gsunlight_repro.stage5a.runner",
                    "--job",
                    str(job_file),
                ],
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                code = process.wait(timeout=allowance)
            except subprocess.TimeoutExpired:
                code = terminate_worker(process, log)
                (directory / "error.json").write_text(
                    json.dumps({"error": "external_guard", "exit_code": code}),
                    encoding="utf-8",
                )
                raise RuntimeError(
                    f"External guard stopped trial: {identity}"
                ) from None
        if code or not result.exists():
            raise RuntimeError(f"Worker failed: {identity}; inspect local console.log")
        row = json.loads(result.read_text(encoding="utf-8"))["row"]
        LOGGER.info(
            "%s geometry=%s execute=%s reason=%s planning=%.3fs tracking=%.3fs",
            identity,
            row["strict_geometry_valid"],
            row["execution_success"],
            row["execution_reason"],
            row["actual_total_s"],
            row["tracking_wall_s"],
        )
        return row

    def phase(self, phase: str) -> None:
        """Enforce pilot/development before a prospectively selected holdout."""
        split = "pilot" if phase == "pilot_single" else phase
        seeds = (
            [0]
            if phase == "pilot_single"
            else self.protocol["planning_seeds"]
            if phase == "holdout"
            else self.protocol["pilot_seeds"]
        )
        selection = None
        if (
            phase == "development"
            and not (self.local / "pilot_completed.json").exists()
        ):
            raise ValueError("Development requires completed functional validation")
        if phase == "holdout":
            selection = read_config("stage5a_selected.json")
            if (
                not selection["resource_gate_passed"]
                or not (self.local / "development_completed.json").exists()
            ):
                raise ValueError(
                    "Holdout requires the prospective selection/resource gate"
                )
        for seed in seeds:
            for spec in self.config["maps"]["maps"]:
                if spec["split"] != split:
                    continue
                for method in self.protocol["methods"]:
                    modes = (
                        ["body"]
                        if phase == "development"
                        else self.protocol["geometry_modes"]
                    )
                    steps = (
                        self.protocol["development_steps_m"]
                        if phase == "development" and method != "rrt_connect"
                        else [
                            selection["steps_m"][method]
                            if selection
                            else self.protocol["default_step_m"]
                        ]
                    )
                    for mode in modes:
                        for step in steps:
                            self.run(
                                spec["id"],
                                method,
                                seed,
                                mode,
                                phase=split,
                                seconds=self.protocol["total_budget_s"]
                                if phase == "holdout"
                                else self.protocol["development_budget_s"]
                                if phase == "development"
                                else self.protocol["pilot_budget_s"],
                                step=step,
                            )
        marker = self.local / (phase + "_completed.json")
        if not marker.exists():
            marker.write_text(
                json.dumps({"phase": phase, "completed": True}), encoding="utf-8"
            )


def main() -> int:
    """Run a worker or a serial staged controller with explicit error evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path)
    parser.add_argument("--local-dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/stage5a"))
    parser.add_argument(
        "--phase", choices=("pilot_single", "pilot", "development", "holdout")
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
    else:
        if not args.local_dir or not args.phase:
            parser.error("Controller requires --local-dir and --phase")
        Runner(args.local_dir, args.output).phase(args.phase)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
