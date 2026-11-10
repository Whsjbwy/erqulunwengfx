"""A* safety, endpoint fidelity, optimal graph cost and budget regressions."""

import heapq
import math
from itertools import product

import numpy as np
import pytest

from gsunlight_repro.astar import neighbor_is_free, plan
from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.metrics import path_length
from gsunlight_repro.planning import PlanningLimits


def gap_map() -> OccupancyMap:
    """Return a small wall with a known high-y route around its end."""
    values = np.zeros((6, 6, 3), dtype=bool)
    values[3, :4, :] = True
    return OccupancyMap(values)


def test_empty_direct_path_keeps_true_endpoints_and_euclidean_length() -> None:
    grid = OccupancyMap(np.zeros((6, 6, 6), dtype=bool))
    start, goal = (1, 1, 1), (5, 5, 5)
    result = plan(grid, start, goal, 0, PlanningLimits())
    assert result.status == "ok"
    assert result.raw_path == [start, goal]
    assert path_length(result.raw_path) == pytest.approx(math.sqrt(48))


def test_route_uses_unsnapped_grid_vertex_endpoints_and_strict_edges() -> None:
    grid = gap_map()
    start, goal = (1, 1, 1), (5, 1, 2)
    result = plan(grid, start, goal, 0, PlanningLimits(max_iterations=1))
    assert result.status == "ok"
    assert result.raw_path[0] == start
    assert result.raw_path[-1] == goal
    assert validate_path(result.raw_path, grid).valid
    assert result.counters.expanded_nodes > 1
    assert result.parameters["max_iterations_not_applicable"] == 1


def test_local_neighbor_shortcut_matches_all_2264_obstacle_combinations() -> None:
    occupancy = np.zeros((5, 5, 5), dtype=bool)
    grid = OccupancyMap(occupancy)
    cell = (2, 2, 2)
    cases = 0
    for offset in product((-1, 0, 1), repeat=3):
        if not any(offset):
            continue
        touched = list(product(*[(0, value) if value else (0,) for value in offset]))
        destination = tuple(cell[axis] + offset[axis] for axis in range(3))
        start = tuple(value + 0.5 for value in cell)
        goal = tuple(value + 0.5 for value in destination)
        for pattern in range(2 ** len(touched)):
            occupancy.fill(False)
            for index, shift in enumerate(touched):
                occupancy[tuple(cell[axis] + shift[axis] for axis in range(3))] = bool(
                    pattern & (1 << index)
                )
            expected = validate_path([start, goal], grid).valid
            assert neighbor_is_free(grid, cell, offset) == expected
            assert (
                neighbor_is_free(grid, destination, tuple(-value for value in offset))
                == expected
            )
            cases += 1
    assert cases == 2264


def test_neighbor_shortcut_shifted_anisotropic_map_and_map_edges() -> None:
    occupancy = np.zeros((4, 4, 4), dtype=bool)
    grid = OccupancyMap(occupancy, (10, -3, 7), (2, 3, 4))
    cell = (1, 1, 1)
    for offset in product((-1, 0, 1), repeat=3):
        if not any(offset):
            continue
        destination = tuple(cell[axis] + offset[axis] for axis in range(3))
        occupancy.fill(False)
        occupancy[destination] = True
        points = [
            tuple(
                grid.origin[axis] + (index[axis] + 0.5) * grid.spacing[axis]
                for axis in range(3)
            )
            for index in (cell, destination)
        ]
        assert neighbor_is_free(grid, cell, offset) == validate_path(points, grid).valid
    assert not neighbor_is_free(grid, (0, 0, 0), (-1, 0, 0))
    with pytest.raises(ValueError, match="26-neighbor"):
        neighbor_is_free(grid, cell, (2, 0, 0))


def independent_dijkstra_cost(grid: OccupancyMap, start: tuple, goal: tuple) -> float:
    """Find the center-graph optimum using full strict checks, not the shortcut."""
    frontier = [(0.0, start)]
    costs = {start: 0.0}
    while frontier:
        cost, current = heapq.heappop(frontier)
        if cost > costs[current]:
            continue
        if current == goal:
            return cost
        for offset in product((-1, 0, 1), repeat=3):
            if not any(offset):
                continue
            neighbor = tuple(current[axis] + offset[axis] for axis in range(3))
            if any(not 0 <= neighbor[axis] < grid.shape[axis] for axis in range(3)):
                continue
            points = [
                tuple(value + 0.5 for value in cell) for cell in (current, neighbor)
            ]
            if not validate_path(points, grid).valid:
                continue
            candidate = cost + math.sqrt(sum(value * value for value in offset))
            if candidate < costs.get(neighbor, math.inf):
                costs[neighbor] = candidate
                heapq.heappush(frontier, (candidate, neighbor))
    return math.inf


def test_astar_cost_matches_independent_dijkstra_graph_optimum() -> None:
    grid = gap_map()
    start, goal = (0.5, 0.5, 1.5), (5.5, 0.5, 1.5)
    result = plan(grid, start, goal, 7, PlanningLimits())
    assert result.status == "ok"
    expected = independent_dijkstra_cost(grid, (0, 0, 1), (5, 0, 1))
    assert path_length(result.raw_path) == pytest.approx(expected)


def test_sealed_small_map_exhaustion_is_no_path() -> None:
    values = np.zeros((5, 5, 3), dtype=bool)
    values[2, :, :] = True
    result = plan(
        OccupancyMap(values), (0.5, 0.5, 1.5), (4.5, 4.5, 1.5), 0, PlanningLimits()
    )
    assert result.status == "no_path"
    assert result.termination_reason == "open_set_exhausted"
    assert result.raw_path is None


def test_corner_endpoint_incident_obstacle_is_not_missed_by_floor() -> None:
    values = np.zeros((5, 5, 3), dtype=bool)
    values[0, 0, 0] = True
    result = plan(OccupancyMap(values), (1, 1, 1), (4, 4, 2), 0, PlanningLimits())
    assert result.status == "invalid_input"
    assert result.termination_reason == "invalid_start"


def test_node_budget_and_timeout_keep_partial_counters() -> None:
    grid = gap_map()
    start, goal = (0.5, 0.5, 1.5), (5.5, 0.5, 1.5)
    limited = plan(grid, start, goal, 0, PlanningLimits(max_nodes=2))
    assert limited.status == "budget_exhausted"
    assert limited.termination_reason == "node_budget"
    assert limited.counters.sampled_nodes == 2
    assert limited.counters.collision_checks > 0
    timed = plan(grid, start, goal, 0, PlanningLimits(time_limit=1e-12))
    assert timed.status == "timeout"
    assert timed.counters.collision_checks > 0


def test_unknown_parameters_are_not_silently_ignored() -> None:
    result = plan(
        gap_map(),
        (0.5, 0.5, 1.5),
        (5.5, 0.5, 1.5),
        0,
        PlanningLimits(),
        {"unexpected": True},
    )
    assert result.status == "invalid_input"


def test_astar_is_deterministic_across_seeds() -> None:
    arguments = (gap_map(), (0.5, 0.5, 1.5), (5.5, 0.5, 1.5))
    first = plan(*arguments, 0, PlanningLimits())
    second = plan(*arguments, 4, PlanningLimits())
    assert first.raw_path == second.raw_path
