"""Independent finite-body certification and bounded common postprocessing."""

from __future__ import annotations

import time

from ..map_reader import Point
from ..metrics import endpoints_match, path_length
from ..planning import BudgetExceeded
from ..stage4a.budget import Budget
from .geometry import Geometry


class Solutions:
    """Store unique coordinates once and retain only actual certified improvements."""

    def __init__(
        self, geometry: Geometry, start: Point, goal: Point, budget: Budget
    ) -> None:
        self.geometry, self.start, self.goal, self.budget = (
            geometry,
            start,
            goal,
            budget,
        )
        self.paths: list[list[Point]] = []
        self.path_ids: dict[tuple[Point, ...], int] = {}
        self.history: list[dict] = []
        self.raw_history: list[dict] = []
        self.validation_s = 0.0
        self.shortcut_s = 0.0
        self.reported_candidates = 0
        self.post_interrupted = 0

    def _publish(self, path: list[Point], kind: str) -> None:
        length = path_length(path)
        now = self.budget.elapsed
        if now > self.budget.seconds:
            return
        raw_improved = kind == "raw" and (
            not self.raw_history or length < self.raw_history[-1]["length"]
        )
        improved = not self.history or length < self.history[-1]["length"]
        if not (raw_improved or improved):
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
        }
        if raw_improved:
            self.raw_history.append(event)
        if improved:
            self.history.append(event)

    def accept(self, path: list[Point]) -> None:
        """Certify each raw improvement first; a postprocess timeout preserves it."""
        self.reported_candidates += 1
        self.budget.check()
        if (
            self.raw_history
            and path_length(path) >= self.raw_history[-1]["length"] - 1e-12
        ):
            return
        started = time.perf_counter()
        try:
            valid = self.geometry.path(path).valid and endpoints_match(
                path, self.start, self.goal
            )
        finally:
            self.validation_s += time.perf_counter() - started
        if not valid:
            raise RuntimeError("Backend reported an unsafe finite-body path")
        self.budget.check()
        self._publish(path, "raw")
        started = time.perf_counter()
        try:
            shortened = [path[0]]
            current = 0
            while current < len(path) - 1:
                selected = current + 1
                for candidate in range(len(path) - 1, current, -1):
                    self.budget.check()
                    if self.geometry.segment(path[current], path[candidate]).valid:
                        selected = candidate
                        break
                shortened.append(path[selected])
                current = selected
            if not self.geometry.path(shortened).valid:
                raise RuntimeError("Common finite-body shortcut failed validation")
            self.budget.check()
            self._publish(shortened, "shortcut")
        except BudgetExceeded:
            self.post_interrupted += 1
            raise
        finally:
            self.shortcut_s += time.perf_counter() - started

    def checkpoints(self, cutoffs: list[float]) -> list[dict]:
        """Never credit a solution certified after its requested time point."""
        output = []
        for cutoff in cutoffs:
            eligible = [event for event in self.history if event["time_s"] <= cutoff]
            output.append(
                {
                    "checkpoint_s": cutoff,
                    "valid": bool(eligible),
                    "best_length": eligible[-1]["length"] if eligible else None,
                }
            )
        return output
