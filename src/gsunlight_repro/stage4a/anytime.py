"""Budgeted evaluation policies around unchanged single-attempt backends."""

from __future__ import annotations

import math
import time
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
from typing import Any
from unittest.mock import patch

import numpy as np

from .. import paper_planner, rrt_connect, safety_planner
from ..collision_checker import validate_path
from ..grid_candidates import CandidateNode, GridCandidates
from ..planning import BudgetExceeded, PlanningLimits, SearchCounters
from ..scenarios import Scenario
from .budget import Budget
from .incumbent import Incumbent
from .measurement import Measurement


def attempt_seed(root_seed: int, index: int) -> int:
    """Preserve the first native stream and derive every later stream a priori."""
    if index == 0:
        return root_seed
    return int(np.random.SeedSequence([root_seed, index]).generate_state(1)[0])


def plan(
    scenario: Scenario,
    method: str,
    seed: int,
    protocol: dict[str, Any],
    *,
    seconds: float | None = None,
) -> dict[str, Any]:
    """Run a static configuration with one shared end-to-end clock.

    G-Sunlight keeps its unchanged within-attempt search and may restart after
    natural termination. RRT-first has one attempt; RRT-restart uses all time.
    This policy is distinct from every frozen paper and stage-three result.
    """
    budget = Budget(seconds if seconds is not None else protocol["total_budget_s"])
    geometry = Measurement(scenario.grid)
    incumbent = Incumbent(
        scenario.grid, scenario.start, scenario.goal, budget, geometry.check_path
    )
    counters = SearchCounters()
    terminations: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    all_cells: set[tuple[int, ...]] = set()
    graph_nodes = 0
    attempts = 0
    opened: GridCandidates | None = None
    backend_successes = 0
    last_backend_status = None
    angle = method in protocol["angles"]
    parameters = (
        {
            **protocol["shared_parameters"],
            **{
                k: v
                for k, v in protocol["angles"][method].items()
                if k != "theory_rays"
            },
        }
        if angle
        else {"step_size": 5.0, "goal_bias": 0.05}
    )
    if not angle and method not in ("rrt_first", "rrt_restart"):
        raise ValueError(f"Unregistered method: {method}")
    original_reconstruct = paper_planner._reconstruct
    original_grid = paper_planner.GridCandidates

    def capture(nodes: list[CandidateNode], node: CandidateNode, goal: tuple) -> list:
        path = original_reconstruct(nodes, node, goal)
        incumbent.accept(path)
        return path

    def grid_factory(*args: Any) -> GridCandidates:
        nonlocal opened
        opened = original_grid(*args)
        return opened

    stop_reason = "time_budget"
    with ExitStack() as stack:
        stack.enter_context(geometry.installed())
        if angle:
            stack.enter_context(patch.object(paper_planner, "_reconstruct", capture))
            stack.enter_context(
                patch.object(paper_planner, "GridCandidates", grid_factory)
            )
        while budget.remaining > 0:
            current_seed = attempt_seed(seed, attempts)
            incumbent.attempt_index = attempts
            incumbent.source_seed = current_seed
            attempts += 1
            limits = PlanningLimits(
                max(1e-9, budget.remaining),
                protocol["max_nodes_per_attempt"],
                protocol["max_iterations_per_attempt"],
            )
            planner = safety_planner.plan if angle else rrt_connect.plan
            result = planner(
                scenario.grid,
                scenario.start,
                scenario.goal,
                current_seed,
                limits,
                parameters,
            )
            last_backend_status = result.status
            statuses[result.status] += 1
            terminations[result.termination_reason] += 1
            backend_successes += int(result.reported_success)
            for name, value in asdict(result.counters).items():
                if name == "final_open_nodes":
                    setattr(counters, name, value)
                elif value is not None:
                    setattr(counters, name, int(getattr(counters, name) or 0) + value)
            if angle and opened is not None:
                all_cells.update(opened._history)
                graph_nodes += int(result.events.get("graph_nodes", 0))
            if result.status in ("error", "invalid_input"):
                raise RuntimeError(
                    f"Backend {method}: {result.status}/{result.termination_reason}"
                )
            if not angle and result.raw_path is not None:
                try:
                    incumbent.accept(result.raw_path)
                except BudgetExceeded:
                    break
            if method == "rrt_first":
                stop_reason = "first_attempt_finished"
                break
    total_s = budget.elapsed
    first = incumbent.raw_history[0] if incumbent.raw_history else None
    best = incumbent.history[-1] if incumbent.history else None
    # This final audit is outside planning and cannot introduce a new solution.
    audit_started = time.perf_counter()
    if (
        incumbent.best_path is not None
        and not validate_path(incumbent.best_path, scenario.grid).valid
    ):
        raise RuntimeError("Final audit rejected an accepted incumbent")
    audit_seconds = time.perf_counter() - audit_started
    result = {
        "method": method,
        "version": "stage4a-budgeted-static-v1",
        "seed": seed,
        "parameters": parameters,
        "total_budget_s": budget.seconds,
        "actual_total_s": total_s,
        "post_run_audit_s": audit_seconds,
        "deadline_overshoot_s": max(0.0, total_s - budget.seconds),
        "termination_reason": stop_reason,
        "policy_completed_without_error": True,
        "backend_normal_attempts": statuses["ok"],
        "last_backend_status": last_backend_status,
        "first_attempt_normally_completed_by_budget": method == "rrt_first"
        and last_backend_status == "ok"
        and total_s <= budget.seconds,
        "attempts": attempts,
        "attempt_terminations": dict(terminations),
        "attempt_statuses": dict(statuses),
        "backend_reported_successes": backend_successes,
        "strict_valid": bool(incumbent.best_path),
        "first_valid_time_s": first["time_s"] if first else None,
        "first_valid_length": first["length"] if first else None,
        "best_length": best["length"] if best else None,
        "search_and_bookkeeping_s": max(
            0.0, total_s - incumbent.validation_s - incumbent.shortcut_s
        ),
        "external_validation_s": incumbent.validation_s,
        "shortcut_s": incumbent.shortcut_s,
        "candidates_verified": incumbent.candidates_verified,
        "invalid_candidates": incumbent.invalid_candidates,
        "post_interrupted": incumbent.post_interrupted,
        "seen_capacity_cells": len(all_cells),
        "spatial_coverage_bins20": len(
            {tuple(math.floor(c * 5 / 20) for c in cell) for cell in all_cells}
        ),
        "permanent_graph_nodes_across_attempts": graph_nodes if angle else None,
        **asdict(counters),
        **geometry.metrics(),
        "history": incumbent.history,
        "raw_history": incumbent.raw_history,
        "checkpoints": incumbent.checkpoints(protocol["checkpoints_s"]),
        "paths": incumbent.paths,
        "best_path": incumbent.best_path,
    }
    return result
