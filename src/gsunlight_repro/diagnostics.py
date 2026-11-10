"""Isolated safety hooks for diagnosis, separate from the author baseline."""

from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .collision_checker import validate_path
from .map_reader import OccupancyMap
from .metrics import path_length


@contextmanager
def adapt(
    utils: ModuleType, grid: OccupancyMap, parameters: dict[str, Any]
) -> Iterator[None]:
    """Guard candidate edges, goal connections and smoothing in map units.

    Only module functions are replaced, and all three are restored on exit,
    including exceptional exits. The author's files and map stay unchanged.
    Counts and the exact safety measures are recorded in ``parameters``.

    The original entry point consumes candidates rather than a direct path.
    When the current sun can reach the goal, return that sun as a zero-cost
    candidate. This intentionally leaves a repeated waypoint in the evidence.
    Invalid input to smoothing raises ``ValueError``; an invalid smoothing
    output rolls back to the valid input path, without suppressing exceptions.
    """
    original_tangent = utils.findtangent
    original_cross = utils.findcross
    original_backend = utils.backendprocess
    counts = {
        "rejected_edges": 0,
        "direct_goal_candidates": 0,
        "smoothing_rollbacks": 0,
    }
    parameters["safety_changes"] = [
        "strict_parent_candidate_filter",
        "strict_goal_and_smoothing_links",
        "direct_goal_as_zero_cost_repeated_candidate",
        "whole_path_smoothing_validation_and_rollback",
    ]
    parameters["diagnostic_counts"] = counts

    def strict_cross(
        first: ArrayLike,
        second: ArrayLike,
        map_data: Any,
        step: float,
    ) -> tuple[int, float]:
        """Return a strict blocked flag and Euclidean length in map units."""
        valid = validate_path([first, second], grid).valid
        length = float(
            np.linalg.norm(np.asarray(second, dtype=float) - np.asarray(first))
        )
        return int(not valid), length

    def safe_tangent(
        point: ArrayLike, goal: ArrayLike, *args: Any, **kwargs: Any
    ) -> NDArray[np.float32]:
        """Keep sampled candidates only when their entire parent edge is valid."""
        if validate_path([point, goal], grid).valid:
            counts["direct_goal_candidates"] += 1
            candidate = np.append(np.asarray(point, dtype=float), 0.0)
            return np.asarray([candidate], dtype=np.float32)
        candidates = np.asarray(
            original_tangent(point, goal, *args, **kwargs), dtype=np.float32
        )
        if candidates.size == 0:
            return candidates
        accepted = []
        for candidate in candidates:
            if validate_path([point, candidate[:3]], grid).valid:
                accepted.append(candidate)
            else:
                counts["rejected_edges"] += 1
        return np.asarray(accepted, dtype=np.float32).reshape(-1, 4)

    def safe_backend(
        path: ArrayLike, step: float, map_data: Any
    ) -> tuple[float, NDArray[Any]]:
        """Recheck the complete smoothing result and roll back unsafe output."""
        if not validate_path(path, grid).valid:
            raise ValueError(
                "Safety diagnosis received an invalid path before smoothing"
            )
        original_path = np.asarray(path).copy()
        if len(original_path) < 3:
            return path_length(original_path), original_path
        _, candidate = original_backend(original_path.copy(), step, map_data)
        if validate_path(candidate, grid).valid:
            return path_length(candidate), candidate
        counts["smoothing_rollbacks"] += 1
        return path_length(original_path), original_path

    utils.findtangent = safe_tangent
    utils.findcross = strict_cross
    utils.backendprocess = safe_backend
    try:
        yield
    finally:
        utils.findtangent = original_tangent
        utils.findcross = original_cross
        utils.backendprocess = original_backend
