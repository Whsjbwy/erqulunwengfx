"""Finite-endpoint direction, latch and identical preterminal evaluation."""

import json

import pytest

from gsunlight_repro.stage5a.maps import read_config
from gsunlight_repro.stage5a.tracking import Route
from gsunlight_repro.stage5af.guidance import TerminalLOS
from gsunlight_repro.stage5af.tracking import simulate
from gsunlight_repro.stage5af.verification import acceptance, command_cases
from gsunlight_repro.stage5ar.p0 import empty_scene


def test_terminal_direction_and_folded_route_are_explicit() -> None:
    rows = command_cases()
    assert rows[0]["old_dot"] < 0 < rows[0]["corrected_dot"]
    assert len(rows) == 7


def test_analytic_safety_and_frozen_adapter_acceptance() -> None:
    result = acceptance()
    assert result["passed"] and result["maximum_rk4_error_m"] < 1e-10


def test_terminal_distance_rejects_invalid_values() -> None:
    route = Route([(0, 0, 0), (10, 0, 0)])
    for value in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            TerminalLOS(route, 2.0, value)


def test_complete_terminal_trace_is_json_serializable() -> None:
    scene = empty_scene()
    result = simulate(
        [scene.start, scene.goal],
        scene,
        read_config("stage5a_protocol.json"),
        0.0,
        read_config("stage5af_protocol.json"),
    )
    json.dumps({"summary": result.summary, "trace": result.trace}, allow_nan=False)
