"""Verify exact algorithm-5 membership, tail removal and historical costs."""

import math

import pytest

from gsunlight_repro.grid_candidates import CandidateNode, GridCandidates


def node(node_id: int, cost: float, point: tuple = (1.0, 1.0, 1.0)) -> CandidateNode:
    """Build a synthetic immutable candidate for one capacity cell."""
    return CandidateNode(node_id, point, cost, None)


def test_index_one_insertion_and_tail_eviction() -> None:
    """New nonbest nodes displace the tail, rather than append or delete randomly."""
    candidates = GridCandidates((0, 0, 0), 10, 3)
    for index, cost in enumerate([10, 20, 30]):
        assert candidates.insert(node(index, cost)) is None
    assert candidates.members((1, 1, 1)) == (0, 2, 1)
    assert candidates.insert(node(3, 40)) == 1
    assert candidates.members((1, 1, 1)) == (0, 3, 2)
    assert candidates.insert(node(4, 5)) == 2
    assert candidates.members((1, 1, 1)) == (4, 0, 3)
    assert candidates.historical_best((1, 1, 1)) == 5


def test_history_survives_best_node_removal() -> None:
    """Compare with historical cost even when the best point is no longer open."""
    candidates = GridCandidates((0, 0, 0), 10, 3)
    candidates.insert(node(0, 5))
    candidates.insert(node(1, 10))
    candidates.remove(0)
    candidates.insert(node(2, 6))
    assert candidates.members((1, 1, 1)) == (1, 2)
    assert candidates.historical_best((1, 1, 1)) == 5
    assert [value.node_id for value in candidates.ordered()] == [2, 1]
    candidates.remove(1)
    candidates.remove(2)
    assert len(candidates) == 0
    assert candidates.historical_best((1, 1, 1)) == 5
    candidates.insert(node(3, 7))
    assert candidates.members((1, 1, 1)) == (3,)


def test_equal_cost_does_not_replace_best_at_capacity_one() -> None:
    """The paper's strict less-than rule can evict a newly inserted tied point."""
    candidates = GridCandidates((0, 0, 0), 10, 1)
    candidates.insert(node(0, 5))
    assert candidates.insert(node(1, 5)) == 1
    assert candidates.members((1, 1, 1)) == (0,)
    with pytest.raises(KeyError):
        candidates.remove(1)


def test_capacity_cells_use_physical_origin_and_independent_membership() -> None:
    """Capacity cells are not assumed to be unit-spaced occupancy indices."""
    candidates = GridCandidates((10, -5, 2), 2, 1)
    assert candidates.cell_key((12, -3, 4)) == (1, 1, 1)
    assert candidates.cell_key((9.5, -5, 2)) == (-1, 0, 0)
    candidates.insert(node(2, 3, (12, -3, 4)))
    candidates.insert(node(1, 3, (10, -5, 2)))
    assert [value.node_id for value in candidates.ordered()] == [1, 2]


@pytest.mark.parametrize(
    ("side", "capacity"), [(0, 1), (math.inf, 1), (1, 0), (1, True)]
)
def test_invalid_grid_parameters_are_rejected(side: float, capacity: int) -> None:
    """Reject nonphysical cells and invalid capacity values."""
    with pytest.raises(ValueError):
        GridCandidates((0, 0, 0), side, capacity)


def test_duplicate_open_ids_and_nonfinite_cost_raise() -> None:
    """Corrupt state must not be silently accepted by candidate bookkeeping."""
    candidates = GridCandidates((0, 0, 0), 10, 3)
    candidates.insert(node(0, 1))
    with pytest.raises(ValueError, match="already"):
        candidates.insert(node(0, 2))
    with pytest.raises(ValueError, match="finite"):
        candidates.insert(node(1, math.nan))
