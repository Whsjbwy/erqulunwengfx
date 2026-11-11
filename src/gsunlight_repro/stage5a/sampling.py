"""Uniform 3D ball and correctly rotated prolate-ellipsoid sampling."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import Point


class InformedSampler:
    """Use the raw best tree cost, never an unverified optimistic bound."""

    def __init__(self, start: Point, goal: Point) -> None:
        self.center = (np.asarray(start) + goal) / 2
        self.minimum = math.dist(start, goal)
        self.rotation = np.eye(3)
        if self.minimum > 0:
            axis = (np.asarray(goal) - start) / self.minimum
            left, _, right = np.linalg.svd(np.outer(axis, [1, 0, 0]))
            self.rotation = (
                left
                @ np.diag([1, 1, np.linalg.det(left) * np.linalg.det(right)])
                @ right
            )

    def sample(self, rng: np.random.Generator, best: float) -> Point:
        """Generate a volume-uniform sample, including well-defined degeneracy."""
        if not math.isfinite(best) or best < self.minimum - 1e-10:
            raise ValueError(
                "Informed sampling requires a finite admissible upper bound"
            )
        direction = rng.normal(size=3)
        norm = float(np.linalg.norm(direction))
        while norm == 0:
            direction = rng.normal(size=3)
            norm = float(np.linalg.norm(direction))
        unit_ball = direction / norm * rng.random() ** (1 / 3)
        best = max(best, self.minimum)
        minor = math.sqrt(max(0.0, (best - self.minimum) * (best + self.minimum))) / 2
        point = self.rotation @ (unit_ball * [best / 2, minor, minor]) + self.center
        return tuple(float(value) for value in point)


def neighbor_radius(count: int, step: float, workspace_volume: float) -> float:
    """RRT* Algorithm6/Theorem38 with d=3 and a free-volume upper bound."""
    gamma = 1.1 * (2 * (1 + 1 / 3) * workspace_volume / (4 * math.pi / 3)) ** (1 / 3)
    count = max(2, count)
    return min(step, gamma * (math.log(count) / count) ** (1 / 3))
