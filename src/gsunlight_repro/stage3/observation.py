"""Restore-on-exit observations of the frozen paper controller."""

from __future__ import annotations

import json
import math
import time
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .. import paper_planner as paper
from ..collision_checker import validate_path
from ..metrics import endpoints_match, path_length
from ..planning import PlanResult, SearchCounters


class FirstValidFound(Exception):
    """Explicit cancellation for the separately labeled first-solution policy."""


class Observation:
    """Record verified incumbents and bounded candidate events in map units.

    No RNG is used and every wrapped computation is invoked exactly once.
    Added observation cost is real and can affect a wall-clock-limited run;
    fixed-work equivalence and profiling controls are therefore mandatory.
    """

    def __init__(
        self,
        grid: Any,
        start: Any,
        goal: Any,
        parameters: dict[str, Any],
        event_path: Path | None = None,
        stop_first: bool = False,
        event_limit: int = 20000,
    ) -> None:
        self.grid, self.start, self.goal = grid, start, goal
        self.parameters = parameters
        self.event_path, self.stop_first = event_path, stop_first
        self.event_limit = event_limit
        self.started = 0.0
        self.history: list[dict[str, Any]] = []
        self.first_path: list | None = None
        self.first_nodes: int | None = None
        self.best_length = math.inf
        self.counters = SearchCounters()
        self.opened: Any = None
        self.sun: Any = None
        self.nodes: list = []
        self.stream: Any = None
        self.event_count = 0
        self.dropped_events = 0
        self.validation_seconds = 0.0

    def event(self, kind: str, node: Any = None, **extra: Any) -> None:
        """Write only candidate-level events; explicitly count any truncated rows."""
        if self.stream is None:
            return
        if self.event_count >= self.event_limit:
            self.dropped_events += 1
            return
        record = {"event": kind, "time_s": time.perf_counter() - self.started, **extra}
        if node is not None:
            point = tuple(float(x) for x in node.point)
            alpha = self.parameters.get("alpha", 0.5)
            record.update(
                node_id=node.node_id,
                parent_id=node.parent_id,
                point=point,
                g=node.accumulated_cost,
                heuristic=node.accumulated_cost + alpha * math.dist(point, self.goal),
                grid=self.opened.cell_key(point),
                spatial_bin=tuple(math.floor(x / 20) for x in point),
            )
        self.stream.write(json.dumps(record) + "\n")
        self.event_count += 1

    @contextmanager
    def installed(self):
        """Install local observers, restoring all baseline globals even on errors."""
        original_deadline = paper.Deadline
        original_choose = paper._choose_sun
        original_free = paper._free
        original_reconstruct = paper._reconstruct
        original_grid = paper.GridCandidates
        observer = self

        def deadline(seconds):
            value = original_deadline(seconds)
            observer.started = value.started
            return value

        def free(first, second, grid, counters):
            observer.counters = counters
            return original_free(first, second, grid, counters)

        def choose(*args):
            value = original_choose(*args)
            observer.sun = value
            observer.event("selected", value)
            return value

        def reconstruct(nodes, node, goal):
            path = original_reconstruct(nodes, node, goal)
            observer.nodes = nodes
            before = time.perf_counter()
            valid = validate_path(path, observer.grid).valid and endpoints_match(
                path, observer.start, observer.goal
            )
            observer.validation_seconds += time.perf_counter() - before
            if valid:
                length = path_length(path)
                if observer.first_path is None:
                    observer.first_path = [tuple(p) for p in path]
                    observer.first_nodes = observer.counters.expanded_nodes
                if length < observer.best_length:
                    observer.best_length = length
                    observer.history.append(
                        {
                            "time_s": time.perf_counter() - observer.started,
                            "length": length,
                            "expanded_nodes": observer.counters.expanded_nodes,
                            "graph_nodes": len(nodes) + 1,
                        }
                    )
                if observer.stop_first:
                    raise FirstValidFound()
            return path

        class ObservedGrid(original_grid):
            def __init__(self, *args):
                super().__init__(*args)
                observer.opened = self

            def insert(self, node):
                previous = (
                    {i: self._open[i] for i in self.members(node.point)}
                    if observer.stream
                    else {}
                )
                removed = super().insert(node)
                observer.event("inserted", node)
                if removed is not None and observer.stream:
                    observer.event(
                        "evicted",
                        node if removed == node.node_id else previous[removed],
                        reason="capacity_tail",
                    )
                return removed

            def remove(self, node_id):
                node = super().remove(node_id)
                observer.event("expanded", node)
                return node

        with ExitStack() as stack:
            if self.event_path:
                self.event_path.parent.mkdir(parents=True, exist_ok=True)
                self.stream = stack.enter_context(
                    self.event_path.open("x", encoding="utf-8")
                )
            for name, value in {
                "Deadline": deadline,
                "_free": free,
                "_choose_sun": choose,
                "_reconstruct": reconstruct,
                "GridCandidates": ObservedGrid,
            }.items():
                stack.enter_context(patch.object(paper, name, value))
            try:
                yield self
            finally:
                if self.opened is not None:
                    for node in self.opened.ordered():
                        self.event("open_at_stop", node)
                self.stream = None

    def first_result(self, method: str, limits: Any) -> PlanResult:
        """Return the explicitly changed stopping-policy result, never paper-v1."""
        self.counters.final_open_nodes = len(self.opened)
        return PlanResult(
            method,
            "stage3-stop-first-v1",
            "ok",
            "first_valid_policy",
            True,
            self.first_path,
            time.perf_counter() - self.started,
            self.counters,
            {**self.parameters, "limits": asdict(limits), "stop_on_first_valid": True},
        )

    def metrics(self, result: PlanResult, budget: float) -> dict[str, Any]:
        """Report actual event times; never substitute final time or length."""
        first = self.history[0] if self.history else {}
        last = self.history[-1] if self.history else {}
        return {
            "time_to_first_valid_path_s": first.get("time_s"),
            "first_valid_path_length": first.get("length"),
            "first_valid_expanded_nodes": self.first_nodes,
            "last_valid_path_length": last.get("length"),
            "time_to_last_improvement_s": last.get("time_s"),
            "incumbent_history": self.history,
            "valid_solution_found_by_30s": bool(first and first["time_s"] <= 30),
            "valid_solution_found_by_budget": bool(first and first["time_s"] <= budget),
            "normal_completion_by_30s": result.status == "ok"
            and result.search_seconds <= 30,
            "search_stop_reason": result.termination_reason,
            "observer_validation_seconds": self.validation_seconds,
            "candidate_events_recorded": self.event_count,
            "candidate_events_dropped": self.dropped_events,
        }
