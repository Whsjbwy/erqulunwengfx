"""Verify explicit parent guards and complete-path postprocessing safeguards."""

import numpy as np
import pytest

from gsunlight_repro import paper_planner, safety_planner
from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.planning import PlanningLimits


def test_safe_reference_rejects_the_parent_edge_before_insertion(monkeypatch) -> None:
    """A candidate beyond a closed wall cannot create an unsafe goal path."""
    occupancy = np.zeros((6, 4, 3), dtype=bool)
    occupancy[2, :, :] = True
    grid = OccupancyMap(occupancy)
    monkeypatch.setattr(
        paper_planner, "tangent_candidates", lambda *args: iter([(4.5, 0.5, 0.5)])
    )
    result = safety_planner.plan(
        grid, (0.5, 0.5, 0.5), (5.5, 0.5, 0.5), 0, PlanningLimits()
    )
    assert result.method == "safety_reference" and result.version == "stage2-safety-v1"
    assert result.status == "no_path" and result.raw_path is None
    assert result.counters.collision_filtered == 1
    assert result.counters.valid_candidates == 0


def test_narrow_opening_route_remains_strictly_valid(monkeypatch) -> None:
    """Use a known narrow-window route to test the full guarded control chain."""
    occupancy = np.zeros((7, 7, 3), dtype=bool)
    occupancy[3, :, :] = True
    occupancy[3, 4:6, :] = False
    grid = OccupancyMap(occupancy)
    start, goal = (0.5, 0.5, 0.5), (6.5, 0.5, 0.5)
    route = [(2.5, 5.0, 0.5), (4.5, 5.0, 0.5)]

    def sampler(point, *args):
        return iter([route[0]] if point == start else [route[1]])

    monkeypatch.setattr(paper_planner, "tangent_candidates", sampler)
    result = safety_planner.plan(
        grid, start, goal, 0, PlanningLimits(), {"grid_side_length": 1}
    )
    assert result.status == "ok" and result.raw_path == [start, *route, goal]
    assert validate_path(result.raw_path, grid).valid
    assert result.events["internal_raw_valid"]
    assert result.postprocessed_path is None


def test_closed_wall_does_not_gain_a_fallback_path() -> None:
    """A real sampling run on a sealed scene cannot call another planner to succeed."""
    occupancy = np.zeros((4, 4, 3), dtype=bool)
    occupancy[2, :, :] = True
    grid = OccupancyMap(occupancy)
    result = safety_planner.plan(
        grid,
        (0.5, 0.5, 0.5),
        (3.5, 3.5, 2.5),
        1,
        PlanningLimits(time_limit=3, max_iterations=2),
        {
            "theta_step_degrees": 30,
            "phi_step_degrees": 90,
            "half_cone_degrees": 60,
            "distance_step": 0.5,
            "length_threshold": 0.1,
            "forward_distance": 0.2,
        },
    )
    assert not result.reported_success and result.raw_path is None
    assert result.status in {"no_path", "budget_exhausted"}


def test_safe_postprocessing_rolls_back_collisions_or_changed_endpoints() -> None:
    """No shortcut or endpoint movement may bypass the complete-path guard."""
    occupancy = np.zeros((4, 4, 3), dtype=bool)
    occupancy[1, 1, 0] = True
    grid = OccupancyMap(occupancy)
    original = [(0.5, 1.5, 0.5), (0.5, 3.5, 0.5), (3.5, 3.5, 0.5), (3.5, 1.5, 0.5)]
    assert (
        safety_planner.accept_safe_postprocessing(original, original[::3], grid)
        == original
    )
    assert (
        safety_planner.accept_safe_postprocessing(original, original[1:], grid)
        == original
    )
    with pytest.raises(ValueError, match="valid"):
        safety_planner.accept_safe_postprocessing(original[::3], original, grid)


def test_safe_helper_accepts_a_valid_endpoint_preserving_result() -> None:
    """The helper supports safe common postprocessing without modifying its inputs."""
    grid = OccupancyMap(np.zeros((4, 4, 3), dtype=bool))
    original = [(0.5, 0.5, 0.5), (0.5, 3.5, 0.5), (3.5, 3.5, 0.5)]
    shortcut = [original[0], original[-1]]
    assert (
        safety_planner.accept_safe_postprocessing(original, shortcut, grid) == shortcut
    )
    assert len(original) == 3
