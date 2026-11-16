"""Geometry-preserving subdivision and one explicit terminal-contract variant."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np

from ..map_reader import Point
from ..stage5a.tracking import Route
from ..stage5af import tracking
from ..stage5af.guidance import TerminalLOS


class ArcTerminalLOS(TerminalLOS):
    """Change only the trigger arc; reuse frozen normal and terminal commands."""

    def __init__(
        self, route: Route, lookahead: float, terminal_distance: float
    ) -> None:
        super().__init__(route, lookahead, terminal_distance)
        self.switch_progress = max(0.0, float(route.cumulative[-1]) - terminal_distance)


@contextmanager
def guidance_factory(arc_terminal: bool) -> Iterator[None]:
    """Inject one serial process-local factory and always restore the frozen loop."""
    original = tracking.TerminalLOS
    if original is not TerminalLOS:
        raise RuntimeError("Concurrent or nested guidance injection is forbidden")
    try:
        if arc_terminal:
            tracking.TerminalLOS = ArcTerminalLOS
        yield
    finally:
        tracking.TerminalLOS = original


def subdivide(path: list[Point]) -> list[Point]:
    """Insert exactly one midpoint inside every original nonzero segment."""
    route = Route(path)
    result = [tuple(route.points[0])]
    for start, end in zip(route.points[:-1], route.points[1:], strict=True):
        result.extend((tuple((start + end) / 2), tuple(end)))
    return result


def geometry_equivalence(original: list[Point], divided: list[Point]) -> dict:
    """Certify parent/child segment identity, order and total arc numerically."""
    a, b = Route(original), Route(divided)
    if len(b.points) != 2 * len(a.points) - 1:
        raise ValueError("Subdivision changed the registered vertex count")
    error = float(np.max(np.abs(b.points[::2] - a.points)))
    error = max(
        error,
        float(np.max(np.abs(b.points[1::2] - (a.points[:-1] + a.points[1:]) / 2))),
    )
    length_error = abs(float(a.cumulative[-1] - b.cumulative[-1]))
    if error > 1e-9 or not np.isclose(
        a.cumulative[-1], b.cumulative[-1], rtol=1e-12, atol=1e-9
    ):
        raise ValueError("Subdivision failed geometric equivalence")
    return {
        "geometry_equivalent": True,
        "maximum_vertex_error_m": error,
        "arc_length_difference_m": length_error,
        "original_vertices": len(a.points),
        "subdivided_vertices": len(b.points),
    }
