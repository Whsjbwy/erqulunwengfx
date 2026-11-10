"""Paper-structured independent G-Sunlight with explicit reconstruction choices."""

from __future__ import annotations

import logging
import math
import random
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from .collision_checker import validate_path
from .grid_candidates import CandidateNode, GridCandidates
from .map_reader import OccupancyMap, Point
from .planning import (
    BudgetExceeded,
    Deadline,
    PlanningLimits,
    PlanResult,
    SearchCounters,
)
from .sampling import SamplingParameters, tangent_candidates

LOGGER = logging.getLogger(__name__)
METHOD = "paper_reimplementation"
VERSION = "stage2-paper-v1"


@dataclass(frozen=True, slots=True)
class PaperParameters(SamplingParameters):
    """Paper settings plus explicit choices for the undefined ChooseSun function."""

    grid_side_length: float = 5.0
    grid_capacity: int = 1
    n_max: int = 100
    epsilon: float = 0.8
    alpha: float = 0.5

    def __post_init__(self) -> None:
        SamplingParameters.__post_init__(self)
        if not math.isfinite(self.grid_side_length) or self.grid_side_length <= 0:
            raise ValueError("Grid side length must be finite and positive")
        if type(self.grid_capacity) is not int or self.grid_capacity < 1:
            raise ValueError("Grid capacity must be a positive integer")
        if type(self.n_max) is not int or self.n_max < 0:
            raise ValueError("Paper n_max must be a nonnegative integer")
        if not math.isfinite(self.epsilon) or not 0 <= self.epsilon <= 1:
            raise ValueError("Epsilon must be between zero and one")
        if not math.isfinite(self.alpha) or self.alpha < 0:
            raise ValueError("Alpha must be finite and nonnegative")


def _point(value: Point) -> Point:
    coordinates = np.asarray(value, dtype=float)
    if coordinates.shape != (3,) or not np.all(np.isfinite(coordinates)):
        raise ValueError("Endpoints and candidates must be finite triples")
    return tuple(float(item) for item in coordinates)


def _choose_sun(
    opened: GridCandidates,
    goal: Point,
    parameters: PaperParameters,
    python_rng: random.Random,
    numpy_rng: np.random.Generator,
) -> CandidateNode:
    ordered = opened.ordered()
    if python_rng.random() < parameters.epsilon:
        return min(
            ordered,
            key=lambda node: (
                node.accumulated_cost + parameters.alpha * math.dist(node.point, goal),
                node.accumulated_cost,
                node.node_id,
            ),
        )
    return ordered[int(numpy_rng.integers(len(ordered)))]


def _reconstruct(
    nodes: list[CandidateNode], node: CandidateNode, goal: Point
) -> list[Point]:
    chain = [node.point]
    parent = node.parent_id
    while parent is not None:
        ancestor = nodes[parent]
        chain.append(ancestor.point)
        parent = ancestor.parent_id
    chain.reverse()
    chain.append(goal)
    return chain


def _increment(counters: SearchCounters, name: str) -> None:
    setattr(counters, name, int(getattr(counters, name) or 0) + 1)


def _free(
    first: Point, second: Point, grid: OccupancyMap, counters: SearchCounters
) -> bool:
    _increment(counters, "collision_checks")
    return validate_path([first, second], grid).valid


def run_search(
    grid: OccupancyMap,
    start: Point,
    goal: Point,
    seed: int,
    limits: PlanningLimits,
    parameters: dict[str, Any] | None,
    *,
    method: str,
    version: str,
    safety_guards: bool,
) -> PlanResult:
    """Run the common paper controller with explicitly selected safety guards.

    Sharing this independent controller avoids two drifting copies of algorithms
    1 and 5. Safety mode additionally filters parent edges and whole goal paths;
    paper mode preserves algorithm-5 insertion without a hidden parent filter.
    Both modes retain actual paths and make a final strict verdict visible.
    """
    deadline = Deadline(limits.time_limit)
    counters = SearchCounters()
    configuration: dict[str, Any] = {}
    events: dict[str, int | str | bool | None] = {
        "safety_guards": safety_guards,
        "paper_counter": 0,
        "pathset_size": 0,
        "graph_nodes": 0,
        "sampling_counter_unit": "rays",
        "valid_candidates_rule": (
            "strict_parent_edge" if safety_guards else "finite_coordinates_admitted"
        ),
    }
    try:
        options = PaperParameters(**(parameters or {}))
        configuration = asdict(options)
        configuration.update(
            choose_sun="epsilon_min_g_plus_alpha_h_otherwise_uniform",
            choose_sun_details="alpha_epsilon_from_author_defaults_not_defined_in_paper",
            collision_policy="closed_voxels_contact_is_collision_closed_map_domain",
            ray_optimization="single_supercover_slab_entry_adjacent_prefix_correction",
            limits=asdict(limits),
            seed=seed,
        )
        start, goal = _point(start), _point(goal)
        if type(seed) is not int or seed < 0:
            raise ValueError("Seed must be a nonnegative integer")
        if not _free(start, start, grid, counters) or not _free(
            goal, goal, grid, counters
        ):
            raise ValueError("Start or goal is outside free space")
        python_rng = random.Random(seed)
        numpy_rng = np.random.default_rng(seed)
    except (TypeError, ValueError) as error:
        events["error"] = str(error)
        return PlanResult(
            method,
            version,
            "invalid_input",
            "invalid_input",
            False,
            None,
            deadline.elapsed,
            counters,
            configuration,
            events=events,
        )

    opened = GridCandidates(
        grid.origin, options.grid_side_length, options.grid_capacity
    )
    nodes = [CandidateNode(0, start, 0.0, None)]
    opened.insert(nodes[0])
    pathset: list[tuple[float, list[Point]]] = []
    paper_counter = 0
    status = "no_path"
    termination = "open_exhausted"
    try:
        while len(opened) and paper_counter <= options.n_max:
            deadline.check()
            if int(counters.expanded_nodes or 0) >= limits.max_iterations:
                raise BudgetExceeded("iteration_budget")
            sun = _choose_sun(opened, goal, options, python_rng, numpy_rng)
            opened.remove(sun.node_id)
            _increment(counters, "expanded_nodes")
            if _free(sun.point, goal, grid, counters):
                path = _reconstruct(nodes, sun, goal)
                if safety_guards:
                    _increment(counters, "collision_checks")
                    if not validate_path(path, grid).valid:
                        _increment(counters, "collision_filtered")
                        continue
                pathset.append(
                    (sun.accumulated_cost + math.dist(sun.point, goal), path)
                )
                # Algorithm 1 line 9 does not increment its expansion counter.
                continue

            generated = 0
            for candidate in tangent_candidates(
                sun.point, goal, grid, options, deadline, counters
            ):
                deadline.check()
                generated += 1
                _increment(counters, "generated_candidates")
                point = _point(candidate)
                if safety_guards and not _free(sun.point, point, grid, counters):
                    _increment(counters, "collision_filtered")
                    continue
                # V contains the special goal in addition to immutable tree nodes.
                if len(nodes) + 1 >= limits.max_nodes:
                    raise BudgetExceeded("node_budget")
                node = CandidateNode(
                    len(nodes),
                    point,
                    sun.accumulated_cost + math.dist(sun.point, point),
                    sun.node_id,
                )
                nodes.append(node)
                _increment(counters, "valid_candidates")
                if opened.insert(node) is not None:
                    _increment(counters, "capacity_evicted")
            if generated == 0:
                _increment(counters, "no_candidate_expansions")
            # Empty tangent sets still reach line 15 in the paper.
            paper_counter += 1
        termination = "open_exhausted" if not len(opened) else "paper_iteration_limit"
        status = "ok" if pathset else "no_path"
    except BudgetExceeded as error:
        termination = str(error)
        status = "timeout" if termination == "time_budget" else "budget_exhausted"
    except ValueError as error:
        LOGGER.exception("Independent planner rejected a search-state value")
        termination = "invalid_search_state"
        status = "error"
        events["error"] = str(error)

    counters.final_open_nodes = len(opened)
    events.update(
        paper_counter=paper_counter,
        pathset_size=len(pathset),
        graph_nodes=len(nodes) + 1,
    )
    best_path = min(pathset, key=lambda item: item[0])[1] if pathset else None
    if best_path is not None:
        _increment(counters, "collision_checks")
        events["internal_raw_valid"] = validate_path(best_path, grid).valid
        if not events["internal_raw_valid"]:
            status, termination = "error", "invalid_solution"
    return PlanResult(
        method,
        version,
        status,
        termination,
        bool(pathset),
        best_path,
        deadline.elapsed,
        counters,
        configuration,
        events=events,
    )


def plan(
    grid: OccupancyMap,
    start: Point,
    goal: Point,
    seed: int,
    limits: PlanningLimits,
    parameters: dict[str, Any] | None = None,
) -> PlanResult:
    """Independently reconstruct the paper with disclosed choices; never import authors.

    Coordinates are physical map units. Invalid endpoints or parameters return
    invalid_input; budgets retain an incumbent path with their non-ok status.
    A reported path with failed strict validation retains its evidence and gets
    error/invalid_solution, rather than being advertised as a valid solution.
    """
    return run_search(
        grid,
        start,
        goal,
        seed,
        limits,
        parameters,
        method=METHOD,
        version=VERSION,
        safety_guards=False,
    )
