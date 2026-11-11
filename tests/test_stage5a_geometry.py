"""Analytical contacts and independent finite-radius continuous oracles."""

import math

import numpy as np
import pytest

from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.stage5a.geometry import (
    Geometry,
    reference_distance,
    segment_box_distances,
)


def box_grid() -> OccupancyMap:
    """One closed unit obstacle with room for swept-body queries."""
    values = np.zeros((10, 10, 10), dtype=bool)
    values[4, 4, 4] = True
    return OccupancyMap(values)


@pytest.mark.parametrize("kind", ["face", "edge", "corner"])
def test_exact_tangent_contacts_and_nearby_free_paths(kind: str) -> None:
    start, end, radius = {
        "face": ((2, 3, 4.5), (7, 3, 4.5), 1),
        "edge": ((2, 3, 3), (7, 3, 3), math.sqrt(2)),
        "corner": ((3, 3, 3), (3, 3, 3), math.sqrt(3)),
    }[kind]
    assert not Geometry(box_grid(), radius).segment(start, end).valid
    assert Geometry(box_grid(), radius - 1e-6).segment(start, end).valid


def test_rounded_minkowski_corner_does_not_use_box_inflation_as_truth() -> None:
    grid = box_grid()
    assert Geometry(grid, 1).segment((3.2, 3.2, 4.5), (3.2, 3.2, 4.5)).valid
    assert not Geometry(grid, 1.2).segment((3.2, 3.2, 4.5), (3.2, 3.2, 4.5)).valid


def test_body_boundary_and_margin_are_distinct() -> None:
    grid = OccupancyMap(np.zeros((10, 10, 10), dtype=bool))
    assert Geometry(grid, 1).segment((1, 1, 1), (9, 9, 9)).valid
    assert not Geometry(grid, 1.01).segment((1, 1, 1), (9, 9, 9)).valid
    assert Geometry(grid, 0).segment((0, 0, 0), (10, 10, 10)).valid
    assert not Geometry(grid, 0).segment((-0.001, 1, 1), (9, 1, 1)).valid


@pytest.mark.parametrize("radius", [-1, float("nan"), float("inf")])
def test_invalid_radius_rejected(radius: float) -> None:
    with pytest.raises(ValueError):
        Geometry(box_grid(), radius)


@pytest.mark.parametrize(
    "path",
    [
        None,
        [],
        [[1, 1, 1]],
        [[1, 1], [2, 2]],
        [[1, 1, 1], [2, np.nan, 2]],
        [["bad", 1, 1], [2, 2, 2]],
    ],
)
def test_malformed_paths_have_no_validity_claim(path: object) -> None:
    assert not Geometry(box_grid(), 0.2).path(path).valid


def test_segment_minima_match_independent_lipschitz_bounded_reference() -> None:
    rng = np.random.default_rng(5501)
    for _ in range(90):
        a, b = rng.uniform(-3, 5, (2, 3))
        lower = rng.uniform(-2, 2, (3, 3))
        upper = lower + rng.uniform(0.2, 2, (3, 3))
        actual = segment_box_distances(a, b, lower, upper)
        reverse = segment_box_distances(b, a, lower, upper)
        expected = [
            reference_distance(a, b, lo, hi)
            for lo, hi in zip(lower, upper, strict=True)
        ]
        assert actual == pytest.approx(expected, abs=2e-10)
        assert reverse == pytest.approx(actual, abs=2e-12)


def test_nonunit_spacing_broad_phase_matches_exhaustive_box_reference() -> None:
    rng = np.random.default_rng(5502)
    values = rng.random((5, 5, 5)) < 0.1
    grid = OccupancyMap(values, (-1, 2, 3), (0.5, 1.5, 2))
    indices = np.argwhere(values)
    lower = np.asarray(grid.origin) + indices * grid.spacing
    upper = lower + grid.spacing
    for _ in range(25):
        a, b = np.asarray(grid.origin) + rng.uniform(0.4, 4.6, (2, 3)) * grid.spacing
        radius = float(rng.choice([0, 0.1, 0.19]))
        expected = all(
            reference_distance(a, b, lo, hi) > radius + 1e-9
            for lo, hi in zip(lower, upper, strict=True)
        )
        assert Geometry(grid, radius).segment(a, b).valid == expected


def test_zero_radius_matches_legacy_oracle_on_random_interior_segments() -> None:
    rng = np.random.default_rng(5503)
    grid = OccupancyMap(rng.random((8, 7, 6)) < 0.08)
    checker = Geometry(grid, 0)
    for _ in range(80):
        path = rng.uniform(0.1, np.asarray(grid.shape) - 0.1, (2, 3))
        assert checker.path(path).valid == validate_path(path, grid).valid


def test_ceiling_is_not_labelled_as_physical_collision() -> None:
    physical = OccupancyMap(np.zeros((10, 10, 10), dtype=bool))
    ceiling = physical.occupancy.copy()
    ceiling[:, :, 7:] = True
    oracle = Geometry(physical, 1, OccupancyMap(ceiling))
    assert oracle.segment((3, 3, 6), (5, 3, 6)).reason == "mission_ceiling"
    assert oracle.segment((3, 3, 5), (5, 3, 5)).valid
    assert oracle.clearance((3, 3, 6), (5, 3, 6), mission=False) > 0


def test_long_segment_cannot_skip_single_voxel_and_curved_margin() -> None:
    oracle = Geometry(box_grid(), 0.1)
    assert not oracle.segment((1, 4.5, 4.5), (9, 4.5, 4.5)).valid
    assert oracle.segment((2, 3.89, 4.5), (7, 3.89, 4.5)).valid
    assert not oracle.segment((2, 3.89, 4.5), (7, 3.89, 4.5), extra_radius=0.02).valid


def test_truncated_clearance_is_labelled_and_respects_margin() -> None:
    grid = OccupancyMap(np.zeros((20, 20, 20), dtype=bool))
    oracle = Geometry(grid, 1)
    assert oracle.clearance((10, 10, 10), (11, 10, 10)) == 3
    assert oracle.clearance((1.2, 2, 2), (2, 2, 2)) == pytest.approx(0.2)
    with pytest.raises(ValueError):
        oracle.clearance((1, 1, 1), (2, 2, 2), cap=0)
