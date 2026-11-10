"""Independent conical and planar tangent sampling from paper algorithms 2--4."""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .collision_checker import trace_voxel_segment, validate_path
from .map_reader import OccupancyMap, Point, Voxel
from .planning import Deadline, SearchCounters


@dataclass(frozen=True, slots=True)
class SamplingParameters:
    """Angular steps in degrees and distances in physical map-coordinate units."""

    theta_step_degrees: float = 5.0
    phi_step_degrees: float = 10.0
    half_cone_degrees: float = 30.0
    distance_step: float = 5.0
    length_threshold: float = 15.0
    forward_distance: float = 3.0

    def __post_init__(self) -> None:
        values = (
            self.theta_step_degrees,
            self.phi_step_degrees,
            self.half_cone_degrees,
            self.distance_step,
            self.length_threshold,
            self.forward_distance,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Sampling parameters must be finite")
        if min(self.theta_step_degrees, self.phi_step_degrees, self.distance_step) <= 0:
            raise ValueError("Angular and distance steps must be positive")
        if not 0 <= self.half_cone_degrees <= 180:
            raise ValueError("Half-cone angle must be between zero and 180 degrees")
        if min(self.length_threshold, self.forward_distance) < 0:
            raise ValueError("Length threshold and forward distance cannot be negative")


def angle_values(stop: float, step: float, *, inclusive: bool) -> Iterator[float]:
    """Yield an integer-multiple angular lattice, without adding an off-lattice end."""
    if not math.isfinite(stop) or not math.isfinite(step) or step <= 0 or stop < 0:
        raise ValueError(
            "Angle range must be finite, nonnegative and have positive step"
        )
    index = 0
    while True:
        angle = index * step
        past_stop = angle > stop + 1e-12 if inclusive else angle >= stop
        if past_stop:
            return
        yield min(angle, stop) if inclusive else angle
        index += 1


def find_direction(point: Point, goal: Point, phi: float, theta1: float) -> Point:
    """Return the paper's Z--Y--X--Y unit direction; both angles are radians.

    Unlike another common convention, the paper's Ry has -sin in its upper
    right entry. Coincident endpoints or nonfinite inputs raise ValueError.
    """
    values = np.asarray([point, goal], dtype=float)
    if values.shape != (2, 3) or not np.all(np.isfinite(values)):
        raise ValueError("Direction endpoints must be finite triples")
    if not math.isfinite(phi) or not math.isfinite(theta1):
        raise ValueError("Direction angles must be finite")
    difference = values[1] - values[0]
    if not np.any(difference):
        raise ValueError("A conical axis needs distinct endpoints")
    psi = math.atan2(difference[1], difference[0])
    theta = math.atan2(difference[2], math.hypot(*difference[:2]))
    # Applying Ry(theta1), Rx(phi), Ry(theta), Rz(psi) to (1,0,0)
    # avoids allocating four small matrices for every sampled ray.
    cosine, sine = math.cos(theta1), math.sin(theta1)
    local_x = math.cos(theta) * cosine - math.sin(theta) * math.cos(phi) * sine
    local_y = -math.sin(phi) * sine
    local_z = math.sin(theta) * cosine + math.cos(theta) * math.cos(phi) * sine
    direction = np.asarray(
        [
            math.cos(psi) * local_x - math.sin(psi) * local_y,
            math.sin(psi) * local_x + math.cos(psi) * local_y,
            local_z,
        ]
    )
    direction /= np.linalg.norm(direction)
    return tuple(float(value) for value in direction)


def _ray_domain(
    point: Point, direction: Point, grid: OccupancyMap
) -> tuple[NDArray[np.float64], NDArray[np.float64], float]:
    start = np.asarray(point, dtype=float)
    vector = np.asarray(direction, dtype=float)
    if start.shape != (3,) or vector.shape != (3,):
        raise ValueError("Ray coordinates and direction must be triples")
    if not np.all(np.isfinite(start)) or not np.all(np.isfinite(vector)):
        raise ValueError("Ray coordinates and direction must be finite")
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        raise ValueError("Ray direction cannot be zero")
    vector = vector / norm
    lower = np.asarray(grid.origin)
    upper = lower + np.asarray(grid.shape) * np.asarray(grid.spacing)
    if np.any(start < lower) or np.any(start > upper):
        raise ValueError("Ray origin is outside the map")
    distances = [
        ((upper[axis] if vector[axis] > 0 else lower[axis]) - start[axis])
        / vector[axis]
        for axis in range(3)
        if vector[axis] != 0
    ]
    return start, vector, max(0.0, min(distances))


def _entry_distance(
    start: NDArray[np.float64],
    vector: NDArray[np.float64],
    voxel: Voxel,
    grid: OccupancyMap,
) -> float:
    lower = np.asarray(grid.origin) + np.asarray(voxel) * np.asarray(grid.spacing)
    upper = lower + np.asarray(grid.spacing)
    entry = 0.0
    for axis in range(3):
        if vector[axis] != 0:
            first = (lower[axis] - start[axis]) / vector[axis]
            second = (upper[axis] - start[axis]) / vector[axis]
            entry = max(entry, min(first, second))
    return entry


def _checked_prefix(
    start: NDArray[np.float64],
    vector: NDArray[np.float64],
    length: float,
    grid: OccupancyMap,
    deadline: Deadline,
    counters: SearchCounters,
) -> bool:
    deadline.check()
    counters.collision_checks = int(counters.collision_checks or 0) + 1
    return validate_path([start, start + vector * length], grid).valid


def ray_free_length(
    point: Point,
    direction: Point,
    grid: OccupancyMap,
    distance_step: float,
    deadline: Deadline,
    counters: SearchCounters,
) -> float:
    """Return the last valid discrete prefix using one whole-ray supercover.

    Distances are in physical map units; the supplied direction is normalized.
    A closed-obstacle entry is forbidden, whereas the closed map boundary is
    allowed. A slab intersection recovers entry distance because supercover
    visits can represent interval midpoints. Adjacent prefix checks reconcile
    floating boundary/tolerance cases with the ordinary strict segment oracle.
    Invalid ray origins raise ValueError; deadline checks occur inside traversal.
    This is an equivalent sampling optimization, not a complexity assertion.
    """
    deadline.check()
    if not math.isfinite(distance_step) or distance_step <= 0:
        raise ValueError("Ray distance step must be finite and positive")
    start, vector, boundary = _ray_domain(point, direction, grid)
    lower = np.asarray(grid.origin)
    upper = lower + np.asarray(grid.shape) * np.asarray(grid.spacing)
    endpoint = np.clip(start + vector * boundary, lower, upper)
    hit = None
    counters.sampled_nodes = int(counters.sampled_nodes or 0) + 1
    counters.collision_checks = int(counters.collision_checks or 0) + 1
    for visit in trace_voxel_segment(start, endpoint, grid):
        deadline.check()
        if grid.occupancy[visit.voxel]:
            hit = _entry_distance(start, vector, visit.voxel, grid)
            break
    count = math.floor(boundary / distance_step)
    if hit is not None:
        count = min(count, math.ceil(hit / distance_step) - 1)
    count = max(0, count)
    while not _checked_prefix(
        start, vector, count * distance_step, grid, deadline, counters
    ):
        if count == 0:
            raise ValueError("Ray origin touches an occupied voxel")
        count -= 1
    # Usually one check. Never use sampled endpoints as a substitute for the
    # prefix check: an earlier thin obstacle may lie between two endpoints.
    while _checked_prefix(
        start, vector, (count + 1) * distance_step, grid, deadline, counters
    ):
        count += 1
    return count * distance_step


def ray_free_length_reference(
    point: Point,
    direction: Point,
    grid: OccupancyMap,
    distance_step: float,
    deadline: Deadline,
    counters: SearchCounters,
) -> float:
    """Evaluate each entire prefix naively, only as a small-map test reference."""
    if not math.isfinite(distance_step) or distance_step <= 0:
        raise ValueError("Ray distance step must be finite and positive")
    start, vector, _ = _ray_domain(point, direction, grid)
    if not _checked_prefix(start, vector, 0, grid, deadline, counters):
        raise ValueError("Ray origin touches an occupied voxel")
    count = 1
    while _checked_prefix(
        start, vector, count * distance_step, grid, deadline, counters
    ):
        count += 1
    return (count - 1) * distance_step


def _tangent(
    point: Point,
    previous_direction: Point,
    direction: Point,
    previous_length: float,
    length: float,
    parameters: SamplingParameters,
) -> Point | None:
    if abs(length - previous_length) <= parameters.length_threshold:
        return None
    chosen = direction if length > previous_length else previous_direction
    distance = min(length, previous_length) + parameters.forward_distance
    return tuple(float(a + distance * b) for a, b in zip(point, chosen, strict=True))


def tangent_candidates(
    point: Point,
    goal: Point,
    grid: OccupancyMap,
    parameters: SamplingParameters,
    deadline: Deadline,
    counters: SearchCounters,
) -> Iterator[Point]:
    """Yield algorithm-3 candidates, without adding an unpublished parent filter.

    The phi=0 plane is traversed but yields no candidates, as in line 13.
    Theta includes its upper lattice value; the angular seam is not wrapped.
    Yielding incrementally lets the caller enforce its node budget inside rays.
    """
    for phi_degrees in angle_values(360, parameters.phi_step_degrees, inclusive=False):
        previous_length = None
        previous_direction = None
        for theta_degrees in angle_values(
            parameters.half_cone_degrees,
            parameters.theta_step_degrees,
            inclusive=True,
        ):
            deadline.check()
            direction = find_direction(
                point, goal, math.radians(phi_degrees), math.radians(theta_degrees)
            )
            length = ray_free_length(
                point, direction, grid, parameters.distance_step, deadline, counters
            )
            if phi_degrees > 0 and previous_length is not None:
                assert previous_direction is not None
                candidate = _tangent(
                    point,
                    previous_direction,
                    direction,
                    previous_length,
                    length,
                    parameters,
                )
                if candidate is not None:
                    yield candidate
            previous_length, previous_direction = length, direction


def planar_tangent_candidates(
    point: Point,
    grid: OccupancyMap,
    parameters: SamplingParameters,
    deadline: Deadline,
    counters: SearchCounters,
) -> Iterator[Point]:
    """Yield algorithm-2 XY-plane candidates at the supplied fixed physical z."""
    previous_length = None
    previous_direction = None
    for degrees in angle_values(360, parameters.theta_step_degrees, inclusive=False):
        deadline.check()
        radians = math.radians(degrees)
        direction = (math.cos(radians), math.sin(radians), 0.0)
        length = ray_free_length(
            point, direction, grid, parameters.distance_step, deadline, counters
        )
        if previous_length is not None:
            assert previous_direction is not None
            candidate = _tangent(
                point,
                previous_direction,
                direction,
                previous_length,
                length,
                parameters,
            )
            if candidate is not None:
                yield candidate
        previous_length, previous_direction = length, direction
