"""Check independent rotations, angular boundaries and strict ray equivalence."""

import math

import numpy as np
import pytest

from gsunlight_repro import sampling
from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.planning import BudgetExceeded, Deadline, SearchCounters
from gsunlight_repro.sampling import SamplingParameters, find_direction


@pytest.mark.parametrize(
    ("goal", "expected"),
    [
        ((4, 0, 0), (1, 0, 0)),
        ((0, 0, 4), (0, 0, 1)),
        ((0, 0, -4), (0, 0, -1)),
        ((-4, 0, 0), (-1, 0, 0)),
        ((0, 4, 0), (0, 1, 0)),
    ],
)
def test_zero_cone_angle_tracks_axis(goal: tuple, expected: tuple) -> None:
    """Handle positive, negative and vertical axes without an arbitrary pole rule."""
    np.testing.assert_allclose(
        find_direction((0, 0, 0), goal, 1.7, 0), expected, atol=1e-14
    )


def test_rotations_follow_paper_y_sign_and_remain_unit() -> None:
    """A positive final Y rotation points upward before the X rotation."""
    np.testing.assert_allclose(
        find_direction((0, 0, 0), (1, 0, 0), 0, math.pi / 2),
        (0, 0, 1),
        atol=1e-14,
    )
    np.testing.assert_allclose(
        find_direction((0, 0, 0), (1, 0, 0), math.pi / 2, math.pi / 2),
        (0, -1, 0),
        atol=1e-14,
    )
    vector = find_direction((1, 2, 3), (-4, 8, 1), 0.8, 0.3)
    assert np.linalg.norm(vector) == pytest.approx(1)
    with pytest.raises(ValueError, match="distinct"):
        find_direction((0, 0, 0), (0, 0, 0), 0, 0)


def test_angle_lattice_includes_only_reachable_upper_endpoint() -> None:
    """Do not omit a divisible cone boundary or append an off-lattice angle."""
    assert list(sampling.angle_values(30, 5, inclusive=True)) == [
        0,
        5,
        10,
        15,
        20,
        25,
        30,
    ]
    assert list(sampling.angle_values(12, 5, inclusive=True)) == [0, 5, 10]
    assert list(sampling.angle_values(360, 90, inclusive=False)) == [0, 90, 180, 270]


@pytest.mark.parametrize("spacing", [(1.0, 1.0, 1.0), (0.5, 1.3, 2.0)])
def test_optimized_ray_matches_naive_prefixes_on_small_random_maps(
    spacing: tuple,
) -> None:
    """Check numerical equivalence against complete prefixes, not sampled points."""
    rng = np.random.default_rng(2718)
    occupied = rng.random((5, 4, 3)) < 0.2
    grid = OccupancyMap(occupied, (2.0, -3.0, 0.5), spacing)
    free_cells = np.argwhere(~occupied)
    for _ in range(24):
        cell = free_cells[int(rng.integers(len(free_cells)))]
        point = tuple(np.asarray(grid.origin) + (cell + 0.5) * np.asarray(spacing))
        direction = tuple(rng.normal(size=3))
        for step in (0.25, 0.7, 2.0):
            actual = sampling.ray_free_length(
                point, direction, grid, step, Deadline(10), SearchCounters()
            )
            expected = sampling.ray_free_length_reference(
                point, direction, grid, step, Deadline(10), SearchCounters()
            )
            assert actual == pytest.approx(expected, abs=1e-12)


def test_ray_contact_and_closed_map_boundary() -> None:
    """Face contact is occupied while an empty outer boundary is permitted."""
    occupancy = np.zeros((4, 3, 3), dtype=bool)
    occupancy[2, 1, 0] = True
    grid = OccupancyMap(occupancy)
    assert (
        sampling.ray_free_length(
            (0.5, 1.0, 0.5), (1, 0, 0), grid, 0.5, Deadline(10), SearchCounters()
        )
        == 1.0
    )
    assert (
        sampling.ray_free_length(
            (0.5, 0.5, 2.5), (1, 0, 0), grid, 0.5, Deadline(10), SearchCounters()
        )
        == 3.5
    )
    assert not validate_path([(0.5, 1.0, 0.5), (2.0, 1.0, 0.5)], grid).valid


def test_ray_origin_in_obstacle_is_rejected() -> None:
    """An invalid starting point is not a zero-length successful free prefix."""
    grid = OccupancyMap(np.ones((2, 2, 2), dtype=bool))
    for implementation in (
        sampling.ray_free_length,
        sampling.ray_free_length_reference,
    ):
        with pytest.raises(ValueError, match="occupied"):
            implementation(
                (0.5, 0.5, 0.5), (1, 0, 0), grid, 1, Deadline(10), SearchCounters()
            )


def test_sampling_uses_cone_upper_bound_but_skips_phi_zero_candidates(
    monkeypatch,
) -> None:
    """Evaluate both planes but generate tangent events only from positive phi."""
    calls = []
    lengths = iter([1.0, 10.0, 20.0, 1.0, 10.0, 20.0])

    def fake_ray(*args):
        calls.append(args[1])
        return next(lengths)

    monkeypatch.setattr(sampling, "ray_free_length", fake_ray)
    parameters = SamplingParameters(
        theta_step_degrees=10,
        phi_step_degrees=180,
        half_cone_degrees=20,
        length_threshold=8,
    )
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    candidates = list(
        sampling.tangent_candidates(
            (0.5, 0.5, 0.5),
            (2.5, 0.5, 0.5),
            grid,
            parameters,
            Deadline(10),
            SearchCounters(),
        )
    )
    assert len(calls) == 6
    assert len(candidates) == 2


def test_threshold_equality_does_not_generate_tangent(monkeypatch) -> None:
    """Algorithm 3 uses a strict greater-than threshold, unlike author code."""
    lengths = iter([1.0, 9.0, 1.0, 9.0])
    monkeypatch.setattr(sampling, "ray_free_length", lambda *args: next(lengths))
    parameters = SamplingParameters(
        theta_step_degrees=10,
        phi_step_degrees=180,
        half_cone_degrees=10,
        length_threshold=8,
    )
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    assert (
        list(
            sampling.tangent_candidates(
                (0.5, 0.5, 0.5),
                (2.5, 0.5, 0.5),
                grid,
                parameters,
                Deadline(10),
                SearchCounters(),
            )
        )
        == []
    )


def test_planar_algorithm_stays_in_xy_plane(monkeypatch) -> None:
    """The separate algorithm-2 interface samples a full circle at fixed z."""
    lengths = iter([1.0, 10.0, 20.0, 30.0])
    directions = []

    def fake_ray(*args):
        directions.append(args[1])
        return next(lengths)

    monkeypatch.setattr(sampling, "ray_free_length", fake_ray)
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    parameters = SamplingParameters(theta_step_degrees=90, length_threshold=5)
    points = list(
        sampling.planar_tangent_candidates(
            (0.5, 0.5, 0.5), grid, parameters, Deadline(10), SearchCounters()
        )
    )
    assert len(directions) == 4 and len(points) == 3
    assert all(point[2] == 0.5 for point in points)


def test_deadline_is_checked_inside_whole_ray_traversal(monkeypatch) -> None:
    """A long ray traversal must remain interruptible before returning a result."""
    deadline = Deadline(10)
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls > 3:
            raise BudgetExceeded("time_budget")

    monkeypatch.setattr(deadline, "check", check)
    grid = OccupancyMap(np.zeros((40, 3, 3), dtype=bool))
    with pytest.raises(BudgetExceeded, match="time_budget"):
        sampling.ray_free_length(
            (0.5, 0.5, 0.5), (1, 0, 0), grid, 1, deadline, SearchCounters()
        )
    assert calls == 4


@pytest.mark.parametrize(
    "parameters",
    [
        {"distance_step": 0},
        {"half_cone_degrees": 181},
        {"theta_step_degrees": math.nan},
        {"forward_distance": -1},
    ],
)
def test_invalid_sampling_settings_are_explicit(parameters: dict) -> None:
    """Reject malformed settings before beginning a sampling loop."""
    with pytest.raises(ValueError):
        SamplingParameters(**parameters)
