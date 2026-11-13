"""Breivik/Fossen 2005 3D LOS guidance, expressed in upward-positive z."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import Point
from ..stage5a.tracking import Route, State


def project(route: Route, position: Point) -> tuple[float, float, int]:
    """Expose the exact global nearest-segment convention used historically."""
    delta = np.asarray(position) - route.points[:-1]
    fraction = np.divide(
        np.einsum("ij,ij->i", delta, route.edges),
        route.lengths**2,
        out=np.zeros(len(route.edges)),
        where=route.lengths > 0,
    ).clip(0, 1)
    errors = np.linalg.norm(delta - fraction[:, None] * route.edges, axis=1)
    index = int(np.argmin(errors))
    return (
        float(route.cumulative[index] + fraction[index] * route.lengths[index]),
        float(errors[index]),
        index,
    )


def frame(tangent: np.ndarray) -> np.ndarray:
    """Return tangent/lateral/up-normal columns, with determinant +1."""
    norm = float(np.linalg.norm(tangent))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise ValueError("Path tangent must be finite and nonzero")
    tangent = tangent / norm
    yaw = math.atan2(tangent[1], tangent[0])
    lateral = np.array([-math.sin(yaw), math.cos(yaw), 0.0])
    return np.column_stack((tangent, lateral, np.cross(tangent, lateral)))


class LOS:
    """Virtual path particle plus transverse LOS, not global-nearest pursuit.

    Source: doi:10.1109/CDC.2005.1582226, equations 37,38,46,54,56,57.
    Finite path bounds, Euler progress and a rate-limited inner loop are explicit
    implementation adaptations; the ideal smooth-path proof is not claimed.
    """

    def __init__(self, route: Route, lookahead: float, gain: float = 1.0) -> None:
        if (
            not math.isfinite(lookahead)
            or not math.isfinite(gain)
            or lookahead <= 0
            or gain <= 0
        ):
            raise ValueError("LOS distances and progress gain must be positive")
        self.route, self.lookahead, self.gain = route, lookahead, gain
        self.progress = 0.0

    def command(self, state: State, dt: float) -> tuple[np.ndarray, dict]:
        """Compute a desired direction then propagate the virtual path particle."""
        route = self.route
        index = min(
            len(route.edges) - 1,
            int(np.searchsorted(route.cumulative, self.progress, side="right") - 1),
        )
        tangent = route.edges[index]
        if np.linalg.norm(tangent) < 1e-12:
            tangent = np.array([1.0, 0.0, 0.0])
        rotation = frame(tangent)
        reference = route.target(self.progress)
        along, lateral, vertical = rotation.T @ (np.asarray(state.position) - reference)
        azimuth = -math.atan2(lateral, self.lookahead)
        elevation = -math.atan2(vertical, self.lookahead)
        relative = np.array(
            [
                math.cos(azimuth) * math.cos(elevation),
                math.sin(azimuth) * math.cos(elevation),
                math.sin(elevation),
            ]
        )
        direction = rotation @ relative
        rate = state.speed * relative[0] + self.gain * along
        details = {
            "reference_progress_m": self.progress,
            "active_segment": index,
            "along_error_m": float(along),
            "lateral_error_m": float(lateral),
            "vertical_error_m": float(vertical),
            "progress_rate_m_s": float(rate),
            "reference_position": reference.tolist(),
        }
        self.progress = float(
            np.clip(self.progress + dt * rate, 0, route.cumulative[-1])
        )
        return np.asarray(state.position) + direction, details
