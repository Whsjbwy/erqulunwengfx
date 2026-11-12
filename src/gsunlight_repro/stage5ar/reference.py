"""Independent RK4 integration and point-to-box curve checks for diagnosis."""

from __future__ import annotations

import math

import numpy as np

from ..stage5a.maps import Scene
from ..stage5a.tracking import State, integrate


def rk4_position(
    state: State, yaw_rate: float, pitch_rate: float, duration: float, steps: int = 2000
) -> np.ndarray:
    """Integrate the full five-state ODE independently with small RK4 steps."""
    value = np.array([*state.position, state.yaw, state.pitch], dtype=float)
    dt = duration / steps

    def derivative(current: np.ndarray) -> np.ndarray:
        yaw, pitch = current[3:]
        return np.array(
            [
                state.speed * math.cos(pitch) * math.cos(yaw),
                state.speed * math.cos(pitch) * math.sin(yaw),
                state.speed * math.sin(pitch),
                yaw_rate,
                pitch_rate,
            ]
        )

    for _ in range(steps):
        a = derivative(value)
        b = derivative(value + dt * a / 2)
        c = derivative(value + dt * b / 2)
        d = derivative(value + dt * c)
        value += dt * (a + 2 * b + 2 * c + d) / 6
    return value[:3]


def sampled_curve_evidence(
    event: dict, scene: Scene, radius: float, samples: int = 101
) -> dict:
    """Bound clearance independently of segment-box minimization.

    A negative sampled clearance proves a sphere-model intersection at a
    sampled instant. A positive Lipschitz lower bound certifies this curve
    segment. Neither is a statement about the actual slender vehicle.
    """
    if samples < 2:
        raise ValueError("At least two reference curve samples are required")
    state = State(
        tuple(event["start_position"]),
        event["start_yaw_rad"],
        event["start_pitch_rad"],
        event["speed_m_s"],
    )
    duration = event["time_s"] - event["time_start_s"]
    times = np.linspace(0, duration, samples)
    points = np.array(
        [
            state.position
            if t == 0
            else integrate(
                state, event["yaw_rate_rad_s"], event["pitch_rate_rad_s"], float(t)
            ).position
            for t in times
        ]
    )
    origin = np.array(scene.grid.origin)
    upper_workspace = origin + np.array(scene.grid.shape) * scene.grid.spacing
    boundary = (
        float(np.min(np.minimum(points - origin, upper_workspace - points))) - radius
    )

    def clearance(grid) -> float:
        indices = np.argwhere(grid.occupancy)
        lower = np.array(grid.origin) + indices * grid.spacing
        upper = lower + grid.spacing
        # Only boxes whose distance could undercut radius+1 are needed.
        near = np.all(upper >= points.min(axis=0) - radius - 1, axis=1) & np.all(
            lower <= points.max(axis=0) + radius + 1, axis=1
        )
        lower, upper = lower[near], upper[near]
        if not len(lower):
            return 1.0
        residual = np.maximum(
            np.maximum(lower[None] - points[:, None], points[:, None] - upper[None]), 0
        )
        return float(np.min(np.linalg.norm(residual, axis=2))) - radius

    physical = min(boundary, clearance(scene.grid))
    mission = min(physical, clearance(scene.ceiling)) if scene.ceiling else physical
    error = state.speed * duration / (2 * (samples - 1))
    result = {"reference_samples": samples, "reference_lipschitz_gap_m": error}
    for name, value in (("physical", physical), ("mission", mission)):
        result.update(
            {
                f"reference_{name}_sample_min_m": value,
                f"reference_{name}_curve_lower_bound_m": value - error,
                f"reference_{name}_classification": "sampled_sphere_intersection"
                if value < -1e-9
                else "curve_certified_clear"
                if value - error > 1e-9
                else "unresolved_contact_band",
            }
        )
    return result
