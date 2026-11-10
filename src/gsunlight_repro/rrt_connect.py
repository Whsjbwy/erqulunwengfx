"""Independent bidirectional RRT-Connect with continuously checked edges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .collision_checker import validate_path
from .map_reader import OccupancyMap, Point
from .planning import (
    BudgetExceeded,
    Deadline,
    PlanningLimits,
    PlanResult,
    SearchCounters,
)


@dataclass(slots=True)
class _Tree:
    root: str
    points: list[Point]
    parents: list[int]


def _root_path(tree: _Tree, index: int) -> list[Point]:
    reverse = []
    while index >= 0:
        reverse.append(tree.points[index])
        index = tree.parents[index]
    return list(reversed(reverse))


def _joined_path(
    first: _Tree, first_index: int, second: _Tree, second_index: int
) -> list[Point]:
    if first.root == "start":
        left = _root_path(first, first_index)
        right = list(reversed(_root_path(second, second_index)))
    else:
        left = _root_path(second, second_index)
        right = list(reversed(_root_path(first, first_index)))
    return left + (right[1:] if left[-1] == right[0] else right)


def plan(
    grid: OccupancyMap,
    start: Point,
    goal: Point,
    seed: int,
    limits: PlanningLimits,
    parameters: dict[str, Any] | None = None,
) -> PlanResult:
    """Run seeded RRT-Connect with bounded extend/connect loops.

    Uniform samples and ``step_size`` use physical map coordinates. Every new
    edge, final tree connection and reconstructed path is checked continuously;
    exact supplied endpoints are retained. Nearest neighbors use a transparent
    linear NumPy search. Return partial counters on time/node/iteration limits.
    """
    deadline = Deadline(limits.time_limit)
    counters = SearchCounters(final_open_nodes=None)
    supplied = {} if parameters is None else dict(parameters)
    effective: dict[str, Any] = {
        "seed": seed,
        "time_limit": limits.time_limit,
        "max_nodes": limits.max_nodes,
        "max_iterations": limits.max_iterations,
        "step_size": supplied.get("step_size", 5.0),
        "goal_bias": supplied.get("goal_bias", 0.05),
        "nearest_neighbor": "linear_numpy",
        "direct_connection_check": True,
        "rng": "numpy_default_rng",
    }
    events: dict[str, int | str | bool | None] = {
        "outer_iterations": 0,
        "random_samples": 0,
        "tree_swaps": 0,
        "expanded_nodes_semantics": "extension_attempts",
    }

    def finish(status: str, reason: str, path: list[Point] | None = None) -> PlanResult:
        return PlanResult(
            "rrt_connect",
            "stage2-rrt-connect-v1",
            status,
            reason,
            path is not None,
            path,
            deadline.elapsed,
            counters,
            effective,
            events=events,
        )

    try:
        if set(supplied) - {"step_size", "goal_bias"}:
            raise ValueError(f"Unknown RRT-Connect parameters: {sorted(supplied)}")
        step_size = float(effective["step_size"])
        goal_bias = float(effective["goal_bias"])
        if not np.isfinite(step_size) or step_size <= 0:
            raise ValueError("step_size must be finite and positive")
        if not np.isfinite(goal_bias) or not 0 <= goal_bias <= 1:
            raise ValueError("goal_bias must be between zero and one")
        effective.update(step_size=step_size, goal_bias=goal_bias)
        endpoints = np.asarray([start, goal], dtype=float)
        if endpoints.shape != (2, 3) or not np.all(np.isfinite(endpoints)):
            raise ValueError("Endpoints must contain three finite coordinates")
        start = tuple(float(value) for value in endpoints[0])
        goal = tuple(float(value) for value in endpoints[1])
        for name, point in (("start", start), ("goal", goal)):
            counters.collision_checks += 1
            if not validate_path([point, point], grid).valid:
                return finish("invalid_input", f"invalid_{name}")
        rng = np.random.default_rng(seed)
        deadline.check()
        counters.collision_checks += 1
        direct = validate_path([start, goal], grid).valid
        deadline.check()
        if direct:
            return finish("ok", "direct_connection", [start, goal])
        first = _Tree("start", [start], [-1])
        second = _Tree("goal", [goal], [-1])
        counters.sampled_nodes = 2
        lower = np.asarray(grid.origin)
        upper = lower + np.asarray(grid.spacing) * np.asarray(grid.shape)

        def extend(tree: _Tree, target: Point) -> tuple[str, int]:
            deadline.check()
            counters.expanded_nodes += 1
            array = np.asarray(tree.points)
            difference = np.asarray(target) - array
            index = int(np.argmin(np.einsum("ij,ij->i", difference, difference)))
            delta = difference[index]
            distance = float(np.linalg.norm(delta))
            if distance == 0:
                return "reached", index
            point = (
                target
                if distance <= step_size
                else tuple(
                    float(value)
                    for value in array[index] + delta * (step_size / distance)
                )
            )
            if point == tree.points[index]:
                counters.no_candidate_expansions += 1
                return "trapped", index
            counters.generated_candidates += 1
            counters.collision_checks += 1
            valid = validate_path([tree.points[index], point], grid).valid
            deadline.check()
            if not valid:
                counters.collision_filtered += 1
                counters.no_candidate_expansions += 1
                return "trapped", index
            counters.valid_candidates += 1
            if counters.sampled_nodes >= limits.max_nodes:
                raise BudgetExceeded("node_budget")
            tree.points.append(point)
            tree.parents.append(index)
            counters.sampled_nodes += 1
            return ("reached" if distance <= step_size else "advanced"), len(
                tree.points
            ) - 1

        for iteration in range(limits.max_iterations):
            deadline.check()
            events["outer_iterations"] = iteration + 1
            if rng.random() < goal_bias:
                target = second.points[0]
            else:
                target = tuple(float(value) for value in rng.uniform(lower, upper))
                events["random_samples"] += 1
            status, first_index = extend(first, target)
            if status != "trapped":
                while True:
                    deadline.check()
                    connection, second_index = extend(second, first.points[first_index])
                    if connection != "advanced":
                        break
                if connection == "reached":
                    counters.collision_checks += 1
                    if not validate_path(
                        [first.points[first_index], second.points[second_index]], grid
                    ).valid:
                        return finish("error", "invalid_final_connection")
                    path = _joined_path(first, first_index, second, second_index)
                    counters.collision_checks += len(path) - 1
                    if not validate_path(path, grid).valid:
                        return finish("error", "invalid_reconstructed_path")
                    deadline.check()
                    return finish("ok", "trees_connected", path)
            first, second = second, first
            events["tree_swaps"] += 1
        return finish("budget_exhausted", "iteration_budget")
    except BudgetExceeded as error:
        reason = str(error)
        return finish(
            "timeout" if reason == "time_budget" else "budget_exhausted", reason
        )
    except (TypeError, ValueError) as error:
        return finish("invalid_input", str(error))
