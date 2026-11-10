"""Continuous geometry checks, including an independent slab intersection oracle."""

from itertools import product

import numpy as np
import pytest

from gsunlight_repro.collision_checker import trace_voxel_segment, validate_path
from gsunlight_repro.map_reader import OccupancyMap


def make_grid(*occupied: tuple[int, int, int]) -> OccupancyMap:
    """Build a small synthetic map without using author materials."""
    values = np.zeros((4, 4, 4), dtype=bool)
    for voxel in occupied:
        values[voxel] = True
    return OccupancyMap(values)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ((0, 0, 0), (4, 4, 4)),
        ((0.2, 0.3, 0.4), (3.8, 2.7, 1.6)),
        ((0, 2, 2), (4, 2, 2)),
        ((4, 4, 4), (4, 4, 4)),
    ],
)
def test_empty_map_accepts_segments(start: tuple, end: tuple) -> None:
    result = validate_path([start, end], make_grid())
    assert result.valid
    assert result.reason == "ok"
    assert result.checked_segments == 1
    assert result.collision_segment_count == 0


def test_single_voxel_collision_has_physical_evidence() -> None:
    result = validate_path([(0.2, 1.5, 1.5), (3.8, 1.5, 1.5)], make_grid((1, 1, 1)))
    assert not result.valid
    assert result.reason == "collision"
    assert result.first_collision_segment == 0
    assert result.first_collision_voxel == (1, 1, 1)
    assert result.first_collision_point == pytest.approx((1, 1.5, 1.5))


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ((0.2, 1, 1.5), (3.8, 1, 1.5)),  # travels on an occupied face
        ((0.2, 1, 1), (3.8, 1, 1)),  # travels on an occupied edge
        ((0, 2, 1), (2, 0, 1)),  # touches only the corner (1, 1, 1)
        ((0.2, 0.2, 0.2), (1, 1, 1)),  # endpoint is an occupied corner
        ((1, 1, 1), (0.2, 0.2, 0.2)),
        ((1.5, 1.5, 1.5), (1.5, 1.5, 1.5)),
        ((1, 1, 1), (1, 1, 1)),
    ],
)
def test_face_edge_corner_and_zero_length_contacts_collide(
    start: tuple, end: tuple
) -> None:
    result = validate_path([start, end], make_grid((1, 1, 1)))
    assert not result.valid
    assert result.first_collision_voxel == (1, 1, 1)


@pytest.mark.parametrize("reverse", [False, True])
def test_obstacle_endpoint_is_checked(reverse: bool) -> None:
    points = [(0.2, 0.2, 0.2), (1.5, 1.5, 1.5)]
    if reverse:
        points.reverse()
    assert not validate_path(points, make_grid((1, 1, 1))).valid


@pytest.mark.parametrize(
    "point", [(-0.01, 1, 1), (4.01, 1, 1), (1, -0.01, 1), (1, 1, 4.01)]
)
def test_outside_domain_is_invalid(point: tuple) -> None:
    result = validate_path([(0.5, 0.5, 0.5), point], make_grid())
    assert result.reason == "out_of_bounds"
    assert result.collision_segment_count == 1
    assert result.first_collision_voxel is None
    with pytest.raises(ValueError, match="outside"):
        list(trace_voxel_segment((0.5, 0.5, 0.5), point, make_grid()))


@pytest.mark.parametrize(
    "points",
    [[], [(1, 1, 1)], [(0, 0), (1, 1)], [(0, 0, 0), (np.nan, 1, 1)], [None]],
)
def test_malformed_paths_have_explicit_status(points: list) -> None:
    result = validate_path(points, make_grid())
    assert result.reason == "invalid_path"
    assert not result.valid
    assert result.checked_segments == 0


def test_all_invalid_segments_are_counted_once() -> None:
    path = [(0.2, 1.5, 1.5), (2.5, 1.5, 1.5), (0.2, 1.5, 1.5), (-1, 1, 1)]
    result = validate_path(path, make_grid((1, 1, 1), (2, 1, 1)))
    assert result.collision_segment_count == 3
    assert result.checked_segments == 3
    assert result.first_collision_segment == 0


def test_supercover_includes_all_cells_at_simultaneous_corner_crossing() -> None:
    visits = list(trace_voxel_segment((0.5, 0.5, 0.5), (2.5, 2.5, 2.5), make_grid()))
    visited = {visit.voxel for visit in visits}
    assert set(product((0, 1), repeat=3)) <= visited
    assert set(product((1, 2), repeat=3)) <= visited
    assert len(visits) == len(visited)
    assert [visit.parameter for visit in visits] == sorted(
        visit.parameter for visit in visits
    )


def test_anisotropic_spacing_and_shifted_origin() -> None:
    grid = OccupancyMap(make_grid((1, 1, 1)).occupancy, (10, -20, 3), (2, 3, 4))
    result = validate_path([(10.4, -15.5, 9), (17.6, -15.5, 9)], grid)
    assert result.first_collision_voxel == (1, 1, 1)
    assert result.first_collision_point == pytest.approx((12, -15.5, 9))
    assert grid.bounds == (10, 18, -20, -8, 3, 19)


def test_plane_tolerance_is_conservative_and_explicit() -> None:
    grid = make_grid((1, 1, 1))
    close = [(0.2, 1 - 1e-11, 1.5), (3.8, 1 - 1e-11, 1.5)]
    separated = [(0.2, 1 - 1e-7, 1.5), (3.8, 1 - 1e-7, 1.5)]
    assert not validate_path(close, grid).valid
    assert validate_path(separated, grid).valid


def slab_intersects(start: np.ndarray, end: np.ndarray, voxel: tuple) -> bool:
    """Independently intersect a segment with one closed box via slabs."""
    entering, leaving = 0.0, 1.0
    lower = np.asarray(voxel, dtype=float)
    upper = lower + 1
    direction = end - start
    for axis in range(3):
        if direction[axis] == 0:
            if not lower[axis] <= start[axis] <= upper[axis]:
                return False
            continue
        first = (lower[axis] - start[axis]) / direction[axis]
        second = (upper[axis] - start[axis]) / direction[axis]
        entering = max(entering, min(first, second))
        leaving = min(leaving, max(first, second))
        if entering > leaving:
            return False
    return True


def test_supercover_matches_independent_slab_oracle_and_reversal() -> None:
    rng = np.random.default_rng(20261110)
    grid = OccupancyMap(rng.random((4, 4, 4)) < 0.2)
    # The test seed controls synthetic fixtures only, not research experiments.
    for _ in range(150):
        start, end = rng.uniform(0, 4, size=(2, 3))
        expected = not any(
            slab_intersects(start, end, tuple(voxel))
            for voxel in np.argwhere(grid.occupancy)
        )
        assert validate_path([start, end], grid).valid == expected
        assert validate_path([end, start], grid).valid == expected


def test_small_diagonal_crossing_cannot_skip_thin_occupied_cell() -> None:
    result = validate_path([(0.99, 1.5, 1.5), (1.01, 1.5, 1.5)], make_grid((1, 1, 1)))
    assert not result.valid
