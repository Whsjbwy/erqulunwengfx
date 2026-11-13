"""Analytic tracking, coordinate conventions and continuous fillet safety."""

import math

import numpy as np
import pytest

from gsunlight_repro.stage5a.maps import read_config
from gsunlight_repro.stage5a.tracking import Route, State
from gsunlight_repro.stage5ae.curves import fillet
from gsunlight_repro.stage5ae.guidance import LOS, frame
from gsunlight_repro.stage5ae.verification import analytic_cases, folded_projection_case
from gsunlight_repro.stage5ar.p0 import empty_scene


def test_finite_path_los_does_not_claim_a_terminal_attractor() -> None:
    """Expose the frozen guidance limitation without silently repairing it."""
    route = Route([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)])
    guidance = LOS(route, 2.0)
    guidance.progress = 10.0
    state = State((11.0, 0.0, 0.0), 0.0, 0.0, 1.0)
    target, _ = guidance.command(state, 0.1)
    desired = target - state.position
    assert guidance.progress == 10.0
    assert desired @ (route.points[-1] - state.position) < 0


def test_analytic_positive_and_negative_tracking_cases() -> None:
    rows = analytic_cases()
    assert len(rows) == 22
    assert rows[-1]["maximum_error_m"] < 1e-10


def test_global_projection_can_jump_without_silent_algorithm_change() -> None:
    result = folded_projection_case()
    assert result["projection_step_m"] > 10
    assert result["position_step_m"] < 0.01


def test_path_frame_is_proper_and_invalid_lookahead_is_rejected() -> None:
    rotation = frame(np.array([1.0, 2.0, 3.0]))
    assert np.linalg.det(rotation) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        LOS(None, -1)


def test_horizontal_fillet_has_bounded_curvature_and_true_arc_exit() -> None:
    scene = empty_scene((8, 8, 8), (28, 28, 8))
    result = fillet([scene.start, (28, 8, 8), scene.goal], scene.geometry(1.02), 6.0)
    assert result["valid"] and result["arc_count"] == 1
    assert result["length_m"] == pytest.approx(28 + 3 * math.pi)
    assert result["max_curvature_m_inv"] == pytest.approx(1 / 6)
    assert result["maximum_chord_enclosure_m"] < 0.001
    assert scene.geometry(1.02).path(result["display_points"]).valid
    assert (
        fillet([(8, 8, 8), (9, 8, 8), (9, 9, 8)], scene.geometry(1.02), 6.0)["status"]
        == "insufficient_segment_length"
    )
    assert (
        fillet([(8, 8, 8), (28, 8, 9)], scene.geometry(1.02), 6.0)["status"]
        == "unsupported_nonhorizontal"
    )


def test_control_candidates_keep_original_actuator_and_speed_settings() -> None:
    protocol = read_config("stage5ae_protocol.json")
    assert [row["lookahead_m"] for row in protocol["controller_candidates"]] == [
        2.0,
        4.0,
    ]
    assert protocol["planning_budget_s"] == 10
