"""Shared result and budget types for independent stage-two planners."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from .map_reader import Point


class BudgetExceeded(RuntimeError):
    """Signal a genuine planning deadline or explicit resource limit."""


@dataclass(frozen=True, slots=True)
class PlanningLimits:
    """Per-run CPU search limits; loading and final validation are separate."""

    time_limit: float = 30.0
    max_nodes: int = 100_000
    max_iterations: int = 10_000

    def __post_init__(self) -> None:
        if not math.isfinite(self.time_limit) or self.time_limit <= 0:
            raise ValueError("Search time limit must be finite and positive")
        if self.max_nodes < 2 or self.max_iterations < 1:
            raise ValueError("Node and iteration limits must be positive")


class Deadline:
    """Monotonic per-search deadline, including planner data initialization."""

    def __init__(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Deadline duration must be finite and positive")
        self.started = time.perf_counter()
        self.ends = self.started + seconds

    def check(self) -> None:
        """Raise ``BudgetExceeded`` once the allotted wall time has elapsed."""
        if time.perf_counter() >= self.ends:
            raise BudgetExceeded("time_budget")

    @property
    def elapsed(self) -> float:
        """Return elapsed seconds since planner invocation."""
        return time.perf_counter() - self.started


@dataclass(slots=True)
class SearchCounters:
    """Observable search events; unavailable author counters remain null."""

    generated_candidates: int | None = 0
    valid_candidates: int | None = 0
    collision_filtered: int | None = 0
    capacity_evicted: int | None = 0
    expanded_nodes: int | None = 0
    sampled_nodes: int | None = 0
    collision_checks: int | None = 0
    no_candidate_expansions: int | None = 0
    final_open_nodes: int | None = 0


@dataclass(slots=True)
class PlanResult:
    """Reported search result before an independent final safety verdict.

    Coordinates are physical map units, retaining the exact supplied endpoints.
    A returned path does not automatically imply strict validity. ``status``
    distinguishes ok/no_path/timeout/budget_exhausted/invalid_input/error.
    """

    method: str
    version: str
    status: str
    termination_reason: str
    reported_success: bool
    raw_path: list[Point] | None
    search_seconds: float | None
    counters: SearchCounters = field(default_factory=SearchCounters)
    parameters: dict[str, Any] = field(default_factory=dict)
    postprocessed_path: list[Point] | None = None
    events: dict[str, int | str | bool | None] = field(default_factory=dict)
