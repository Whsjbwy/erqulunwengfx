"""Transparent linear nearest neighbors and consistent rewiring costs."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import Point


class Tree:
    """Preallocated coordinates; one parent and explicit children per vertex."""

    def __init__(self, root: Point, capacity: int) -> None:
        self.coordinates = np.empty((capacity, 3), dtype=float)
        self.coordinates[0] = root
        self.parents = [-1]
        self.costs = [0.0]
        self.children: list[set[int]] = [set()]

    def __len__(self) -> int:
        """Return actual inserted vertices, not the allocated capacity."""
        return len(self.parents)

    def point(self, index: int) -> Point:
        """Return immutable coordinates for published path snapshots."""
        return tuple(float(value) for value in self.coordinates[index])

    def distances(self, point: Point) -> np.ndarray:
        """Return exact Euclidean distances to all current vertices."""
        difference = self.coordinates[: len(self)] - point
        return np.sqrt(np.einsum("ij,ij->i", difference, difference))

    def nearest(self, point: Point) -> int:
        """Resolve equal distances by insertion order."""
        return int(np.argmin(self.distances(point)))

    def add(self, point: Point, parent: int) -> int:
        """Insert one edge and initialize its true accumulated length."""
        index = len(self)
        if index >= len(self.coordinates):
            raise ValueError("Tree capacity exhausted")
        self.coordinates[index] = point
        self.parents.append(parent)
        self.costs.append(self.costs[parent] + math.dist(self.point(parent), point))
        self.children.append(set())
        self.children[parent].add(index)
        return index

    def path(self, index: int) -> list[Point]:
        """Snapshot a root path; rewiring never mutates an archived path."""
        reverse = []
        while index >= 0:
            reverse.append(self.point(index))
            index = self.parents[index]
        return reverse[::-1]

    def reparent(self, index: int, parent: int) -> int:
        """Atomically update every descendant cost; reject any cycle.

        The bounded update is not interrupted halfway by a deadline. Any
        resulting atomic overrun is recorded and cannot publish a late path.
        """
        ancestor = parent
        while ancestor >= 0:
            if ancestor == index:
                raise ValueError("Rewire would create a cycle")
            ancestor = self.parents[ancestor]
        if index == 0:
            raise ValueError("The root cannot be rewired")
        self.children[self.parents[index]].remove(index)
        self.parents[index] = parent
        self.children[parent].add(index)
        pending = [index]
        updated = 0
        while pending:
            child = pending.pop()
            source = self.parents[child]
            self.costs[child] = self.costs[source] + math.dist(
                self.point(source), self.point(child)
            )
            updated += 1
            pending.extend(sorted(self.children[child], reverse=True))
        return updated


def steer(source: Point, target: Point, step: float) -> Point:
    """Move no farther than step in physical coordinates, preserving targets."""
    distance = math.dist(source, target)
    if distance <= step:
        return target
    return tuple(
        float(value)
        for value in np.asarray(source)
        + (np.asarray(target) - source) * (step / distance)
    )
