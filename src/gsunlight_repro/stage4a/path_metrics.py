"""Post-run path metrics, excluded from planning and never used for selection."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import OccupancyMap, Point


def turn_count(path: list[Point], threshold: float = 1.0) -> int:
    """Count bends above a fixed degree threshold, skipping zero-length edges."""
    vectors = np.diff(np.asarray(path, dtype=float), axis=0)
    norms = np.linalg.norm(vectors, axis=1)
    vectors = vectors[norms > 0] / norms[norms > 0, None]
    if len(vectors) < 2:
        return 0
    cosines = np.clip(np.einsum("ij,ij->i", vectors[:-1], vectors[1:]), -1, 1)
    return int(np.count_nonzero(np.degrees(np.arccos(cosines)) > threshold))


def clearance_lower_bound(
    path: list[Point], grid: OccupancyMap, step: float = 0.5
) -> float:
    """Bound clearance via occupied-center balls and a sampling Lipschitz bound.

    Every occupied box is contained in its center's half-diagonal ball. Every
    point on a segment is at most step/2 from an endpoint-inclusive sample.
    Thus min center distance - half-diagonal - step/2 is a conservative bound,
    not an exact minimum. A zero bound does not assert collision.
    """
    if step <= 0:
        raise ValueError("Clearance sample step must be positive")
    vertices = np.asarray(path, dtype=float)
    lower = np.asarray(grid.origin)
    upper = lower + np.asarray(grid.shape) * grid.spacing
    boundary = float(np.min(np.minimum(vertices - lower, upper - vertices)))
    occupied = np.argwhere(grid.occupancy)
    if not len(occupied):
        return max(0.0, boundary)
    # VTK is already a locked project dependency. This locator is only a
    # post-run metric, never a replacement for the continuous validator.
    from vtkmodules.util.numpy_support import numpy_to_vtk
    from vtkmodules.vtkCommonCore import vtkPoints
    from vtkmodules.vtkCommonDataModel import vtkPolyData, vtkStaticPointLocator

    centers = lower + (occupied + 0.5) * np.asarray(grid.spacing)
    points = vtkPoints()
    points.SetData(numpy_to_vtk(centers, deep=True))
    data = vtkPolyData()
    data.SetPoints(points)
    locator = vtkStaticPointLocator()
    locator.SetDataSet(data)
    locator.BuildLocator()
    minimum = math.inf
    for first, second in zip(vertices[:-1], vertices[1:], strict=True):
        intervals = max(1, math.ceil(float(np.linalg.norm(second - first)) / step))
        for point in np.linspace(first, second, intervals + 1):
            index = locator.FindClosestPoint(point)
            minimum = min(minimum, float(np.linalg.norm(point - centers[index])))
    obstacle_bound = minimum - float(np.linalg.norm(grid.spacing)) / 2 - step / 2
    return max(0.0, min(boundary, obstacle_bound))
