"""Prevent goal, state, safety and reference contracts from silently changing."""

import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from gsunlight_repro.stage5a.geometry import Geometry
from gsunlight_repro.stage5a.tracking import State
from gsunlight_repro.stage5ar.replay import Replay
from gsunlight_repro.stage6b import replay
from gsunlight_repro.stage6b.replay import audit_controls, track_reference
from gsunlight_repro.stage6b.scenarios import (
    analytic_scenarios,
    effective_radius,
    export_scenario,
    mid_segment_scenario,
    state_values,
)


def test_export_preserves_c_order_and_reuses_the_same_empty_grid(
    tmp_path: Path,
) -> None:
    scenarios = {item.id: item for item in analytic_scenarios()}
    first = export_scenario(scenarios["straight"], tmp_path)
    second = export_scenario(scenarios["left_arc"], tmp_path)
    assert first["physical"]["data_file"] == second["physical"]["data_file"]
    item = export_scenario(scenarios["obstacle_reject"], tmp_path)
    shape = item["physical"]["shape"]
    values = np.fromfile(item["physical"]["data_file"], dtype=np.uint8)
    assert values[(60 * shape[1] + 35) * shape[2] + 26] == 1
    assert values[(59 * shape[1] + 35) * shape[2] + 26] == 0
    assert len(list(tmp_path.glob("*.u8"))) == 2


def test_quarter_arc_keeps_registered_initial_heading_and_target() -> None:
    scenario = next(item for item in analytic_scenarios() if item.id == "left_arc")
    radius = 1 / math.radians(10)
    assert scenario.scene.goal == pytest.approx((20 + radius, 20 + radius, 15))
    assert scenario.initial.yaw == 0
    assert math.atan2(
        scenario.scene.goal[1] - 20, scenario.scene.goal[0] - 20
    ) == pytest.approx(math.pi / 4)


def test_mid_segment_counterexample_has_two_free_endpoints() -> None:
    scenario = mid_segment_scenario()
    geometry = Geometry(scenario.scene.grid, effective_radius())
    assert geometry.segment(scenario.scene.start, scenario.scene.start).valid
    assert geometry.segment(scenario.scene.goal, scenario.scene.goal).valid
    middle = tuple(
        (a + b) / 2
        for a, b in zip(scenario.scene.start, scenario.scene.goal, strict=True)
    )
    assert not geometry.segment(middle, middle).valid
    assert (
        geometry.segment(scenario.scene.start, scenario.scene.goal).reason
        == "physical_obstacle"
    )


def _quarter_payload(status: str = "exact") -> tuple:
    scenario = next(item for item in analytic_scenarios() if item.id == "left_arc")
    radius = 1 / math.radians(10)
    endpoint = [20 + radius, 20 + radius, 15, math.pi / 2, 0, 1]
    return scenario, {
        "status": status,
        "states": [state_values(scenario.initial), endpoint],
        "controls": [dict(scenario.witness_controls[0])],
    }


def test_exact_control_path_is_reintegrated_and_corrupt_nodes_are_rejected() -> None:
    scenario, payload = _quarter_payload()
    summary, trace = audit_controls(scenario, payload)
    assert summary["independent_audit_passed"] and summary["model_feasible"]
    assert len(trace) == 90
    assert summary["maximum_rk4_error_m"] < 1e-10
    payload["states"][-1][4] = 0.001
    corrupted, _ = audit_controls(scenario, payload)
    assert not corrupted["independent_audit_passed"]
    assert not corrupted["model_feasible"]
    assert corrupted["reason"] == "native_state_mismatch"


def test_approximate_status_is_not_upgraded_when_it_enters_the_goal_ball() -> None:
    scenario, payload = _quarter_payload("approximate")
    summary, _ = audit_controls(scenario, payload)
    assert summary["independent_audit_passed"] and summary["goal_reached"]
    assert not summary["model_feasible"]
    assert summary["reason"] == "approximate_not_strict"


def test_invalid_duration_is_not_rounded_into_a_valid_control() -> None:
    scenario, payload = _quarter_payload()
    payload["controls"][0]["duration_s"] = 0.15
    with pytest.raises(ValueError, match="whole0.1s"):
        audit_controls(scenario, payload)


def test_unsafe_goal_bridge_does_not_change_the_task_or_invoke_los(monkeypatch) -> None:
    scenario = mid_segment_scenario()
    # An initial state already inside the goal ball is valid without moving.
    # The bridge still must be safe; it is not part of the native ODE trajectory.
    scenario = replace(scenario, witness_controls=())
    goal_before = scenario.scene.goal

    def unexpected_tracker(*args, **kwargs):
        raise AssertionError("LOS must not run for an uncertified reference bridge")

    monkeypatch.setattr(replay, "simulate", unexpected_tracker)
    summary, trace = track_reference(scenario, {"model_feasible": True}, [])
    assert not summary["was_run"] and not trace
    assert (
        summary["failure_reason"]
        == "interface_rejected_reference_bridge_physical_obstacle"
    )
    assert scenario.scene.goal == goal_before


def test_los_receives_native_initial_state_and_true_goal(monkeypatch) -> None:
    scenario, payload = _quarter_payload()
    audit, trace = audit_controls(scenario, payload)
    seen = {}

    def capture_tracker(path, scene, vehicle, margin, settings, **kwargs):
        seen.update(path=path, initial=kwargs["initial"], margin=margin)
        assert path[-1] == scene.goal
        return Replay({"execution_success": True, "eligible": True}, [])

    monkeypatch.setattr(replay, "simulate", capture_tracker)
    summary, _ = track_reference(scenario, audit, trace)
    assert seen["initial"] == State((20, 20, 15), 0, 0, 1)
    assert seen["margin"] == 0.25
    assert summary["reference_bridge_is_native_control"] is False
    assert summary["was_run"]
