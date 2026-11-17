"""Independent algebra, boundary, continuous-safety and horizon acceptance."""

import math
import time
from dataclasses import replace

import numpy as np
import pytest

from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.stage5a.maps import Scene
from gsunlight_repro.stage5a.tracking import State, integrate
from gsunlight_repro.stage6b.replay import _replay
from gsunlight_repro.stage6b.scenarios import Scenario, mid_segment_scenario
from gsunlight_repro.stage7b0.execution import Safety, certify, execute
from gsunlight_repro.stage7b0.lqr import (
    Limits,
    bounded_control,
    command,
    jacobians,
    riccati,
    state_error,
    vector,
    weights,
)


def empty_case() -> Scenario:
    """A synthetic test only, unrelated to the six historical performance paths."""
    grid = OccupancyMap(np.zeros((40, 40, 30), dtype=bool), spacing=(1, 1, 1))
    initial = State((10, 10, 10), 0, 0, 1)
    scene = Scene({"id": "unit_only"}, grid, None, initial.position, (20, 10, 10), None)
    return Scenario("unit_only", scene, initial, (), "ok", "synthetic", "empty")


@pytest.mark.parametrize(
    "yaw,pitch,r,q",
    [
        (0, 0, 0, 0),
        (0.3, 0.2, 0.04, -0.03),
        (-1, -0.3, 0.08, 0.08),
        (1.8, 0.1, 1e-12, -1e-12),
        (math.pi, 0.2, 0.03, -0.03),
        (-math.pi, -0.2, -0.02, -0.02),
        (0.4, math.pi / 9, 0, 0),
        (0.4, -math.pi / 9, 0, 0),
    ],
)
def test_exact_flow_jacobians_against_independent_finite_difference(
    yaw: float, pitch: float, r: float, q: float
) -> None:
    state = State((8, 9, 10), yaw, pitch, 1)
    u, epsilon = np.array([r, q], dtype=float), 1e-5
    a, b = jacobians(state, u, 0.1)
    finite_a, finite_b = np.zeros((5, 5)), np.zeros((5, 2))
    for column in range(5):
        plus, minus = vector(state), vector(state)
        plus[column] += epsilon
        minus[column] -= epsilon
        first = integrate(State(tuple(plus[:3]), *plus[3:], 1), r, q, 0.1)
        second = integrate(State(tuple(minus[:3]), *minus[3:], 1), r, q, 0.1)
        finite_a[:, column] = state_error(first, second) / (2 * epsilon)
    for column in range(2):
        plus, minus = u.copy(), u.copy()
        plus[column] += epsilon
        minus[column] -= epsilon
        finite_b[:, column] = state_error(
            integrate(state, *plus, 0.1), integrate(state, *minus, 0.1)
        ) / (2 * epsilon)
    np.testing.assert_allclose(a, finite_a, rtol=0, atol=2e-9)
    np.testing.assert_allclose(b, finite_b, rtol=0, atol=2e-9)


def test_scalar_riccati_matches_independent_one_step_cost_minimizer() -> None:
    one = np.ones((1, 1))
    gains, costs = riccati([(one, one)], one, one, one)
    np.testing.assert_allclose(gains[0], [[0.5]])
    np.testing.assert_allclose(costs[0], [[1.5]])
    for u in (-0.6, -0.4):
        assert 1 + u * u + (1 + u) ** 2 > costs[0][0, 0]
    with pytest.raises(ValueError, match="positive definite"):
        riccati([(one, one)], one, np.zeros((1, 1)), one)


def test_zero_error_feedforward_and_full_synthetic_nominal_consistency() -> None:
    limits = Limits.frozen()
    inputs = [np.array([r, q]) for r, q in [(0.03, 0.02), (-0.02, -0.01), (0, 0)]]
    actual, refs = State((10, 10, 10), 0.1, 0.05, 1), []
    refs.append(actual)
    dynamics = []
    for u in inputs:
        dynamics.append(jacobians(refs[-1], u, limits.step))
        refs.append(integrate(refs[-1], *u, limits.step))
    gains, _ = riccati(dynamics, *weights(limits))
    for index, u in enumerate(inputs):
        requested, applied = command(actual, refs[index], u, gains[index], limits)
        np.testing.assert_array_equal(requested, u)
        np.testing.assert_array_equal(applied, u)
        actual = integrate(actual, *applied, limits.step)
        np.testing.assert_array_equal(vector(actual), vector(refs[index + 1]))


def test_nonzero_attitude_error_generates_corrective_feedback() -> None:
    limits = Limits.frozen()
    nominal = State((10, 10, 10), 0, 0, 1)
    a, b = jacobians(nominal, np.zeros(2), 0.1)
    gains, _ = riccati([(a, b)] * 20, *weights(limits))
    actual = replace(nominal, yaw=0.03, pitch=0.02)
    _, applied = command(actual, nominal, np.zeros(2), gains[0], limits)
    following = integrate(actual, *applied, limits.step)
    assert applied[0] < 0 and applied[1] < 0
    assert abs(following.yaw) < abs(actual.yaw)
    assert abs(following.pitch) < abs(actual.pitch)
    assert (
        np.linalg.matrix_rank(
            np.column_stack([np.linalg.matrix_power(a, k) @ b for k in range(5)]),
            tol=1e-10,
        )
        == 4
    )
    assert np.allclose(gains[0][:, 0], 0)


@pytest.mark.parametrize("sign", [-1, 1])
def test_signed_pitch_boundary_tolerance_and_saturation(sign: int) -> None:
    limits = Limits.frozen()
    envelope = limits.pitch + limits.tolerance
    for pitch in (sign * limits.pitch, sign * (limits.pitch + 5e-13), sign * envelope):
        state = State((10, 10, 10), 0, pitch, 1)
        u = bounded_control(state, np.array([99.0, sign * 99.0]), limits)
        assert u[0] == limits.yaw_rate and abs(u[1]) <= limits.pitch_rate
        assert abs(integrate(state, *u, 0.1).pitch) <= envelope
    for outside in (np.nextafter(envelope, math.inf), envelope + 1e-8):
        with pytest.raises(ValueError, match="constraints"):
            bounded_control(
                State((10, 10, 10), 0, sign * outside, 1), np.zeros(2), limits
            )


def test_invalid_controls_and_speed_are_not_silently_accepted() -> None:
    state, limits = State((10, 10, 10), 0, 0, 1), Limits.frozen()
    with pytest.raises(ValueError, match="finite"):
        bounded_control(state, np.array([np.nan, 0]), limits)
    with pytest.raises(ValueError, match="constraints"):
        bounded_control(replace(state, speed=0.95), np.zeros(2), limits)
    audit, _, _ = _replay(
        empty_case(),
        [{"yaw_rate_rad_s": 1.0, "pitch_rate_rad_s": 0.0, "duration_s": 0.1}],
    )
    assert audit["reason"] == "yaw_rate" and audit["integrated_intervals"] == 0


def test_free_endpoints_do_not_certify_a_crossing_control_interval() -> None:
    case = mid_segment_scenario()
    safety = Safety(case)
    end = integrate(case.initial, 0, 0, 0.1)
    oracle = safety.oracles["margin"]
    assert oracle.segment(case.initial.position, case.initial.position).valid
    assert oracle.segment(end.position, end.position).valid
    assert (
        safety.interval(case.initial, end, np.zeros(2), 0.1)["margin_reason"]
        == "physical_obstacle"
    )


def test_goal_ball_and_horizon_exhaustion_do_not_create_extra_controls() -> None:
    case, limits = empty_case(), Limits.frozen()
    inputs = [np.zeros(2)] * 2
    refs = [case.initial]
    for u in inputs:
        refs.append(integrate(refs[-1], *u, 0.1))
    gains, _ = riccati(
        [jacobians(s, u, 0.1) for s, u in zip(refs[:-1], inputs, strict=True)],
        *weights(limits),
    )
    summary, trace = execute(
        case, refs, inputs, gains, limits, time.perf_counter() + 10
    )
    assert (
        not summary["online_strict_success"]
        and summary["termination_reason"] == "reference_exhausted"
    )
    assert len(trace) == 2
    proof = certify(case, trace)
    assert proof["certificate_consistent"] and not proof["goal_reached"]
    for offset, expected in ((0.75, True), (0.75001, False)):
        target = (case.initial.position[0] + offset, 10, 10)
        goal_case = replace(case, scene=replace(case.scene, goal=target))
        result, saved = execute(
            goal_case, refs, inputs, gains, limits, time.perf_counter() + 10
        )
        assert result["online_strict_success"] and (len(saved) == 0) == expected


def test_independent_certificate_rejects_changed_saved_control() -> None:
    case, limits = empty_case(), Limits.frozen()
    u = np.zeros(2)
    refs = [case.initial, integrate(case.initial, *u, 0.1)]
    gains, _ = riccati([jacobians(case.initial, u, 0.1)], *weights(limits))
    _, trace = execute(case, refs, [u], gains, limits, time.perf_counter() + 10)
    trace[0]["yaw_rate_rad_s"] = 0.01
    with pytest.raises(ValueError, match="consistency"):
        certify(case, trace)


def test_yaw_error_crosses_representation_cut_locally() -> None:
    reference = State((10, 10, 10), math.pi - 0.01, 0, 1)
    actual = replace(reference, yaw=-math.pi + 0.01)
    assert state_error(actual, reference)[3] == pytest.approx(0.02)


def test_initial_goal_membership_cannot_bypass_initial_safety() -> None:
    case = empty_case()
    unsafe = replace(case.initial, position=(0.0, 0.0, 0.0))
    invalid = replace(
        case,
        initial=unsafe,
        scene=replace(case.scene, start=unsafe.position, goal=unsafe.position),
    )
    with pytest.raises(ValueError, match="strict safety"):
        execute(invalid, [unsafe], [], [], Limits.frozen(), time.perf_counter() + 10)
    valid = replace(case, scene=replace(case.scene, goal=case.initial.position))
    summary, trace = execute(
        valid, [valid.initial], [], [], Limits.frozen(), time.perf_counter() + 10
    )
    assert summary["online_strict_success"] and trace == []
