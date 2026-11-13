"""Desired endpoint direction does not imply immediate actual distance decrease."""

import math

import pytest

from gsunlight_repro.stage5af.diagnostics import goal_alignment


def test_actual_overshoot_velocity_and_turn_alignment_are_distinguished() -> None:
    event = {"start_position": [11, 0, 0], "start_yaw_rad": 0, "start_pitch_rad": 0}
    behind = goal_alignment(event, [10, 0, 0])
    assert behind["actual_velocity_goal_cosine"] == -1
    assert behind["yaw_bearing_error_deg"] == 180
    event["start_yaw_rad"] = math.pi
    facing = goal_alignment(event, [10, 0, 0])
    assert facing["actual_velocity_goal_cosine"] == 1
    assert facing["yaw_bearing_error_deg"] == 0
    event["start_pitch_rad"] = math.pi / 6
    climbing = goal_alignment(event, [10, 0, 1 / math.sqrt(3)])
    assert climbing["actual_velocity_goal_cosine"] == pytest.approx(1)
    assert climbing["pitch_bearing_error_deg"] == pytest.approx(0, abs=1e-12)
