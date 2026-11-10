"""Independent safe G-Sunlight reference; no author hooks or fallback planners."""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import ArrayLike

from .collision_checker import validate_path
from .map_reader import OccupancyMap, Point
from .metrics import endpoints_match
from .paper_planner import run_search
from .planning import PlanningLimits, PlanResult

METHOD = "safety_reference"
VERSION = "stage2-safety-v1"


def validated_path(path: ArrayLike, grid: OccupancyMap) -> list[Point]:
    """Copy a strictly valid physical-coordinate path; raise ValueError otherwise."""
    if not validate_path(path, grid).valid:
        raise ValueError("Safety reference requires a strictly valid complete path")
    return [tuple(float(value) for value in point) for point in np.asarray(path)]


def accept_safe_postprocessing(
    original: ArrayLike, candidate: ArrayLike, grid: OccupancyMap
) -> list[Point]:
    """Accept an optional safe result with the same endpoints, otherwise roll back.

    The original must already be valid. This helper performs no smoothing and
    does not change the primary raw-path result; common postprocessing belongs
    to the experiment layer and is recorded as a separate outcome.
    """
    fallback = validated_path(original, grid)
    if validate_path(candidate, grid).valid and endpoints_match(
        candidate, fallback[0], fallback[-1]
    ):
        return validated_path(candidate, grid)
    return fallback


def plan(
    grid: OccupancyMap,
    start: Point,
    goal: Point,
    seed: int,
    limits: PlanningLimits,
    parameters: dict[str, Any] | None = None,
) -> PlanResult:
    """Run independently written G-Sunlight with explicit whole-chain safety guards.

    Parent edges are checked before insertion. Goal links, complete reconstructed
    paths and final raw paths are checked against closed occupied voxels. This
    version shares the self-written paper controller and pure sampling/grid
    helpers; it never imports the author algorithm or invokes A* as a fallback.
    """
    return run_search(
        grid,
        start,
        goal,
        seed,
        limits,
        parameters,
        method=METHOD,
        version=VERSION,
        safety_guards=True,
    )
