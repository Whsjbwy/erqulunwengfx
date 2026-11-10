"""A shared optional shortcut stage, separate from every primary raw result."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

from .collision_checker import validate_path
from .map_reader import OccupancyMap, Point


def shortcut_path(points: ArrayLike, grid: OccupancyMap) -> list[Point]:
    """Return a deterministic, strictly revalidated greedy shortcut polyline.

    Coordinates retain map units and exact endpoints. Invalid input raises
    ``ValueError``. No original path is modified, and an invalid output raises
    ``RuntimeError`` rather than being reported as a valid processed path.
    """
    path = np.asarray(points, dtype=float).copy()
    if not validate_path(path, grid).valid:
        raise ValueError("Common postprocessing requires a strictly valid input path")
    output = [tuple(float(value) for value in path[0])]
    current = 0
    while current < len(path) - 1:
        selected = current + 1
        for candidate in range(len(path) - 1, current, -1):
            if validate_path([path[current], path[candidate]], grid).valid:
                selected = candidate
                break
        output.append(tuple(float(value) for value in path[selected]))
        current = selected
    if not validate_path(output, grid).valid:
        raise RuntimeError("Common postprocessing failed final strict validation")
    return output
