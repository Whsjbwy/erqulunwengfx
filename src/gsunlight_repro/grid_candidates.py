"""Paper algorithm-5 membership and historical-cost state, independent of VTK."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .map_reader import Point

GridKey = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class CandidateNode:
    """An immutable graph node with physical coordinates and path cost."""

    node_id: int
    point: Point
    accumulated_cost: float
    parent_id: int | None


class GridCandidates:
    """Current open membership with persistent per-cell historical best costs.

    Graph storage belongs to the planner. Removing or evicting an open member
    never destroys a graph node or its parent chain. Cell coordinates use floor
    relative to ``origin``; this capacity grid is not the occupancy voxel grid.
    """

    def __init__(self, origin: Point, side_length: float, capacity: int) -> None:
        if not math.isfinite(side_length) or side_length <= 0:
            raise ValueError("Capacity grid side length must be finite and positive")
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Capacity must be a positive integer")
        if len(origin) != 3 or not all(math.isfinite(value) for value in origin):
            raise ValueError("Capacity grid origin must be a finite triple")
        self.origin = origin
        self.side_length = side_length
        self.capacity = capacity
        self._members: dict[GridKey, list[int]] = {}
        self._history: dict[GridKey, float] = {}
        self._open: dict[int, CandidateNode] = {}

    def cell_key(self, point: Point) -> GridKey:
        """Return the unbounded capacity-cell index of a finite physical point."""
        if len(point) != 3 or not all(math.isfinite(value) for value in point):
            raise ValueError("Candidate coordinates must be a finite triple")
        return tuple(
            math.floor((value - base) / self.side_length)
            for value, base in zip(point, self.origin, strict=True)
        )

    def insert(self, node: CandidateNode) -> int | None:
        """Insert at index 0/1 and return the tail-evicted ID, if any.

        Only strictly shorter costs update history. Equal-cost nodes use index
        1 too, even if the historical best node has already left this grid.
        Duplicate open IDs and invalid costs raise ValueError.
        """
        if node.node_id in self._open:
            raise ValueError("Candidate node is already open")
        if not math.isfinite(node.accumulated_cost) or node.accumulated_cost < 0:
            raise ValueError("Accumulated cost must be finite and nonnegative")
        key = self.cell_key(node.point)
        members = self._members.setdefault(key, [])
        if node.accumulated_cost < self._history.get(key, math.inf):
            members.insert(0, node.node_id)
            self._history[key] = node.accumulated_cost
        else:
            members.insert(1, node.node_id)
        self._open[node.node_id] = node
        if len(members) > self.capacity:
            removed = members.pop()
            del self._open[removed]
            return removed
        return None

    def remove(self, node_id: int) -> CandidateNode:
        """Remove one open member, preserving its cell's historical shortest cost."""
        node = self._open.pop(node_id)
        self._members[self.cell_key(node.point)].remove(node_id)
        return node

    def ordered(self) -> list[CandidateNode]:
        """Return current members sorted by accumulated cost then insertion ID."""
        return sorted(
            self._open.values(), key=lambda node: (node.accumulated_cost, node.node_id)
        )

    def members(self, point: Point) -> tuple[int, ...]:
        """Return a cell's current candidate IDs in algorithm-5 priority order."""
        return tuple(self._members.get(self.cell_key(point), []))

    def historical_best(self, point: Point) -> float:
        """Return historical shortest cost, or infinity for a never-seen cell."""
        return self._history.get(self.cell_key(point), math.inf)

    def __len__(self) -> int:
        """Return the current number of open candidate nodes across all cells."""
        return len(self._open)
