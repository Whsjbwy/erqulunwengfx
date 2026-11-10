"""Test paper control flow independently from conical geometric sampling."""

import math

import numpy as np
import pytest

from gsunlight_repro import paper_planner
from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.metrics import path_length
from gsunlight_repro.planning import PlanningLimits


@pytest.fixture
def blocked_problem():
    """Provide a finite wall with an explicit safe route above it."""
    occupancy = np.zeros((6, 6, 3), dtype=bool)
    occupancy[2, :2, :] = True
    return OccupancyMap(occupancy), (0.5, 0.5, 0.5), (5.5, 0.5, 0.5)


def test_empty_map_connects_before_sampling(monkeypatch) -> None:
    """A clear goal is connected from the current sun with paper counter zero."""

    def forbidden(*args):
        raise AssertionError("The direct-goal branch must skip tangent sampling")

    monkeypatch.setattr(paper_planner, "tangent_candidates", forbidden)
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    result = paper_planner.plan(
        grid, (0.5, 0.5, 0.5), (2.5, 2.5, 2.5), 0, PlanningLimits()
    )
    assert result.status == "ok" and result.reported_success
    assert result.raw_path == [(0.5, 0.5, 0.5), (2.5, 2.5, 2.5)]
    assert result.events["paper_counter"] == 0
    assert result.counters.expanded_nodes == 1
    assert result.postprocessed_path is None
    assert path_length(result.raw_path) == pytest.approx(math.sqrt(12))


def test_coincident_endpoints_form_a_valid_zero_path() -> None:
    """Preserve both exact endpoints without constructing an undefined cone axis."""
    grid = OccupancyMap(np.zeros((2, 2, 2), dtype=bool))
    point = (0.5, 0.5, 0.5)
    result = paper_planner.plan(grid, point, point, 0, PlanningLimits())
    assert result.raw_path == [point, point]
    assert result.status == "ok" and validate_path(result.raw_path, grid).valid


def test_all_goal_connections_are_kept_until_open_exhaustion(
    monkeypatch, blocked_problem
) -> None:
    """The later path can be shorter than the first successful connection."""
    grid, start, goal = blocked_problem
    first, better = (0.5, 5.5, 0.5), (1.5, 5.5, 0.5)
    monkeypatch.setattr(
        paper_planner, "tangent_candidates", lambda *args: iter([first, better])
    )
    result = paper_planner.plan(
        grid,
        start,
        goal,
        0,
        PlanningLimits(),
        {"alpha": 0.0, "epsilon": 1.0, "grid_side_length": 1.0},
    )
    assert result.raw_path == [start, better, goal]
    assert result.status == "ok" and validate_path(result.raw_path, grid).valid
    assert result.events["pathset_size"] == 2
    assert result.events["paper_counter"] == 1
    assert result.counters.expanded_nodes == 3
    assert path_length([start, better, goal]) < path_length([start, first, goal])


def test_original_corner_contact_fixture_is_an_explicit_collision() -> None:
    """Retain the rejected test design as a closed-corner contact counterexample."""
    occupancy = np.zeros((6, 6, 3), dtype=bool)
    occupancy[2, :3, :] = True
    grid = OccupancyMap(occupancy)
    verdict = validate_path([(0.5, 0.5, 0.5), (0.5, 5.5, 0.5), (5.5, 0.5, 0.5)], grid)
    assert not verdict.valid and verdict.first_collision_segment == 1
    assert verdict.first_collision_point == pytest.approx((3.0, 3.0, 0.5))


def test_paper_inclusive_nmax_is_distinct_from_external_iteration_budget(
    monkeypatch, blocked_problem
) -> None:
    """One non-direct expansion is allowed at n_max=0, but its new nodes remain."""
    grid, start, goal = blocked_problem
    monkeypatch.setattr(
        paper_planner, "tangent_candidates", lambda *args: iter([(0.5, 5.5, 0.5)])
    )
    result = paper_planner.plan(grid, start, goal, 0, PlanningLimits(), {"n_max": 0})
    assert result.status == "no_path"
    assert result.termination_reason == "paper_iteration_limit"
    assert result.events["paper_counter"] == 1
    assert result.counters.expanded_nodes == 1 and result.counters.final_open_nodes == 1


def test_empty_candidates_still_increment_paper_counter(
    monkeypatch, blocked_problem
) -> None:
    """Do not copy the author's early continue on an empty tangent set."""
    grid, start, goal = blocked_problem
    monkeypatch.setattr(paper_planner, "tangent_candidates", lambda *args: iter([]))
    result = paper_planner.plan(grid, start, goal, 0, PlanningLimits())
    assert result.termination_reason == "open_exhausted"
    assert result.events["paper_counter"] == 1
    assert result.counters.no_candidate_expansions == 1


def test_node_budget_is_enforced_while_candidates_are_generated(
    monkeypatch, blocked_problem
) -> None:
    """Do not finish an unbounded tangent list before checking graph storage."""
    grid, start, goal = blocked_problem
    monkeypatch.setattr(
        paper_planner, "tangent_candidates", lambda *args: iter([(0.5, 5.5, 0.5)])
    )
    result = paper_planner.plan(grid, start, goal, 0, PlanningLimits(max_nodes=2))
    assert (
        result.status == "budget_exhausted"
        and result.termination_reason == "node_budget"
    )
    assert result.events["graph_nodes"] == 2
    assert result.counters.generated_candidates == 1


def test_iteration_budget_retains_but_labels_an_incumbent(
    monkeypatch, blocked_problem
) -> None:
    """A partial result does not become a normally completed search."""
    grid, start, goal = blocked_problem
    first, later = (0.5, 5.5, 0.5), (1.5, 5.5, 0.5)
    monkeypatch.setattr(
        paper_planner, "tangent_candidates", lambda *args: iter([first, later])
    )
    result = paper_planner.plan(
        grid,
        start,
        goal,
        0,
        PlanningLimits(max_iterations=2),
        {"alpha": 0.0, "epsilon": 1.0, "grid_side_length": 1.0},
    )
    assert result.status == "budget_exhausted"
    assert result.termination_reason == "iteration_budget"
    assert result.reported_success and result.raw_path == [start, first, goal]


def test_timeout_is_checked_after_yield_inside_sampling(
    monkeypatch, blocked_problem
) -> None:
    """The controller must check its deadline immediately on a yielded candidate."""
    grid, start, goal = blocked_problem

    def expired(point, target, map_data, parameters, deadline, counters):
        deadline.ends = deadline.started
        yield (0.5, 5.5, 0.5)

    monkeypatch.setattr(paper_planner, "tangent_candidates", expired)
    result = paper_planner.plan(grid, start, goal, 0, PlanningLimits())
    assert result.status == "timeout" and result.termination_reason == "time_budget"
    assert result.raw_path is None


def test_paper_does_not_hide_an_invalid_generated_parent_edge(
    monkeypatch, blocked_problem
) -> None:
    """Retain evidence and report invalid_solution instead of a safe-looking success."""
    grid, start, goal = blocked_problem
    monkeypatch.setattr(
        paper_planner, "tangent_candidates", lambda *args: iter([(4.5, 0.5, 0.5)])
    )
    result = paper_planner.plan(grid, start, goal, 0, PlanningLimits())
    assert result.reported_success and result.raw_path is not None
    assert result.status == "error" and result.termination_reason == "invalid_solution"
    assert not result.events["internal_raw_valid"]
    assert not validate_path(result.raw_path, grid).valid
    assert result.counters.collision_filtered == 0


@pytest.mark.parametrize(
    "parameters", [{"unknown": 3}, {"n_max": -1}, {"alpha": math.nan}]
)
def test_bad_configuration_is_not_silently_ignored(parameters: dict) -> None:
    """Unknown or malformed settings produce explicit invalid_input results."""
    grid = OccupancyMap(np.zeros((2, 2, 2), dtype=bool))
    result = paper_planner.plan(
        grid, (0.5, 0.5, 0.5), (1.5, 0.5, 0.5), 0, PlanningLimits(), parameters
    )
    assert result.status == "invalid_input" and not result.reported_success


def test_invalid_endpoints_do_not_enter_sampling() -> None:
    """Reject out-of-domain and occupied start configurations explicitly."""
    occupancy = np.zeros((3, 3, 3), dtype=bool)
    occupancy[0, 0, 0] = True
    grid = OccupancyMap(occupancy)
    for start in ((0.5, 0.5, 0.5), (-0.1, 2.5, 2.5)):
        result = paper_planner.plan(grid, start, (2.5, 2.5, 2.5), 0, PlanningLimits())
        assert result.status == "invalid_input" and result.raw_path is None
