"""Analytical and real-oracle acceptance before fixed-trajectory replay."""

from __future__ import annotations

import math

import numpy as np
import pytest

from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.stage5a.maps import Scene
from gsunlight_repro.stage5a.tracking import Route, State
from gsunlight_repro.stage5af.guidance import TerminalLOS
from gsunlight_repro.stage6b.scenarios import Scenario
from gsunlight_repro.stage6c.common import boolean
from gsunlight_repro.stage6c.reference import certify_reference, tail_reference


def scenario(
    path: list[tuple[float, float, float]], obstacle: bool = False
) -> Scenario:
    """Create a geometric test scene, not a supplied AUV control witness."""
    values = np.zeros((40, 40, 40), dtype=bool)
    if obstacle:
        values[20, 20, 20] = True
    scene = Scene(
        {"id": "reference_test"},
        OccupancyMap(values, spacing=(0.5,) * 3),
        None,
        path[0],
        path[-1],
        None,
    )
    return Scenario(
        "reference_test",
        scene,
        State(path[0], 0, 0, 1),
        (),
        "ok",
        "geometric_test_not_control_witness",
        "reference_test",
    )


def test_collinear_representation_moves_terminal_threshold() -> None:
    """Same straight geometry has different frozen terminal latching thresholds."""
    dense = [(2 + float(x), 5.0, 5.0) for x in np.arange(0, 9.51, 0.1)]
    dense.append((12.0, 5.0, 5.0))
    adapted = tail_reference(dense)
    old = TerminalLOS(Route(dense), 2.0, 2.0)
    new = TerminalLOS(Route(adapted), 2.0, 2.0)
    assert old.switch_progress == pytest.approx(9.5)
    assert new.switch_progress == pytest.approx(8.0)
    assert Route(adapted).cumulative[-1] == pytest.approx(10.0)
    old.base.progress = new.base.progress = 8.1
    state = State((10.1, 5.0, 5.0), 0, 0, 1)
    assert not old.command(state, 0.1)[1]["terminal_mode"]
    assert new.command(state, 0.1)[1]["terminal_mode"]


def test_only_terminal_original_arc_is_resampled() -> None:
    path = [(5.0, 5.0, 5.0), (8.0, 5.0, 5.0), (9.0, 6.0, 5.0), (10.0, 6.0, 5.0)]
    old = Route(path)
    new = tail_reference(path)
    anchor = old.target(old.cumulative[-1] - 2.0)
    assert new[:2] == path[:2]
    assert new[-2] == pytest.approx(anchor)
    assert new[-1] == path[-1]
    assert Route(new).cumulative[-1] < old.cumulative[-1]


def test_short_duplicate_reference_preserves_endpoints() -> None:
    path = [(5.0, 5.0, 5.0), (5.0, 5.0, 5.0), (6.0, 5.0, 5.0)]
    assert tail_reference(path) == [path[0], path[-1]]


def test_geometric_tail_cut_is_rejected_without_fallback() -> None:
    path = [(8.7, 10.0, 10.25), (8.7, 8.7, 10.25), (10.0, 8.7, 10.25)]
    case = scenario(path, obstacle=True)
    assert certify_reference(path, case)["reference_geometry_safe"]
    verdict = certify_reference(tail_reference(path), case)
    assert not verdict["reference_geometry_safe"]
    assert verdict["reference_rejection"] == "physical_obstacle"


@pytest.mark.parametrize("window", [0, -1, math.nan, math.inf])
def test_invalid_tail_window_is_rejected(window: float) -> None:
    with pytest.raises(ValueError):
        tail_reference([(5, 5, 5), (6, 5, 5)], window)


@pytest.mark.parametrize(
    "path", [[], [(1, 2, 3)], [(1, 2), (3, 4)], [(1, 2, 3), (math.nan, 2, 3)]]
)
def test_malformed_reference_is_rejected(path: list) -> None:
    with pytest.raises(ValueError):
        tail_reference(path)


def test_missing_boolean_never_becomes_false_or_zero() -> None:
    with pytest.raises(ValueError):
        boolean("")
