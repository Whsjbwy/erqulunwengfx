"""Auditable geometric RRT-Connect, RRT* and Informed-RRT* references."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass

import numpy as np

from ..map_reader import Point
from ..planning import BudgetExceeded
from ..stage4a.budget import Budget
from .geometry import Geometry
from .maps import Scene, mode_radius
from .sampling import InformedSampler, neighbor_radius
from .solutions import Solutions
from .tree import Tree, steer


@dataclass(frozen=True, slots=True)
class Options:
    """Within-attempt limits and explicit fixed algorithm parameters."""

    step: float = 5
    goal_bias: float = 0.05
    max_nodes: int = 100000
    max_iterations: int = 1000000

    def __post_init__(self) -> None:
        if not math.isfinite(self.step) or self.step <= 0:
            raise ValueError("Step must be finite and positive")
        if not math.isfinite(self.goal_bias) or not 0 <= self.goal_bias <= 1:
            raise ValueError("Goal bias must be in [0,1]")
        if type(self.max_nodes) is not int or self.max_nodes < 2:
            raise ValueError("Node limit must be an integer >=2")
        if type(self.max_iterations) is not int or self.max_iterations < 1:
            raise ValueError("Iteration limit must be a positive integer")


def free_edge(
    geometry: Geometry, first: Point, second: Point, counters: Counter
) -> bool:
    """Record rejection reasons without silently treating errors as collisions."""
    verdict = geometry.segment(first, second)
    if not verdict.valid:
        counters["rejected_" + verdict.reason] += 1
    return verdict.valid


def connect_once(
    geometry: Geometry,
    start: Point,
    goal: Point,
    rng: np.random.Generator,
    budget: Budget,
    options: Options,
    counters: Counter,
) -> list[Point] | None:
    """Preserve the audited two-tree algorithm; expose the finite-body oracle."""
    first, second = Tree(start, options.max_nodes), Tree(goal, options.max_nodes)
    first_is_start = True
    counters["inserted_nodes"] += 2
    lower = np.asarray(geometry.grid.origin)
    upper = lower + np.asarray(geometry.grid.shape) * geometry.grid.spacing

    def extend(tree: Tree, target: Point) -> tuple[str, int]:
        budget.check()
        counters["expanded_nodes"] += 1
        index = tree.nearest(target)
        source = tree.point(index)
        distance = math.dist(source, target)
        if distance == 0:
            return "reached", index
        point = steer(source, target, options.step)
        counters["generated_candidates"] += 1
        if not free_edge(geometry, source, point, counters):
            return "trapped", index
        budget.check()
        if len(first) + len(second) >= options.max_nodes:
            raise BudgetExceeded("node_budget")
        index = tree.add(point, index)
        counters["inserted_nodes"] += 1
        return ("reached" if distance <= options.step else "advanced"), index

    for _ in range(options.max_iterations):
        budget.check()
        counters["outer_iterations"] += 1
        if rng.random() < options.goal_bias:
            target = second.point(0)
            counters["goal_biased_samples"] += 1
        else:
            target = tuple(float(value) for value in rng.uniform(lower, upper))
            counters["uniform_samples"] += 1
        status, index = extend(first, target)
        if status != "trapped":
            while True:
                connection, other = extend(second, first.point(index))
                if connection != "advanced":
                    break
            if connection == "reached":
                if not free_edge(
                    geometry, first.point(index), second.point(other), counters
                ):
                    raise RuntimeError("RRT tree join failed continuous validation")
                left, right = (
                    (first.path(index), second.path(other))
                    if first_is_start
                    else (second.path(other), first.path(index))
                )
                right.reverse()
                return left + (right[1:] if left[-1] == right[0] else right)
        first, second = second, first
        first_is_start = not first_is_start
        counters["tree_swaps"] += 1
    raise BudgetExceeded("iteration_budget")


def star_search(
    geometry: Geometry,
    start: Point,
    goal: Point,
    rng: np.random.Generator,
    budget: Budget,
    options: Options,
    counters: Counter,
    solutions: Solutions,
    *,
    informed: bool,
) -> None:
    """Choose a parent, rewire and propagate descendants before querying costs."""
    tree = Tree(start, options.max_nodes)
    counters["inserted_nodes"] += 1
    sampler = InformedSampler(start, goal)
    goals: dict[int, float] = {}
    best_raw = math.inf
    lower = np.asarray(geometry.grid.origin)
    upper = lower + np.asarray(geometry.grid.shape) * geometry.grid.spacing
    volume = float(np.prod(upper - lower))

    def sample_free() -> Point:
        while True:
            budget.check()
            if rng.random() < options.goal_bias:
                sample = goal
                counters["goal_biased_samples"] += 1
            elif informed and math.isfinite(best_raw):
                sample = sampler.sample(rng, best_raw)
                counters["informed_samples"] += 1
            else:
                sample = tuple(float(v) for v in rng.uniform(lower, upper))
                counters["uniform_samples"] += 1
            if free_edge(geometry, sample, sample, counters):
                return sample
            counters["sample_rejections"] += 1

    for _ in range(options.max_iterations):
        budget.check()
        counters["outer_iterations"] += 1
        target = sample_free()
        nearest = tree.nearest(target)
        point = steer(tree.point(nearest), target, options.step)
        if math.dist(point, tree.point(nearest)) <= 1e-12:
            counters["duplicate_samples"] += 1
            continue
        counters["expanded_nodes"] += 1
        counters["generated_candidates"] += 1
        if not free_edge(geometry, tree.point(nearest), point, counters):
            continue
        budget.check()
        if len(tree) >= options.max_nodes:
            raise BudgetExceeded("node_budget")
        distances = tree.distances(point)
        radius = neighbor_radius(len(tree), options.step, volume)
        near = np.flatnonzero(distances <= radius)
        parent = nearest
        cost = tree.costs[nearest] + distances[nearest]
        for candidate in near:
            budget.check()
            proposed = tree.costs[candidate] + distances[candidate]
            if proposed < cost - 1e-12:
                counters["parent_checks"] += 1
                if free_edge(geometry, tree.point(int(candidate)), point, counters):
                    parent, cost = int(candidate), proposed
        index = tree.add(point, parent)
        counters["inserted_nodes"] += 1
        for candidate in near:
            budget.check()
            candidate = int(candidate)
            if cost + distances[candidate] < tree.costs[candidate] - 1e-12:
                counters["rewire_checks"] += 1
                if free_edge(geometry, point, tree.point(candidate), counters):
                    counters["descendant_cost_updates"] += tree.reparent(
                        candidate, index
                    )
                    counters["rewires"] += 1
        to_goal = math.dist(point, goal)
        if to_goal <= options.step and free_edge(geometry, point, goal, counters):
            goals[index] = to_goal
        if goals:
            best = min(goals, key=lambda item: tree.costs[item] + goals[item])
            cost_to_goal = tree.costs[best] + goals[best]
            if cost_to_goal < best_raw - 1e-12:
                path = tree.path(best)
                if path[-1] != goal:
                    path.append(goal)
                best_raw = cost_to_goal
                solutions.accept(path)
    raise BudgetExceeded("iteration_budget")


def plan(
    scene: Scene,
    method: str,
    seed: int,
    mode: str,
    protocol: dict,
    *,
    seconds: float | None = None,
    step: float | None = None,
    options: Options | None = None,
) -> dict:
    """Run one timed policy; report success separately from normal termination."""
    if method not in protocol["methods"]:
        raise ValueError("Unknown stage5A method")
    if type(seed) is not int or seed < 0:
        raise ValueError("Planning seed must be a nonnegative integer")
    options = options or Options(
        protocol["default_step_m"] if step is None else step,
        protocol["goal_bias"],
        protocol["max_nodes"],
        protocol["max_iterations"],
    )
    budget = Budget(protocol["total_budget_s"] if seconds is None else seconds)
    geometry = scene.geometry(mode_radius(mode, protocol))
    solutions = Solutions(geometry, scene.start, scene.goal, budget)
    counters: Counter = Counter()
    terminations: Counter = Counter()
    attempts = 0
    reason = "time_budget"
    try:
        for name, point in (("start", scene.start), ("goal", scene.goal)):
            if not geometry.segment(point, point).valid:
                reason = "invalid_" + name
                break
        else:
            budget.check()
            if geometry.segment(scene.start, scene.goal).valid:
                solutions.accept([scene.start, scene.goal])
                reason = "euclidean_lower_bound"
            elif method == "rrt_connect":
                while True:
                    budget.check()
                    current_seed = (
                        seed
                        if attempts == 0
                        else int(
                            np.random.SeedSequence([seed, attempts]).generate_state(1)[
                                0
                            ]
                        )
                    )
                    attempts += 1
                    try:
                        path = connect_once(
                            geometry,
                            scene.start,
                            scene.goal,
                            np.random.default_rng(current_seed),
                            budget,
                            options,
                            counters,
                        )
                        if path is not None:
                            solutions.accept(path)
                        terminations["trees_connected"] += 1
                    except BudgetExceeded as error:
                        terminations[str(error)] += 1
                        if str(error) == "time_budget":
                            raise
            else:
                attempts = 1
                star_search(
                    geometry,
                    scene.start,
                    scene.goal,
                    np.random.default_rng(seed),
                    budget,
                    options,
                    counters,
                    solutions,
                    informed=method == "informed_rrt_star",
                )
    except BudgetExceeded as error:
        reason = str(error)
    total = budget.elapsed
    first = solutions.raw_history[0] if solutions.raw_history else None
    best = solutions.history[-1] if solutions.history else None
    checkpoints = [t for t in protocol["checkpoints_s"] if t <= budget.seconds]
    return {
        "method": method,
        "version": protocol["version"],
        "seed": seed,
        "geometry_mode": mode,
        "radius_m": geometry.radius,
        "options": asdict(options),
        "time_budget_s": budget.seconds,
        "actual_total_s": total,
        "deadline_overshoot_s": max(0.0, total - budget.seconds),
        "reported_success": solutions.reported_candidates > 0,
        "strict_geometry_valid": bool(best),
        "termination_reason": reason,
        "attempt_terminations": dict(terminations),
        "attempts": attempts,
        "first_valid_time_s": first["time_s"] if first else None,
        "first_valid_length": first["length"] if first else None,
        "best_length": best["length"] if best else None,
        "raw_best_length": solutions.raw_history[-1]["length"] if first else None,
        "raw_path_id": solutions.raw_history[-1]["path_id"] if first else None,
        "selected_path_id": best["path_id"] if best else None,
        "validation_s": solutions.validation_s,
        "shortcut_s": solutions.shortcut_s,
        "search_and_bookkeeping_s": max(
            0.0, total - solutions.validation_s - solutions.shortcut_s
        ),
        "reported_candidates": solutions.reported_candidates,
        "post_interrupted": solutions.post_interrupted,
        "query_calls": geometry.query_calls,
        "requested_segments": geometry.segment_requests,
        "box_distance_tests": geometry.box_distance_tests,
        "counters": dict(counters),
        "paths": solutions.paths,
        "history": solutions.history,
        "raw_history": solutions.raw_history,
        "checkpoints": solutions.checkpoints(checkpoints),
    }
