"""Standard finite-horizon LTV-LQR on the frozen exact five-state flow."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..stage5a.maps import read_config
from ..stage5a.tracking import State, wrap
from ..stage6b.replay import ANGLE_TOLERANCE_RAD

Matrix = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Limits:
    """Frozen physical bounds and the existing numerical pitch tolerance."""

    speed: float
    step: float
    yaw_rate: float
    pitch_rate: float
    pitch: float
    goal: float
    tolerance: float = ANGLE_TOLERANCE_RAD

    @classmethod
    def frozen(cls) -> Limits:
        """Read the historical protocol; no controller-specific physical changes."""
        cfg = read_config("stage5a_protocol.json")["kinematics"]
        return cls(
            cfg["speed_m_s"],
            cfg["step_s"],
            math.radians(cfg["max_yaw_rate_deg_s"]),
            math.radians(cfg["max_pitch_rate_deg_s"]),
            math.radians(cfg["max_pitch_deg"]),
            cfg["goal_tolerance_m"],
        )


def vector(state: State) -> Matrix:
    """Return the five dynamic states; speed remains a fixed parameter."""
    return np.asarray([*state.position, state.yaw, state.pitch], dtype=float)


def state_error(actual: State, reference: State) -> Matrix:
    """Use a local SO(2) yaw error even across the representation cut."""
    error = vector(actual) - vector(reference)
    error[3] = wrap(float(error[3]))
    return error


def integral_terms(angle: float, rate: float, step: float) -> tuple[float, ...]:
    """Return cosine/sine integrals and their exact derivatives w.r.t. rate."""
    half = rate * step / 2
    sinc = float(np.sinc(half / math.pi))
    if abs(half) < 1e-4:
        derivative = -half / 3 + half**3 / 30 - half**5 / 840 + half**7 / 45360
    else:
        derivative = (half * math.cos(half) - math.sin(half)) / half**2
    cosine, sine = math.cos(angle + half), math.sin(angle + half)
    return (
        step * sinc * cosine,
        step * sinc * sine,
        step**2 / 2 * (derivative * cosine - sinc * sine),
        step**2 / 2 * (derivative * sine + sinc * cosine),
    )


def jacobians(state: State, control: Matrix, step: float) -> tuple[Matrix, Matrix]:
    """Linearize the unconstrained exact flow, not the nonsmooth input clip.

    The yaw row is the local tangent chart derivative of the wrapped output.
    Pitch-boundary feasibility is separately enforced before propagation.
    """
    if step <= 0 or control.shape != (2,) or not np.isfinite(control).all():
        raise ValueError("Jacobian requires a positive step and two finite rates")
    if not np.isfinite([*vector(state), state.speed, step]).all():
        raise ValueError("Jacobian requires a finite state and time step")
    r, q = control
    plus = integral_terms(state.yaw + state.pitch, r + q, step)
    minus = integral_terms(state.yaw - state.pitch, r - q, step)
    vertical = integral_terms(state.pitch, q, step)
    speed = state.speed
    a, b = np.eye(5), np.zeros((5, 2))
    a[0, 3] = -speed / 2 * (plus[1] + minus[1])
    a[0, 4] = speed / 2 * (-plus[1] + minus[1])
    a[1, 3] = speed / 2 * (plus[0] + minus[0])
    a[1, 4] = speed / 2 * (plus[0] - minus[0])
    a[2, 4] = speed * vertical[0]
    b[0] = speed / 2 * np.array([plus[2] + minus[2], plus[2] - minus[2]])
    b[1] = speed / 2 * np.array([plus[3] + minus[3], plus[3] - minus[3]])
    b[2, 1] = speed * vertical[3]
    b[3, 0], b[4, 1] = step, step
    return a, b


def weights(limits: Limits) -> tuple[Matrix, Matrix, Matrix]:
    """Use preregistered physical scales once; never tune on task success."""
    state_scales = np.array([limits.goal] * 3 + [limits.yaw_rate, limits.pitch])
    input_scales = np.array([limits.yaw_rate, limits.pitch_rate])
    q, r = np.diag(state_scales**-2), np.diag(input_scales**-2)
    return q, r, q.copy()


def riccati(
    dynamics: list[tuple[Matrix, Matrix]], q: Matrix, r: Matrix, terminal: Matrix
) -> tuple[list[Matrix], list[Matrix]]:
    """Backward discrete Riccati using solves, returning gains and cost matrices."""
    n, m = q.shape[0], r.shape[0]
    for value, size, definite in ((q, n, False), (terminal, n, False), (r, m, True)):
        if value.shape != (size, size) or not np.isfinite(value).all():
            raise ValueError("Riccati cost matrices have invalid shape or values")
        if not np.allclose(value, value.T, rtol=0, atol=1e-12):
            raise ValueError("Riccati cost matrices must be symmetric")
        minimum = float(np.linalg.eigvalsh(value).min())
        if (definite and minimum <= 0) or (not definite and minimum < -1e-12):
            raise ValueError("R must be positive definite; Q and Qf semidefinite")
    gains, costs = [], [terminal.copy()]
    p = terminal.copy()
    for a, b in reversed(dynamics):
        if (
            a.shape != (n, n)
            or b.shape != (n, m)
            or not np.isfinite([*a.flat, *b.flat]).all()
        ):
            raise ValueError("Linearized dynamics are malformed or nonfinite")
        gain = np.linalg.solve(r + b.T @ p @ b, b.T @ p @ a)
        p = q + a.T @ p @ a - a.T @ p @ b @ gain
        p = (p + p.T) / 2
        gains.append(gain)
        costs.append(p)
    return list(reversed(gains)), list(reversed(costs))


def bounded_control(state: State, requested: Matrix, limits: Limits) -> Matrix:
    """Project onto frozen rate bounds and the same tolerated next-pitch set."""
    if requested.shape != (2,) or not np.isfinite(requested).all():
        raise ValueError("Control must contain two finite angular rates")
    envelope = limits.pitch + limits.tolerance
    if (
        not np.isfinite([*vector(state), state.speed]).all()
        or state.speed != limits.speed
        or abs(state.pitch) > envelope
    ):
        raise ValueError("Current state violates frozen model constraints")
    low = max(-limits.pitch_rate, (-envelope - state.pitch) / limits.step)
    high = min(limits.pitch_rate, (envelope - state.pitch) / limits.step)
    result = np.array(
        [
            np.clip(requested[0], -limits.yaw_rate, limits.yaw_rate),
            np.clip(requested[1], low, high),
        ],
        dtype=float,
    )
    if abs(state.pitch + result[1] * limits.step) > envelope:
        result[1] = math.nextafter(float(result[1]), 0.0)
    if abs(state.pitch + result[1] * limits.step) > envelope:
        raise ArithmeticError("Pitch projection failed at the binary64 boundary")
    return result


def command(
    actual: State, reference: State, feedforward: Matrix, gain: Matrix, limits: Limits
) -> tuple[Matrix, Matrix]:
    """Apply standard u_ref-Ke and explicit limits; no deadband hides errors."""
    requested = feedforward - gain @ state_error(actual, reference)
    return requested, bounded_control(actual, requested, limits)
