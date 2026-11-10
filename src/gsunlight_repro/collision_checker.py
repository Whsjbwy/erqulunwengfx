"""Independent continuous-segment checks against closed occupied voxel boxes.

The segment is split at every crossed grid plane. At each plane event and each
open interval's midpoint, all incident cells are examined. Occupancy is constant
between these events, so this is a supercover, not a fixed-step approximation.
Face, edge and corner contact with an obstacle counts as a collision.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import product

import numpy as np
from numpy.typing import ArrayLike

from .map_reader import OccupancyMap, Point, Voxel

# Coordinates within this distance of a grid plane are conservatively snapped
# to that plane. This tolerance is in voxel units, independent of physical scale.
GRID_TOLERANCE = 1e-10


@dataclass(frozen=True, slots=True)
class PathValidation:
    """Path verdict and first collision evidence in physical map coordinates."""

    valid: bool
    reason: str
    collision_segment_count: int
    first_collision_segment: int | None
    first_collision_voxel: Voxel | None
    first_collision_point: Point | None
    checked_segments: int


@dataclass(frozen=True, slots=True)
class VoxelVisit:
    """A closed voxel touched at a segment parameter and physical point."""

    voxel: Voxel
    parameter: float
    point: Point


def _incident_indices(coordinate: float, count: int) -> tuple[int, ...]:
    nearest = int(round(coordinate))
    if abs(coordinate - nearest) <= GRID_TOLERANCE:
        candidates = (nearest - 1, nearest)
    else:
        candidates = (int(np.floor(coordinate)),)
    return tuple(index for index in candidates if 0 <= index < count)


def trace_voxel_segment(
    start: ArrayLike, end: ArrayLike, grid: OccupancyMap
) -> Iterable[VoxelVisit]:
    """Yield the closed-voxel supercover in increasing segment parameter.

    Coordinates use the map's physical units. Endpoints must be finite triples
    inside the closed map domain, otherwise ``ValueError`` is raised. A zero-
    length segment yields every voxel incident to that point. Each voxel is
    yielded once, at its earliest representative event or interval midpoint.
    """
    points = np.asarray([start, end], dtype=float)
    if points.shape != (2, 3) or not np.all(np.isfinite(points)):
        raise ValueError("Segment endpoints must be finite coordinate triples")
    origin = np.asarray(grid.origin)
    spacing = np.asarray(grid.spacing)
    local = (points - origin) / spacing
    shape = np.asarray(grid.shape)
    if np.any(local < 0) or np.any(local > shape):
        raise ValueError("Segment endpoint is outside the closed map domain")
    direction = local[1] - local[0]
    events = {0.0, 1.0}
    for axis in range(3):
        if direction[axis] == 0:
            continue
        lower = int(np.ceil(min(local[:, axis])))
        upper = int(np.floor(max(local[:, axis])))
        for plane in range(lower, upper + 1):
            parameter = float((plane - local[0, axis]) / direction[axis])
            if 0 < parameter < 1:
                events.add(parameter)
    ordered_events = sorted(events)
    samples = [ordered_events[0]]
    for left, right in zip(ordered_events, ordered_events[1:], strict=False):
        samples.extend(((left + right) / 2, right))
    visited: set[Voxel] = set()
    for parameter in samples:
        coordinate = local[0] + parameter * direction
        axes = [
            _incident_indices(float(coordinate[axis]), grid.shape[axis])
            for axis in range(3)
        ]
        point = tuple(float(v) for v in points[0] + parameter * (points[1] - points[0]))
        for indices in product(*axes):
            if indices not in visited:
                visited.add(indices)
                yield VoxelVisit(indices, parameter, point)


def validate_path(points: ArrayLike, grid: OccupancyMap) -> PathValidation:
    """Check all polyline segments against closed occupied voxels and bounds.

    Return a verdict rather than raising for malformed paths. At least two
    finite coordinate triples are required. A segment touching several obstacles
    is counted once; out-of-bounds segments also count as invalid segments. The
    first reported point belongs to the first invalid segment in path order.
    """
    try:
        path = np.asarray(points, dtype=float)
    except (TypeError, ValueError):
        return PathValidation(False, "invalid_path", 0, None, None, None, 0)
    if path.ndim != 2 or path.shape[1:] != (3,) or len(path) < 2:
        return PathValidation(False, "invalid_path", 0, None, None, None, 0)
    if not np.all(np.isfinite(path)):
        return PathValidation(False, "invalid_path", 0, None, None, None, 0)
    local = (path - np.asarray(grid.origin)) / np.asarray(grid.spacing)
    outside = np.any((local < 0) | (local > np.asarray(grid.shape)), axis=1)
    invalid_count = 0
    first_segment = None
    first_voxel = None
    first_point = None
    reason = "ok"
    for index, (start, end) in enumerate(zip(path, path[1:], strict=False)):
        if outside[index] or outside[index + 1]:
            invalid_count += 1
            if first_segment is None:
                first_segment = index
                endpoint = start if outside[index] else end
                first_point = tuple(float(value) for value in endpoint)
                reason = "out_of_bounds"
            continue
        for visit in trace_voxel_segment(start, end, grid):
            if grid.occupancy[visit.voxel]:
                invalid_count += 1
                if first_segment is None:
                    first_segment = index
                    first_voxel = visit.voxel
                    first_point = visit.point
                    reason = "collision"
                break
    return PathValidation(
        invalid_count == 0,
        reason,
        invalid_count,
        first_segment,
        first_voxel,
        first_point,
        len(path) - 1,
    )
