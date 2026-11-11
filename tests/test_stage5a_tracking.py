"""Kinematic integration, curve coverage and the geometry/execution distinction."""

import math

import numpy as np
import pytest

from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.stage5a.maps import Scene, load_scene, read_config
from gsunlight_repro.stage5a.tracking import (
    State,
    chord_error_bound,
    integrate,
    track,
    wrap,
)


def test_constant_turn_has_exact_circular_solution() -> None:
    state = State((0, 0, 0), 0, 0, 1)
    end = integrate(state, 0.2, 0, math.pi / 0.2)
    assert end.position == pytest.approx((0, 10, 0), abs=1e-12)
    assert wrap(2 * math.pi + 0.1) == pytest.approx(0.1)


@pytest.mark.parametrize(
    "yaw_rate,pitch_rate", [(0, 0), (0.1, 0), (0, -0.08), (0.17, 0.08), (-0.17, -0.08)]
)
def test_exact_integration_and_chord_enclosure(
    yaw_rate: float, pitch_rate: float
) -> None:
    start = State((3, 4, 5), 0.4, -0.1, 1.2)
    step = 0.3
    end = integrate(start, yaw_rate, pitch_rate, step)
    t = np.linspace(0, step, 20001)
    velocity = (
        start.speed
        * np.array(
            [
                np.cos(start.pitch + pitch_rate * t) * np.cos(start.yaw + yaw_rate * t),
                np.cos(start.pitch + pitch_rate * t) * np.sin(start.yaw + yaw_rate * t),
                np.sin(start.pitch + pitch_rate * t),
            ]
        ).T
    )
    reference = np.asarray(start.position) + np.trapezoid(velocity, t, axis=0)
    assert end.position == pytest.approx(reference, abs=1e-11)
    for fraction in np.linspace(0.01, 0.99, 19):
        point = integrate(start, yaw_rate, pitch_rate, step * fraction).position
        chord = (1 - fraction) * np.asarray(start.position) + fraction * np.asarray(
            end.position
        )
        assert (
            np.linalg.norm(point - chord)
            <= chord_error_bound(start.speed, yaw_rate, pitch_rate, step) + 1e-12
        )


def test_straight_finite_body_execution_succeeds() -> None:
    scene = load_scene("F5_EMPTY")
    result = track(
        [scene.start, scene.goal], scene, read_config("stage5a_protocol.json"), 0.25
    )
    assert result["eligible"] and result["execution_success"]
    assert result["final_position_error_m"] <= 0.75
    assert result["rate_limit_violations"] == 0


def test_point_valid_narrow_path_is_rejected_before_auv_execution() -> None:
    scene = load_scene("F5_GAP")
    assert scene.geometry(0).path(scene.witness).valid
    result = track(scene.witness, scene, read_config("stage5a_protocol.json"), 0)
    assert not result["eligible"] and not result["execution_success"]
    assert result["failure_reason"].startswith("geometry_rejected_before_tracking")


def test_valid_steep_path_can_fail_while_rates_stay_limited() -> None:
    values = np.zeros((30, 30, 30), dtype=bool)
    scene = Scene(
        {"family": "test"}, OccupancyMap(values), None, (4, 4, 4), (8, 4, 24), None
    )
    result = track(
        [scene.start, scene.goal], scene, read_config("stage5a_protocol.json"), 0
    )
    assert result["eligible"] and not result["execution_success"]
    assert result["pitch_saturation_steps"] > 0
    assert result["rate_limit_violations"] == result["pitch_limit_violations"] == 0


def test_rate_limited_controller_can_cut_into_obstacle_on_valid_polyline() -> None:
    values = np.zeros((30, 30, 15), dtype=bool)
    values[10:18, :18, :10] = True
    scene = Scene(
        {"family": "test"}, OccupancyMap(values), None, (4, 4, 5), (26, 4, 5), None
    )
    path = [scene.start, (4, 23, 5), (23, 23, 5), scene.goal]
    result = track(path, scene, read_config("stage5a_protocol.json"), 0)
    assert result["eligible"] and not result["execution_success"]
    assert result["yaw_saturation_steps"] > 0
    assert result["rate_limit_violations"] == 0
