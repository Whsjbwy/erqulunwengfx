"""Run predeclared stage-two trials, retaining failures and independent verdicts."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .collision_checker import validate_path
from .experiment_runner import WorkerClient
from .metrics import endpoints_match, environment_info, path_length
from .planning import PlanningLimits
from .postprocessing import shortcut_path
from .stage2_worker import METHODS

LOGGER = logging.getLogger(__name__)
COUNTERS = (
    "generated_candidates",
    "valid_candidates",
    "collision_filtered",
    "capacity_evicted",
    "expanded_nodes",
    "sampled_nodes",
    "collision_checks",
    "no_candidate_expansions",
    "final_open_nodes",
)
FIELDS = (
    "schema_version",
    "run_id",
    "scene_id",
    "map_seed",
    "method",
    "version",
    "seed",
    "start",
    "goal",
    "parameters",
    "status",
    "termination_reason",
    "reported_success",
    "strict_valid",
    "endpoints_match",
    "raw_path_length",
    "collision_segment_count",
    "first_collision_segment",
    "first_collision_voxel",
    "first_collision_point",
    "common_post_valid",
    "common_post_length",
    "native_post_valid",
    "native_post_length",
    "search_seconds",
    "planner_call_seconds",
    "request_wall_seconds",
    "startup_seconds",
    "validation_seconds",
    "common_post_seconds",
    "time_budget_seconds",
    "within_search_budget",
    "budget_valid_success",
    "hard_timeout_seconds",
    "exit_code",
    *COUNTERS,
    "failure_categories",
    "error",
)


def assess_path(points: Any, grid: Any, start: Any, goal: Any) -> dict[str, Any]:
    """Independently assess retained coordinates; absent evidence is null."""
    if points is None:
        return {
            "valid": None,
            "endpoints_match": None,
            "length": None,
            "collision_segment_count": None,
            "first_collision_segment": None,
            "first_collision_voxel": None,
            "first_collision_point": None,
        }
    verdict = asdict(validate_path(points, grid))
    malformed = verdict["reason"] == "invalid_path"
    matched = False if malformed else endpoints_match(points, start, goal)
    return {
        "valid": bool(verdict["valid"] and matched),
        "endpoints_match": matched,
        "length": None if malformed else path_length(points),
        **{
            name: verdict[name]
            for name in (
                "collision_segment_count",
                "first_collision_segment",
                "first_collision_voxel",
                "first_collision_point",
            )
        },
    }


def make_row(
    result: dict[str, Any],
    scenario: Any,
    run_id: str,
    limits: PlanningLimits,
    hard_timeout: float,
    startup_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Preserve reporting and geometric validity as separate measurements."""
    result = dict(result)
    if (
        result["status"] in ("timeout", "crash", "error")
        and result.get("parameters") is None
    ):
        result.update(
            reported_success=None,
            search_seconds=None,
            version=None,
            observation_state="planning_result_not_captured",
        )
    started = time.perf_counter()
    raw = assess_path(
        result.get("raw_path"), scenario.grid, scenario.start, scenario.goal
    )
    native = assess_path(
        result.get("postprocessed_path"), scenario.grid, scenario.start, scenario.goal
    )
    validation_seconds = time.perf_counter() - started
    processed = None
    post_valid = None
    post_length = None
    post_error = ""
    started = time.perf_counter()
    if raw["valid"]:
        try:
            processed = shortcut_path(result["raw_path"], scenario.grid)
            post = assess_path(processed, scenario.grid, scenario.start, scenario.goal)
            post_valid, post_length = post["valid"], post["length"]
        except (ValueError, RuntimeError) as error:
            LOGGER.exception("Common postprocessing failed")
            post_valid = False
            post_error = f"{type(error).__name__}: {error}"
    post_seconds = time.perf_counter() - started
    counters = result.get("counters") or {}
    search_seconds = result.get("search_seconds")
    within = search_seconds <= limits.time_limit if search_seconds is not None else None
    categories = []
    for counter, label in (
        ("no_candidate_expansions", "some_expansions_without_candidates"),
        ("collision_filtered", "candidate_collision_filter"),
        ("capacity_evicted", "grid_capacity_eviction"),
    ):
        if counters.get(counter):
            categories.append(label)
    reason = result.get("termination_reason", result.get("failure_reason", "unknown"))
    if (
        result["status"] in ("timeout", "budget_exhausted")
        or within is False
        or reason == "paper_iteration_limit"
    ):
        categories.append("search_budget_exhausted")
    if reason in ("open_exhausted", "open_set_exhausted", "nodes_exhausted"):
        categories.append("search_nodes_exhausted")
    if raw["valid"] is False:
        categories.append("raw_path_invalid")
    if native["valid"] is False:
        categories.append("native_postprocessing_invalid")
    if post_error or post_valid is False:
        categories.append("common_postprocessing_invalid")
    if result["status"] in ("error", "crash"):
        categories.append("exception")
    row = {
        "schema_version": 2,
        "run_id": run_id,
        "scene_id": scenario.scene_id,
        "map_seed": scenario.map_seed,
        "method": result["method"],
        "version": result.get("version"),
        "seed": result["seed"],
        "start": scenario.start,
        "goal": scenario.goal,
        "parameters": result.get("parameters"),
        "status": result["status"],
        "termination_reason": reason,
        "reported_success": result.get("reported_success"),
        "strict_valid": raw["valid"],
        "endpoints_match": raw["endpoints_match"],
        "raw_path_length": raw["length"],
        **{
            name: raw[name]
            for name in (
                "collision_segment_count",
                "first_collision_segment",
                "first_collision_voxel",
                "first_collision_point",
            )
        },
        "common_post_valid": post_valid,
        "common_post_length": post_length,
        "native_post_valid": native["valid"],
        "native_post_length": native["length"],
        "search_seconds": search_seconds,
        "planner_call_seconds": result.get("planner_call_seconds"),
        "request_wall_seconds": result.get("wall_seconds"),
        "startup_seconds": startup_seconds,
        "validation_seconds": validation_seconds,
        "common_post_seconds": post_seconds,
        "time_budget_seconds": limits.time_limit,
        "within_search_budget": within,
        "budget_valid_success": bool(
            result["status"] == "ok"
            and raw["valid"]
            and within
            and result.get("reported_success")
        ),
        "hard_timeout_seconds": hard_timeout,
        "exit_code": result.get("exit_code"),
        **{name: counters.get(name) for name in COUNTERS},
        "failure_categories": categories,
        "error": ";".join(
            message
            for message in (
                result.get("error") or result.get("failure_reason", ""),
                post_error,
            )
            if message
        ),
    }
    evidence = {
        "run_id": run_id,
        "scene_id": scenario.scene_id,
        "map_seed": scenario.map_seed,
        "start": scenario.start,
        "goal": scenario.goal,
        **result,
        "failure_category_note": (
            "Candidate filtering, empty expansions and capacity eviction are observed "
            "events, not established causal explanations for a failed trial."
        ),
        "common_postprocessed_path": processed,
        "raw_validation": raw,
        "native_post_validation": native,
        "row": row,
    }
    return row, evidence


def main(argv: list[str] | None = None) -> int:
    """Run a new immutable trial directory; never mix repeated CSV/JSONL runs."""
    from .scenarios import load_scenarios

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map-config", type=Path, default=Path("configs/stage2_maps.json")
    )
    parser.add_argument(
        "--experiment-config", type=Path, default=Path("configs/stage2_experiment.json")
    )
    parser.add_argument("--scenes", nargs="+")
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    parser.add_argument("--seeds", nargs="+", type=int, default=list(range(5)))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S"
    )
    args.local_dir = args.local_dir.resolve()
    repository = Path(__file__).resolve().parents[2]
    if args.local_dir.is_relative_to(repository):
        parser.error("Local path evidence must remain outside the public repository")
    if args.local_dir.exists() or args.output.exists():
        parser.error(
            "Choose a new directory and output; existing records cannot be overwritten"
        )
    if (
        not args.seeds
        or len(set(args.seeds)) != len(args.seeds)
        or any(s < 0 or s >= 2**32 for s in args.seeds)
    ):
        parser.error("Seeds must be unique integers in [0, 2**32)")
    if len(set(args.methods)) != len(args.methods):
        parser.error("Methods must not be repeated")
    configuration = json.loads(args.experiment_config.read_text(encoding="utf-8"))
    limits = PlanningLimits(**configuration["limits"])
    hard_timeout = float(configuration["hard_timeout_seconds"])
    startup_timeout = float(configuration["startup_timeout_seconds"])
    if (
        not all(
            math.isfinite(value) and value > 0
            for value in (hard_timeout, startup_timeout)
        )
        or hard_timeout < limits.time_limit
    ):
        parser.error(
            "Timeouts must be finite; hard timeout must allow the planning budget"
        )
    scenarios = load_scenarios(args.map_config)
    available = {scenario.scene_id for scenario in scenarios}
    if args.scenes and (
        len(args.scenes) != len(set(args.scenes)) or not set(args.scenes) <= available
    ):
        parser.error("Scene IDs must be unique IDs from the configuration")
    scenarios = [
        s for s in scenarios if args.scenes is None or s.scene_id in args.scenes
    ]
    if "author_original" in args.methods and (
        args.source_dir is None
        or not all(
            (args.source_dir / name).is_file()
            for name in ("main_sunlight_3Dgrid.py", "utils.py")
        )
    ):
        parser.error("Author-Original requires an existing local --source-dir")
    args.local_dir.mkdir(parents=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema_version": 2,
        "run_id": args.run_id,
        "started_utc": datetime.now(UTC).isoformat(),
        "environment": environment_info(),
        "configuration": configuration,
        "map_configuration": json.loads(args.map_config.read_text(encoding="utf-8")),
        "methods": args.methods,
        "seeds": args.seeds,
        "command": [
            sys.executable,
            "-m",
            "gsunlight_repro.benchmark",
            *(argv if argv is not None else sys.argv[1:]),
        ],
    }
    (args.local_dir / "environment.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (
        args.output.open("w", encoding="utf-8", newline="") as stream,
        (args.local_dir / "paths.jsonl").open("x", encoding="utf-8") as evidence_stream,
    ):
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for scenario in scenarios:
            for method in args.methods:
                trial_dir = args.local_dir / scenario.scene_id / method
                trial_dir.mkdir(parents=True)
                command = [
                    sys.executable,
                    "-m",
                    "gsunlight_repro.stage2_worker",
                    "--map-config",
                    str(args.map_config.resolve()),
                    "--experiment-config",
                    str(args.experiment_config.resolve()),
                    "--scene",
                    scenario.scene_id,
                    "--method",
                    method,
                    "--local-dir",
                    str(trial_dir),
                ]
                if args.source_dir is not None:
                    command.extend(("--source-dir", str(args.source_dir.resolve())))
                worker = WorkerClient(command, trial_dir / "worker_stderr.log")
                try:
                    for seed in args.seeds:
                        startup_seconds = 0.0
                        if worker.process is None:
                            started = time.perf_counter()
                            try:
                                worker.start(startup_timeout)
                            except (OSError, RuntimeError, TimeoutError) as error:
                                startup_seconds = time.perf_counter() - started
                                process = worker.process
                                worker.close()
                                result = {
                                    "seed": seed,
                                    "method": method,
                                    "status": "error",
                                    "termination_reason": (
                                        "startup_timeout"
                                        if isinstance(error, TimeoutError)
                                        else "worker_startup_error"
                                    ),
                                    "reported_success": None,
                                    "parameters": None,
                                    "version": None,
                                    "search_seconds": None,
                                    "exit_code": (
                                        process.returncode
                                        if process is not None
                                        else None
                                    ),
                                    "error": str(error),
                                }
                            else:
                                startup_seconds = time.perf_counter() - started
                                result = worker.run_seed(seed, hard_timeout)
                        else:
                            result = worker.run_seed(seed, hard_timeout)
                        result.setdefault("method", method)
                        row, evidence = make_row(
                            result,
                            scenario,
                            args.run_id,
                            limits,
                            hard_timeout,
                            startup_seconds,
                        )
                        writer.writerow(
                            {
                                key: json.dumps(
                                    value, ensure_ascii=False, sort_keys=True
                                )
                                if isinstance(value, (dict, list, tuple))
                                else value
                                for key, value in row.items()
                            }
                        )
                        stream.flush()
                        evidence_stream.write(
                            json.dumps(evidence, ensure_ascii=False) + "\n"
                        )
                        evidence_stream.flush()
                        LOGGER.info(
                            "scene=%s method=%s seed=%s status=%s "
                            "strict=%s reason=%s search_s=%s",
                            scenario.scene_id,
                            method,
                            seed,
                            row["status"],
                            row["strict_valid"],
                            row["termination_reason"],
                            row["search_seconds"],
                        )
                finally:
                    worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
