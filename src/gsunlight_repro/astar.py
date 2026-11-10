"""Independent 26-neighbor A* with exact endpoints and closed-voxel edges."""

from __future__ import annotations

import heapq
import math
from itertools import count, product
from typing import Any

import numpy as np

from .collision_checker import GRID_TOLERANCE, validate_path
from .map_reader import OccupancyMap, Point, Voxel
from .planning import (
    BudgetExceeded,
    Deadline,
    PlanningLimits,
    PlanResult,
    SearchCounters,
)

_OFFSETS = tuple(offset for offset in product((-1, 0, 1), repeat=3) if any(offset))
_TOUCHED = {
    offset: tuple(product(*[(0, value) if value else (0,) for value in offset]))
    for offset in _OFFSETS
}


def neighbor_is_free(grid: OccupancyMap, cell: Voxel, offset: Voxel) -> bool:
    """Check the exact closed-voxel supercover of a center-to-neighbor edge.

    For a 26-neighbor edge all changing axes cross one plane simultaneously at
    t=1/2. Its touched cells are exactly the 2**k source/target index choices.
    This shortcut is not valid for arbitrary endpoints or multi-cell edges.
    An invalid offset raises ``ValueError``; out-of-map cells return false.
    """
    if offset not in _TOUCHED:
        raise ValueError("Offset must be a nonzero 26-neighbor displacement")
    destination = tuple(cell[axis] + offset[axis] for axis in range(3))
    if any(
        not 0 <= cell[axis] < grid.shape[axis]
        or not 0 <= destination[axis] < grid.shape[axis]
        for axis in range(3)
    ):
        return False
    return all(
        not grid.occupancy[cell[0] + shift[0], cell[1] + shift[1], cell[2] + shift[2]]
        for shift in _TOUCHED[offset]
    )


def _center(cell: Voxel, grid: OccupancyMap) -> Point:
    return tuple(
        grid.origin[axis] + (cell[axis] + 0.5) * grid.spacing[axis] for axis in range(3)
    )


def _incident_cells(point: Point, grid: OccupancyMap) -> list[Voxel]:
    axes = []
    for axis in range(3):
        coordinate = (point[axis] - grid.origin[axis]) / grid.spacing[axis]
        nearest = round(coordinate)
        if abs(coordinate - nearest) <= GRID_TOLERANCE:
            candidates = (nearest - 1, nearest)
        else:
            candidates = (math.floor(coordinate),)
        axes.append([index for index in candidates if 0 <= index < grid.shape[axis]])
    return list(product(*axes))


def _distance(first: Point, second: Point) -> float:
    return math.sqrt(sum((first[axis] - second[axis]) ** 2 for axis in range(3)))


def plan(
    grid: OccupancyMap,
    start: Point,
    goal: Point,
    seed: int,
    limits: PlanningLimits,
    parameters: dict[str, Any] | None = None,
) -> PlanResult:
    """Plan on a 26-neighbor center graph with virtual, unsnapped endpoints.

    Costs are physical Euclidean lengths. Every endpoint connection is checked
    by the continuous validator; every graph edge uses its proven equivalent
    local supercover. The seed is recorded but A* is deterministic. Node/time
    exhaustion returns an explicit failure with partial counters and no path.
    """
    deadline = Deadline(limits.time_limit)
    counters = SearchCounters()
    effective: dict[str, Any] = {
        "seed": seed,
        "seed_used": False,
        "time_limit": limits.time_limit,
        "max_nodes": limits.max_nodes,
        "max_iterations_not_applicable": limits.max_iterations,
        "connectivity": 26,
        "heuristic": "euclidean_to_true_goal",
        "endpoint_connections": "all_incident_cell_centers",
        "edge_validation": "exact_local_supercover",
        "direct_connection_check": True,
    }
    costs: np.ndarray | None = None
    closed: np.ndarray | None = None

    def finish(status: str, reason: str, path: list[Point] | None = None) -> PlanResult:
        if costs is not None and closed is not None:
            counters.final_open_nodes = int(
                np.count_nonzero(np.isfinite(costs) & ~closed)
            )
        return PlanResult(
            "astar",
            "stage2-astar-v1",
            status,
            reason,
            path is not None,
            path,
            deadline.elapsed,
            counters,
            effective,
        )

    try:
        if parameters:
            raise ValueError(f"Unknown A* parameters: {sorted(parameters)}")
        endpoints = np.asarray([start, goal], dtype=float)
        if endpoints.shape != (2, 3) or not np.all(np.isfinite(endpoints)):
            raise ValueError("Endpoints must contain three finite coordinates")
        start = tuple(float(value) for value in endpoints[0])
        goal = tuple(float(value) for value in endpoints[1])
        for name, point in (("start", start), ("goal", goal)):
            counters.collision_checks += 1
            if not validate_path([point, point], grid).valid:
                return finish("invalid_input", f"invalid_{name}")
        deadline.check()
        counters.collision_checks += 1
        if validate_path([start, goal], grid).valid:
            return finish("ok", "direct_connection", [start, goal])

        shape = grid.shape
        costs = np.full(shape, np.inf)
        closed = np.zeros(shape, dtype=bool)
        parents = np.full(shape, -1, dtype=np.int64)
        frontier: list[tuple[float, float, int, Voxel]] = []
        insertion = count()
        goal_cells: set[Voxel] = set()
        for cell in _incident_cells(goal, grid):
            deadline.check()
            counters.collision_checks += 1
            if validate_path([_center(cell, grid), goal], grid).valid:
                goal_cells.add(cell)
        for cell in _incident_cells(start, grid):
            deadline.check()
            counters.collision_checks += 1
            center = _center(cell, grid)
            if not validate_path([start, center], grid).valid:
                continue
            if counters.sampled_nodes >= limits.max_nodes:
                raise BudgetExceeded("node_budget")
            initial = _distance(start, center)
            costs[cell] = initial
            counters.sampled_nodes += 1
            heapq.heappush(
                frontier,
                (initial + _distance(center, goal), initial, next(insertion), cell),
            )
        lengths = {
            offset: math.sqrt(
                sum((offset[axis] * grid.spacing[axis]) ** 2 for axis in range(3))
            )
            for offset in _OFFSETS
        }
        while frontier:
            deadline.check()
            _, cost, _, cell = heapq.heappop(frontier)
            if closed[cell] or cost > costs[cell]:
                continue
            closed[cell] = True
            counters.expanded_nodes += 1
            if cell in goal_cells:
                reverse_centers = []
                current = cell
                while True:
                    reverse_centers.append(_center(current, grid))
                    parent = int(parents[current])
                    if parent < 0:
                        break
                    current = (
                        parent // (shape[1] * shape[2]),
                        (parent // shape[2]) % shape[1],
                        parent % shape[2],
                    )
                path = [start, *reversed(reverse_centers), goal]
                return finish("ok", "goal_reached", path)
            valid_count = 0
            for offset in _OFFSETS:
                deadline.check()
                destination = tuple(cell[axis] + offset[axis] for axis in range(3))
                if (
                    any(not 0 <= destination[axis] < shape[axis] for axis in range(3))
                    or closed[destination]
                ):
                    continue
                counters.generated_candidates += 1
                counters.collision_checks += 1
                if not neighbor_is_free(grid, cell, offset):
                    counters.collision_filtered += 1
                    continue
                counters.valid_candidates += 1
                valid_count += 1
                candidate = cost + lengths[offset]
                if candidate >= costs[destination]:
                    continue
                if not np.isfinite(costs[destination]):
                    if counters.sampled_nodes >= limits.max_nodes:
                        raise BudgetExceeded("node_budget")
                    counters.sampled_nodes += 1
                costs[destination] = candidate
                parents[destination] = (cell[0] * shape[1] + cell[1]) * shape[2] + cell[
                    2
                ]
                center = _center(destination, grid)
                heapq.heappush(
                    frontier,
                    (
                        candidate + _distance(center, goal),
                        candidate,
                        next(insertion),
                        destination,
                    ),
                )
            if valid_count == 0:
                counters.no_candidate_expansions += 1
        return finish("no_path", "open_set_exhausted")
    except BudgetExceeded as error:
        reason = str(error)
        return finish(
            "timeout" if reason == "time_budget" else "budget_exhausted", reason
        )
    except (TypeError, ValueError) as error:
        return finish("invalid_input", str(error))
