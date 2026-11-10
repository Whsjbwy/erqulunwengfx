"""Serve stage-two trials with map initialization outside each planning budget."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .author_worker import execute_author, local_output, send_result
from .planning import PlanningLimits, PlanResult, SearchCounters

METHODS = (
    "author_original",
    "paper_reimplementation",
    "safety_reference",
    "astar",
    "rrt_connect",
)


def author_result(payload: dict[str, Any], seconds: float) -> dict[str, Any]:
    """Translate observed author outcomes without inventing unavailable events."""
    observed = payload.get("counters", {})
    counters = SearchCounters(
        generated_candidates=observed.get("emitted_candidates"),
        valid_candidates=None,
        collision_filtered=None,
        capacity_evicted=observed.get("grid_evictions"),
        expanded_nodes=observed.get("expanded_nodes"),
        sampled_nodes=payload.get("node_count"),
        collision_checks=None,
        no_candidate_expansions=observed.get("empty_candidate_batches"),
        final_open_nodes=observed.get("open_nodes"),
    )
    result = PlanResult(
        method="author_original",
        version="author-zip-2026-stage2-observation-v1",
        status=payload["status"],
        termination_reason=payload.get(
            "termination_reason", payload.get("failure_reason", "unknown")
        ),
        reported_success=payload.get("reported_success", False),
        raw_path=payload.get("raw_path"),
        search_seconds=payload.get("algorithm_seconds"),
        counters=counters,
        parameters=payload.get("parameters") or {},
        postprocessed_path=payload.get("postprocessed_path"),
        events={
            "author_timer_scope": (
                "cached-map and initialization through search, before native smoothing"
            ),
            "candidate_collision_filter": "absent in original; count not applicable",
        },
    )
    output = asdict(result)
    # None records missing execution evidence; an empty dict would imply a
    # captured but empty parameter set.
    output["parameters"] = payload.get("parameters")
    output["exit_code"] = payload.get("exit_code")
    output["error"] = payload.get("failure_reason") or payload.get("error", "")
    output["partial"] = payload.get("partial", False)
    output["native_payload"] = payload
    output["planner_call_seconds"] = seconds
    return output


def main(argv: list[str] | None = None) -> int:
    """Load one scenario and method, then serve bounded serial seed requests."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-config", type=Path, required=True)
    parser.add_argument("--experiment-config", type=Path, required=True)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--method", choices=METHODS, required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--local-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    args.local_dir = args.local_dir.resolve()
    args.local_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1) as protocol:
        try:
            with local_output(args.local_dir / "startup.log"):
                from .scenarios import load_scenario

                scenario = load_scenario(args.map_config, args.scene)
                configuration = json.loads(
                    args.experiment_config.read_text(encoding="utf-8")
                )
                limits = PlanningLimits(**configuration["limits"])
                parameters = configuration["method_parameters"].get(args.method, {})
                image = None
                planner = None
                if args.method == "author_original":
                    import numpy as np
                    import pyvista as pv

                    if args.source_dir is None:
                        raise ValueError("Author-Original requires --source-dir")
                    if (
                        scenario.grid.shape != (100, 80, 80)
                        or scenario.grid.origin != (0, 0, 0)
                        or scenario.grid.spacing != (1, 1, 1)
                        or scenario.start != (2, 2, 2)
                        or scenario.goal != (95, 75, 75)
                    ):
                        raise ValueError(
                            "Scenario does not match the original coordinate profile"
                        )
                    image = pv.ImageData(
                        dimensions=tuple(value + 1 for value in scenario.grid.shape),
                        origin=scenario.grid.origin,
                        spacing=scenario.grid.spacing,
                    )
                    image.cell_data["obstacle"] = scenario.grid.occupancy.flatten(
                        order="F"
                    ).astype(np.float64)
                elif args.method == "paper_reimplementation":
                    from .paper_planner import plan as planner
                elif args.method == "safety_reference":
                    from .safety_planner import plan as planner
                elif args.method == "astar":
                    from .astar import plan as planner
                else:
                    from .rrt_connect import plan as planner
            send_result(protocol, {"event": "ready", "map_load_count": 1})
        except Exception as error:
            with (args.local_dir / "startup.log").open(
                "a", encoding="utf-8"
            ) as startup_log:
                traceback.print_exc(file=startup_log)
            send_result(
                protocol,
                {"event": "startup_error", "error": f"{type(error).__name__}: {error}"},
            )
            return 1
        for line in sys.stdin:
            seed = int(json.loads(line)["seed"])
            started = time.perf_counter()
            with local_output(args.local_dir / f"seed_{seed}.log"):
                try:
                    import numpy as np

                    random.seed(seed)
                    np.random.seed(seed)
                    if args.method == "author_original":
                        source = args.source_dir.resolve()
                        # The scenario is generated in memory. cached_read routes
                        # the original relative map request to this image only;
                        # no synthetic file is mislabeled as the author's VTI.
                        payload = execute_author(
                            source, source / "map.vti", image, seed, "author_original"
                        )
                        result = author_result(payload, time.perf_counter() - started)
                    else:
                        assert planner is not None
                        result = asdict(
                            planner(
                                scenario.grid,
                                scenario.start,
                                scenario.goal,
                                seed,
                                limits,
                                parameters,
                            )
                        )
                        result["planner_call_seconds"] = time.perf_counter() - started
                        result["exit_code"] = 0
                except Exception as error:
                    traceback.print_exc()
                    result = {
                        "method": args.method,
                        "status": "error",
                        "termination_reason": "error",
                        "error": f"{type(error).__name__}: {error}",
                        "reported_success": None,
                        "parameters": None,
                        "version": None,
                        "search_seconds": None,
                        "exit_code": 1,
                        "raw_path": None,
                        "postprocessed_path": None,
                    }
            result.update(
                event="result", seed=seed, wall_seconds=time.perf_counter() - started
            )
            send_result(protocol, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
