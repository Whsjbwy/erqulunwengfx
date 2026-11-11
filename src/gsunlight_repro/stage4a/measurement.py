"""Light aggregate geometry observations and an optional exact ray cache."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import patch

from .. import paper_planner, rrt_connect, sampling
from ..collision_checker import PathValidation, validate_path
from ..map_reader import OccupancyMap, Point
from ..planning import Deadline, SearchCounters


class Measurement:
    """Count API requests and disjoint busy intervals without per-voxel timers.

    Ray busy intervals include their nested prefix checks. They are combined
    with outside-ray validation, rather than adding nested times twice.
    A cache belongs to one read-only map and uses exact floating coordinates.
    """

    def __init__(self, grid: OccupancyMap, cache_size: int = 0) -> None:
        if cache_size and grid.occupancy.flags.writeable:
            raise ValueError("A cached map must be read-only")
        self.grid = grid
        self.cache_size = cache_size
        self.cache: OrderedDict[tuple, float] = OrderedDict()
        self.ray_queries = 0
        self.cache_hits = 0
        self.oracle_calls = 0
        self.queried_segments = 0
        self.geometry_busy_s = 0.0
        self.depth = 0
        self.original_ray = sampling.ray_free_length
        self.original_trace = sampling.trace_voxel_segment

    def check_path(self, points: Any, grid: OccupancyMap) -> PathValidation:
        """Call the unchanged continuous validator and count its segment work."""
        started = time.perf_counter()
        top = self.depth == 0
        self.depth += 1
        self.oracle_calls += 1
        try:
            verdict = validate_path(points, grid)
            self.queried_segments += verdict.checked_segments
            return verdict
        finally:
            self.depth -= 1
            if top:
                self.geometry_busy_s += time.perf_counter() - started

    def trace(self, *args: Any, **kwargs: Any) -> Any:
        """Count the sampler's whole-ray query, without timing every voxel."""
        self.oracle_calls += 1
        self.queried_segments += 1
        return self.original_trace(*args, **kwargs)

    def ray(
        self,
        point: Point,
        direction: Point,
        grid: OccupancyMap,
        distance_step: float,
        deadline: Deadline,
        counters: SearchCounters,
    ) -> float:
        """Reuse only completed exact queries on this bound immutable map."""
        deadline.check()
        if grid is not self.grid:
            raise ValueError("Ray cache/measurement cannot cross map instances")
        self.ray_queries += 1
        key = (tuple(point), tuple(direction), distance_step)
        if self.cache_size and key in self.cache:
            self.cache_hits += 1
            counters.sampled_nodes = int(counters.sampled_nodes or 0) + 1
            self.cache.move_to_end(key)
            return self.cache[key]
        started = time.perf_counter()
        self.depth += 1
        try:
            length = self.original_ray(
                point, direction, grid, distance_step, deadline, counters
            )
        finally:
            self.depth -= 1
            self.geometry_busy_s += time.perf_counter() - started
        if self.cache_size:
            self.cache[key] = length
            if len(self.cache) > self.cache_size:
                self.cache.popitem(last=False)
        return length

    @contextmanager
    def installed(self) -> Iterator[Measurement]:
        """Restore every imported function reference, even on cancellation."""
        with ExitStack() as stack:
            for module in (paper_planner, rrt_connect, sampling):
                stack.enter_context(
                    patch.object(module, "validate_path", self.check_path)
                )
            stack.enter_context(
                patch.object(sampling, "trace_voxel_segment", self.trace)
            )
            stack.enter_context(patch.object(sampling, "ray_free_length", self.ray))
            yield self

    def metrics(self) -> dict[str, int | float]:
        """Expose logical rays, physical query work and nonnested busy time."""
        return {
            "logical_ray_queries": self.ray_queries,
            "physical_ray_evaluations": self.ray_queries - self.cache_hits,
            "ray_cache_hits": self.cache_hits,
            "oracle_query_calls": self.oracle_calls,
            "oracle_queried_segments": self.queried_segments,
            "ray_and_collision_busy_s": self.geometry_busy_s,
        }
