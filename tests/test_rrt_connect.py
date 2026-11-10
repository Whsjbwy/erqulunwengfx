"""RRT-Connect exact joins, tree swaps, sampling reproducibility and limits."""

import numpy as np
import pytest

from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.planning import PlanningLimits
from gsunlight_repro.rrt_connect import _joined_path, _Tree, plan


def gap_map() -> OccupancyMap:
    """Return a small wall with a high-y passage."""
    values = np.zeros((6, 6, 3), dtype=bool)
    values[3, :4, :] = True
    return OccupancyMap(values)


def test_empty_direct_and_zero_length_keep_exact_endpoints() -> None:
    grid = OccupancyMap(np.zeros((6, 6, 3), dtype=bool))
    for start, goal in [((1, 1, 1), (5, 5, 2)), ((1, 1, 1), (1, 1, 1))]:
        result = plan(grid, start, goal, 0, PlanningLimits())
        assert result.status == "ok"
        assert result.raw_path == [start, goal]
        assert validate_path(result.raw_path, grid).valid


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_returned_wall_detours_are_strict_and_have_true_endpoints(seed: int) -> None:
    grid = gap_map()
    start, goal = (1, 1, 1), (5, 1, 2)
    result = plan(
        grid, start, goal, seed, PlanningLimits(time_limit=5), {"step_size": 1.5}
    )
    assert result.status == "ok"
    assert result.raw_path[0] == start
    assert result.raw_path[-1] == goal
    assert validate_path(result.raw_path, grid).valid
    assert result.events["tree_swaps"] > 0


def test_joining_after_tree_swap_preserves_start_to_goal_direction() -> None:
    start, joint, goal = (0.5, 0.5, 0.5), (2.5, 1.5, 1.5), (4.5, 3.5, 2.5)
    tree_goal = _Tree("goal", [goal, joint], [-1, 0])
    tree_start = _Tree("start", [start, joint], [-1, 0])
    assert _joined_path(tree_goal, 1, tree_start, 1) == [start, joint, goal]


def test_sampling_repeats_for_same_seed() -> None:
    arguments = (gap_map(), (1, 1, 1), (5, 1, 2), 3, PlanningLimits(time_limit=5))
    first = plan(*arguments, {"step_size": 1.5})
    second = plan(*arguments, {"step_size": 1.5})
    assert first.raw_path == second.raw_path
    assert first.counters == second.counters


def test_iteration_and_node_limits_are_distinct_from_no_path() -> None:
    grid = gap_map()
    start, goal = (0.5, 0.5, 1.5), (5.5, 0.5, 1.5)
    iteration_limited = plan(
        grid,
        start,
        goal,
        0,
        PlanningLimits(max_iterations=1),
        {"step_size": 1, "goal_bias": 1},
    )
    assert iteration_limited.status == "budget_exhausted"
    assert iteration_limited.termination_reason == "iteration_budget"
    node_limited = plan(
        grid,
        start,
        goal,
        0,
        PlanningLimits(max_nodes=2),
        {"step_size": 1, "goal_bias": 1},
    )
    assert node_limited.status == "budget_exhausted"
    assert node_limited.termination_reason == "node_budget"
    assert node_limited.counters.sampled_nodes == 2
    assert node_limited.counters.generated_candidates > 0


def test_timeout_keeps_partial_counters() -> None:
    result = plan(gap_map(), (1, 1, 1), (5, 1, 2), 0, PlanningLimits(time_limit=1e-12))
    assert result.status == "timeout"
    assert result.counters.collision_checks > 0


def test_sampling_existing_root_does_not_cause_zero_progress_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RootSampler:
        def random(self) -> float:
            return 0.5

        def uniform(self, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
            return np.array([0.5, 0.5, 1.5])

    monkeypatch.setattr(np.random, "default_rng", lambda _: RootSampler())
    result = plan(
        gap_map(),
        (0.5, 0.5, 1.5),
        (5.5, 0.5, 1.5),
        0,
        PlanningLimits(max_iterations=3),
        {"step_size": 1, "goal_bias": 0},
    )
    assert result.status == "budget_exhausted"
    assert result.termination_reason == "iteration_budget"
    assert result.events["outer_iterations"] == 3
    assert result.counters.expanded_nodes < 20


@pytest.mark.parametrize(
    "parameters",
    [
        {"step_size": 0},
        {"step_size": np.inf},
        {"goal_bias": -1},
        {"goal_bias": np.nan},
        {"unknown": 1},
    ],
)
def test_invalid_parameters_are_reported(parameters: dict) -> None:
    result = plan(gap_map(), (1, 1, 1), (5, 1, 2), 0, PlanningLimits(), parameters)
    assert result.status == "invalid_input"
    assert result.raw_path is None


def test_occupied_corner_endpoint_is_invalid() -> None:
    values = np.zeros((6, 6, 3), dtype=bool)
    values[0, 0, 0] = True
    result = plan(OccupancyMap(values), (1, 1, 1), (5, 5, 2), 0, PlanningLimits())
    assert result.status == "invalid_input"
    assert result.termination_reason == "invalid_start"
