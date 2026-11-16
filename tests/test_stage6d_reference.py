"""Acceptance for one-factor reference interventions and frozen-loop reuse."""

from __future__ import annotations

import numpy as np
import pytest
from test_stage6c_reference import scenario

from gsunlight_repro.stage5a.maps import read_config
from gsunlight_repro.stage5a.tracking import Route, State
from gsunlight_repro.stage5af import tracking
from gsunlight_repro.stage5af.guidance import TerminalLOS
from gsunlight_repro.stage6c.reference import certify_reference, tail_reference
from gsunlight_repro.stage6d.reference import (
    ArcTerminalLOS,
    geometry_equivalence,
    guidance_factory,
    subdivide,
)


def test_same_geometry_three_different_thresholds() -> None:
    path = [(2.0, 5.0, 5.0), (11.5, 5.0, 5.0), (12.0, 5.0, 5.0)]
    b = subdivide(path)
    assert geometry_equivalence(path, b)["geometry_equivalent"]
    assert TerminalLOS(Route(path), 2, 2).switch_progress == 9.5
    assert TerminalLOS(Route(b), 2, 2).switch_progress == 9.75
    assert ArcTerminalLOS(Route(path), 2, 2).switch_progress == 8.0
    state = State((10.1, 5, 5), 0, 0, 1)
    frozen, changed = TerminalLOS(Route(path), 2, 2), ArcTerminalLOS(Route(path), 2, 2)
    frozen.base.progress = changed.base.progress = 8.1
    assert not frozen.command(state, 0.1)[1]["terminal_mode"]
    assert changed.command(state, 0.1)[1]["terminal_mode"]


def test_subdivision_keeps_corner_and_full_safety_certificate() -> None:
    path = [(8.7, 10.0, 10.25), (8.7, 8.7, 10.25), (10.0, 8.7, 10.25)]
    case = scenario(path, obstacle=True)
    divided = subdivide(path)
    assert divided[::2] == path
    assert geometry_equivalence(path, divided)["arc_length_difference_m"] < 1e-9
    assert certify_reference(path, case)["reference_geometry_safe"]
    assert certify_reference(divided, case)["reference_geometry_safe"]
    assert not certify_reference(tail_reference(path), case)["reference_geometry_safe"]


def test_noncollinear_or_reordered_vertices_fail_equivalence() -> None:
    path = [(2.0, 5.0, 5.0), (4.0, 6.0, 5.0), (6.0, 5.0, 5.0)]
    divided = subdivide(path)
    divided[1] = (3, 5, 5)
    with pytest.raises(ValueError, match="geometric equivalence"):
        geometry_equivalence(path, divided)
    with pytest.raises(ValueError):
        geometry_equivalence(path, list(reversed(divided)))


def test_factory_is_restored_on_exception_and_rejects_nested_changes() -> None:
    with pytest.raises(RuntimeError, match="deliberate"):
        with guidance_factory(True):
            assert tracking.TerminalLOS is ArcTerminalLOS
            with pytest.raises(RuntimeError, match="Concurrent"):
                with guidance_factory(True):
                    pass
            raise RuntimeError("deliberate")
    assert tracking.TerminalLOS is TerminalLOS


def test_same_threshold_gives_identical_real_frozen_execution() -> None:
    path = [(3.0, 5.0, 5.0), (13.0, 5.0, 5.0)]
    case = scenario(path)
    vehicle, settings = (
        read_config("stage5a_protocol.json"),
        read_config("stage5af_protocol.json"),
    )
    original = tracking.simulate(
        path, case.scene, vehicle, 0.25, settings, initial=case.initial
    )
    with guidance_factory(True):
        changed = tracking.simulate(
            path, case.scene, vehicle, 0.25, settings, initial=case.initial
        )
    assert original.trace == changed.trace
    assert original.summary["execution_success"] == changed.summary["execution_success"]
    assert original.summary["execution_success"]
    assert tracking.TerminalLOS is TerminalLOS


@pytest.mark.parametrize("distance", [0, -1, np.nan, np.inf])
def test_arc_variant_keeps_frozen_input_rejection(distance: float) -> None:
    with pytest.raises(ValueError):
        ArcTerminalLOS(Route([(3, 5, 5), (13, 5, 5)]), 2, distance)
