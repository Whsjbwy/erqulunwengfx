"""Synthetic unit records test audit semantics, never scientific performance."""

import math

import pytest

from gsunlight_repro.stage7a.audit import (
    ABSENT,
    UNKNOWN,
    describe,
    event_time,
    first_event,
    reference,
    saturation,
    time_aligned_errors,
)


def test_margin_loss_precedes_physical_termination() -> None:
    trace = [
        {"time_s": 0.1, "margin_reason": "physical_obstacle", "physical_reason": "ok"},
        {
            "time_s": 0.2,
            "margin_reason": "physical_obstacle",
            "physical_reason": "physical_obstacle",
        },
    ]
    assert first_event(trace, "margin") == 0
    assert first_event(trace, "physical") == 1
    assert event_time(trace, 0) == 0.1 and event_time(trace, 1) == 0.2


def test_missing_and_observed_absence_are_different() -> None:
    assert first_event([], "terminal") == UNKNOWN
    assert first_event([{"time_s": 0.1}], "terminal") == UNKNOWN
    assert first_event([{"terminal_switch": False}], "terminal") == ABSENT
    assert saturation([{"yaw_saturated": False}], "yaw") == 0
    assert saturation([{}], "yaw") == UNKNOWN


def test_bridge_geometry_does_not_synthesize_a_control() -> None:
    data = {"scenario": {"initial": [0, 0, 0, 0, 0, 1], "goal": [1, 1, 0]}}
    result = reference(data, [{"position": [1, 0, 0]}])
    assert result["bridge_length_m"] == 1
    assert result["bridge_join_tangent_angle_deg"] == 90
    assert result["bridge_segment_index"] == 1
    assert "controls" not in result


def test_time_comparison_stops_at_saved_native_horizon() -> None:
    native = [{"time_s": 0.1, "position": [1, 0, 0]}]
    los = [
        {"time_s": 0.1, "position": [1, 1, 0]},
        {"time_s": 0.2, "position": [20, 20, 20]},
    ]
    result = time_aligned_errors(native, los)
    assert result["time_aligned_samples"] == 1
    assert result["max_time_aligned_position_error_m"] == 1


def test_inconsistent_saved_time_grid_is_rejected() -> None:
    with pytest.raises(ValueError, match="clocks"):
        time_aligned_errors(
            [{"time_s": 0.1, "position": [1, 0, 0]}],
            [{"time_s": 0.2, "position": [1, 0, 0]}],
        )


def test_tracking_event_uses_strict_declared_threshold() -> None:
    assert first_event([{"cross_track_m": 3}], "tracking") == ABSENT
    assert (
        first_event([{"cross_track_m": math.nextafter(3, math.inf)}], "tracking") == 0
    )
    assert first_event([{"goal_distance_after_m": 0.75}], "goal") == 0
    assert first_event([{"goal_distance_after_m": 0.75001}], "goal") == ABSENT


def test_success_has_no_failure_even_when_guide_enters_bridge() -> None:
    source = {
        "scenario": "unit_only",
        "condition": "unit_only",
        "native_seed": "1",
        "los_strict_success": "True",
        "los_failure_reason": "goal_reached",
    }
    input_data = {"scenario": {"initial": [0, 0, 0, 0, 0, 1], "goal": [2, 0, 0]}}
    sample = {
        "time_start_s": 0,
        "time_s": 0.1,
        "start_position": [0, 0, 0],
        "position": [1, 0, 0],
        "pitch_rad": 0,
        "reference_progress_m": 1,
        "active_segment": 1,
        "terminal_mode": True,
        "terminal_switch": True,
        "physical_reason": "ok",
        "mission_reason": "ok",
        "margin_reason": "ok",
        "cross_track_m": 0,
    }
    record = {
        "native_trace": [dict(sample)],
        "los_trace": [dict(sample)],
        "audit": {"model_feasible": True},
        "tracking": {
            "steps": 1,
            "failure_reason": "goal_reached",
            "reference_bridge_length_m": 1,
        },
    }
    result, _ = describe("unit_only", source, input_data, record, 0.25)
    assert result["guide_reached_bridge"] is True
    assert result["earliest_strict_failure_kind"] == ABSENT
    assert result["first_failure_before_guide_bridge"] == ABSENT
