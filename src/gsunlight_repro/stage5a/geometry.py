"""Continuous swept-sphere checks against closed axis-aligned voxel boxes."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

from ..map_reader import OccupancyMap, Point

TOLERANCE = 1e-9


def segment_box_distances(
    start: NDArray, end: NDArray, lower: NDArray, upper: NDArray
) -> NDArray:
    """Minimize squared distance on every quadratic interval analytically.

    Coordinate/box-face crossing parameters partition [0,1]. On each interval
    the active coordinate residuals are affine, so its minimum is stationary
    or at an endpoint. No spatial point sampling is used.
    """
    if not len(lower):
        return np.empty(0)
    delta = end - start
    crossings = np.zeros((len(lower), 6))
    for axis in range(3):
        if delta[axis] != 0:
            crossings[:, 2 * axis] = (lower[:, axis] - start[axis]) / delta[axis]
            crossings[:, 2 * axis + 1] = (upper[:, axis] - start[axis]) / delta[axis]
    knots = np.sort(
        np.column_stack(
            (np.zeros(len(lower)), np.clip(crossings, 0, 1), np.ones(len(lower)))
        ),
        axis=1,
    )
    left, right = knots[:, :-1], knots[:, 1:]
    midpoint = start + ((left + right) / 2)[..., None] * delta
    below, above = midpoint < lower[:, None], midpoint > upper[:, None]
    intercept = np.where(
        below, lower[:, None] - start, np.where(above, start - upper[:, None], 0)
    )
    slope = np.where(below, -delta, np.where(above, delta, 0))
    numerator = -np.sum(intercept * slope, axis=2)
    denominator = np.sum(slope * slope, axis=2)
    stationary = np.divide(
        numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0
    )
    parameters = np.clip(stationary, left, right)
    positions = start + parameters[..., None] * delta
    residual = np.maximum(
        np.maximum(lower[:, None] - positions, positions - upper[:, None]), 0
    )
    return np.sqrt(np.min(np.sum(residual * residual, axis=2), axis=1))


def reference_distance(
    start: ArrayLike, end: ArrayLike, lower: ArrayLike, upper: ArrayLike
) -> float:
    """Independent convex interval search with a conservative Lipschitz error.

    Used only for small-map cross-checks, not the formal planning hot path.
    """
    a, b, lo, hi = (np.asarray(x, dtype=float) for x in (start, end, lower, upper))
    delta = b - a

    def distance(t: float) -> float:
        return float(
            np.linalg.norm(
                np.maximum(np.maximum(lo - (a + t * delta), a + t * delta - hi), 0)
            )
        )

    left, right = 0.0, 1.0
    for _ in range(96):
        one, two = (2 * left + right) / 3, (left + 2 * right) / 3
        if distance(one) <= distance(two):
            right = two
        else:
            left = one
    estimate = min(distance(0), distance(1), distance((left + right) / 2))
    return max(0.0, estimate - float(np.linalg.norm(delta)) * (right - left))


@dataclass(frozen=True, slots=True)
class Verdict:
    """A geometric verdict, never an execution-success claim."""

    valid: bool
    reason: str


class Geometry:
    """One body radius, immutable physical voxels and optional mission ceiling."""

    def __init__(
        self, grid: OccupancyMap, radius: float, ceiling: OccupancyMap | None = None
    ) -> None:
        if not math.isfinite(radius) or radius < 0:
            raise ValueError("Radius must be finite and nonnegative")
        if ceiling is not None and (
            ceiling.shape != grid.shape
            or ceiling.origin != grid.origin
            or ceiling.spacing != grid.spacing
        ):
            raise ValueError("Mission and physical voxel frames must match")
        self.grid, self.radius, self.ceiling = grid, radius, ceiling
        self.query_calls = 0
        self.box_distance_tests = 0
        self.segment_requests = 0

    def _distance(
        self, a: NDArray, b: NDArray, grid: OccupancyMap, cutoff: float
    ) -> float:
        """Use a conservative swept AABB broad phase, then exact distances."""
        origin, spacing = np.asarray(grid.origin), np.asarray(grid.spacing)
        low = np.maximum(
            0, np.floor((np.minimum(a, b) - cutoff - origin) / spacing).astype(int) - 1
        )
        high = np.minimum(
            grid.shape,
            np.floor((np.maximum(a, b) + cutoff - origin) / spacing).astype(int) + 2,
        )
        if np.any(low >= high):
            return cutoff
        indices = np.argwhere(
            grid.occupancy[
                tuple(
                    slice(int(left), int(right))
                    for left, right in zip(low, high, strict=True)
                )
            ]
        )
        if not len(indices):
            return cutoff
        lower = origin + (indices + low) * spacing
        self.box_distance_tests += len(indices)
        return min(
            cutoff, float(np.min(segment_box_distances(a, b, lower, lower + spacing)))
        )

    def segment(
        self, start: ArrayLike, end: ArrayLike, *, extra_radius: float = 0
    ) -> Verdict:
        """Certify an entire swept sphere; obstacle contact is rejected."""
        self.query_calls += 1
        self.segment_requests += 1
        try:
            points = np.asarray([start, end], dtype=float)
        except (TypeError, ValueError):
            return Verdict(False, "invalid_coordinates")
        if points.shape != (2, 3) or not np.all(np.isfinite(points)):
            return Verdict(False, "invalid_coordinates")
        if not math.isfinite(extra_radius) or extra_radius < 0:
            raise ValueError("Extra radius must be finite and nonnegative")
        radius = self.radius + extra_radius
        lower = np.asarray(self.grid.origin)
        upper = lower + np.asarray(self.grid.shape) * self.grid.spacing
        if np.any(points - lower < radius) or np.any(upper - points < radius):
            return Verdict(False, "workspace_boundary")
        if (
            self._distance(points[0], points[1], self.grid, radius + 2 * TOLERANCE)
            <= radius + TOLERANCE
        ):
            return Verdict(False, "physical_obstacle")
        if (
            self.ceiling is not None
            and self._distance(
                points[0], points[1], self.ceiling, radius + 2 * TOLERANCE
            )
            <= radius + TOLERANCE
        ):
            return Verdict(False, "mission_ceiling")
        return Verdict(True, "ok")

    def path(self, path: ArrayLike) -> Verdict:
        """Validate every edge, including endpoints of a zero-length path."""
        try:
            points = np.asarray(path, dtype=float)
        except (ValueError, TypeError):
            return Verdict(False, "invalid_path")
        if (
            points.ndim != 2
            or points.shape[1:] != (3,)
            or len(points) < 2
            or not np.all(np.isfinite(points))
        ):
            return Verdict(False, "invalid_path")
        for a, b in zip(points[:-1], points[1:], strict=True):
            verdict = self.segment(a, b)
            if not verdict.valid:
                return verdict
        return Verdict(True, "ok")

    def clearance(
        self, start: Point, end: Point, cap: float = 3, *, mission: bool = False
    ) -> float:
        """Return min(center-to-box/boundary distance - radius, cap).

        A cap value is a truncated lower bound, not an unbounded exact distance.
        """
        if not math.isfinite(cap) or cap <= 0:
            raise ValueError("Clearance cap must be finite and positive")
        points = np.asarray([start, end], dtype=float)
        lower = np.asarray(self.grid.origin)
        upper = lower + np.asarray(self.grid.shape) * self.grid.spacing
        result = min(
            float(np.min(np.minimum(points - lower, upper - points))), self.radius + cap
        )
        result = min(
            result, self._distance(points[0], points[1], self.grid, self.radius + cap)
        )
        if mission and self.ceiling is not None:
            result = min(
                result,
                self._distance(points[0], points[1], self.ceiling, self.radius + cap),
            )
        return result - self.radius
