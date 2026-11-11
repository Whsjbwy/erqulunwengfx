"""Publish only paths certified before the shared deadline."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..collision_checker import PathValidation
from ..map_reader import OccupancyMap, Point
from ..metrics import endpoints_match, path_length
from ..planning import BudgetExceeded
from .budget import Budget


class Incumbent:
    """Maintain raw and optionally shortened histories using the same safety rule."""

    def __init__(
        self,
        grid: OccupancyMap,
        start: Point,
        goal: Point,
        budget: Budget,
        checker: Callable[[Any, OccupancyMap], PathValidation],
    ) -> None:
        self.grid, self.start, self.goal = grid, start, goal
        self.budget, self.checker = budget, checker
        self.history: list[dict[str, Any]] = []
        self.raw_history: list[dict[str, Any]] = []
        self.best_path: list[Point] | None = None
        self.raw_best_path: list[Point] | None = None
        self.validation_s = 0.0
        self.shortcut_s = 0.0
        self.candidates_verified = 0
        self.invalid_candidates = 0
        self.post_interrupted = 0
        self.attempt_index = 0
        self.source_seed = 0
        self.paths: list[list[Point]] = []
        self.path_ids: dict[tuple[Point, ...], int] = {}

    def publish(self, path: list[Point], kind: str) -> None:
        """Keep the actual completion timestamp; never backfill a checkpoint."""
        length = path_length(path)
        now = self.budget.elapsed
        if now > self.budget.seconds:
            return
        improves_raw = kind == "raw" and (
            not self.raw_history or length < self.raw_history[-1]["length"]
        )
        improves_best = not self.history or length < self.history[-1]["length"]
        if not (improves_raw or improves_best):
            return
        key = tuple(path)
        if key not in self.path_ids:
            self.path_ids[key] = len(self.paths)
            self.paths.append(list(path))
        event = {
            "time_s": now,
            "length": length,
            "kind": kind,
            "path_id": self.path_ids[key],
            "attempt_index": self.attempt_index,
            "source_seed": self.source_seed,
        }
        if improves_raw:
            self.raw_history.append(event)
            self.raw_best_path = list(path)
        if improves_best:
            self.history.append(event)
            self.best_path = list(path)

    def shortcut(self, path: list[Point]) -> list[Point]:
        """Use the frozen greedy order with deadline checks between queries."""
        output = [path[0]]
        current = 0
        while current < len(path) - 1:
            selected = current + 1
            for candidate in range(len(path) - 1, current, -1):
                self.budget.check()
                if self.checker([path[current], path[candidate]], self.grid).valid:
                    selected = candidate
                    break
            output.append(path[selected])
            current = selected
        self.budget.check()
        if not self.checker(output, self.grid).valid:
            raise RuntimeError("Shared shortcut produced an invalid path")
        self.budget.check()
        return output

    def accept(self, path: list[Point], *, process: bool = True) -> None:
        """Certify raw coordinates first, then spend remaining time on shortcut."""
        self.budget.check()
        started = time.perf_counter()
        valid = self.checker(path, self.grid).valid and endpoints_match(
            path, self.start, self.goal
        )
        self.validation_s += time.perf_counter() - started
        self.budget.check()
        self.candidates_verified += 1
        if not valid:
            self.invalid_candidates += 1
            raise RuntimeError("A backend candidate failed independent path validation")
        path = [tuple(float(v) for v in p) for p in path]
        self.publish(path, "raw")
        if process:
            started = time.perf_counter()
            try:
                shortened = self.shortcut(path)
                self.publish(shortened, "shortcut")
            except BudgetExceeded:
                self.post_interrupted += 1
                raise
            finally:
                self.shortcut_s += time.perf_counter() - started

    def checkpoints(self, times: list[float]) -> list[dict[str, Any]]:
        """Use only events actually completed no later than each requested time."""
        rows = []
        for cutoff in times:
            events = [x for x in self.history if x["time_s"] <= cutoff]
            raw = [x for x in self.raw_history if x["time_s"] <= cutoff]
            rows.append(
                {
                    "checkpoint_s": cutoff,
                    "valid": bool(events),
                    "best_length": events[-1]["length"] if events else None,
                    "raw_best_length": raw[-1]["length"] if raw else None,
                    "best_kind": events[-1]["kind"] if events else None,
                }
            )
        return rows
