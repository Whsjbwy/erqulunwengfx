"""Descriptive polyline features; sharp corners are not finite curvature."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import Point
from .tracking import wrap


def describe_path(path: list[Point], start: Point, goal: Point) -> dict:
    """Describe demands on the fixed initial attitude without proving infeasibility."""
    edges = np.diff(np.asarray(path, dtype=float), axis=0)
    lengths = np.linalg.norm(edges, axis=1)
    edges, lengths = edges[lengths > 1e-12], lengths[lengths > 1e-12]
    if not len(edges):
        return {
            "nonzero_segments": 0,
            "max_segment_pitch_deg": None,
            "max_corner_turn_deg": None,
            "initial_yaw_mismatch_deg": None,
        }
    horizontal = np.linalg.norm(edges[:, :2], axis=1)
    inclinations = np.degrees(np.arctan2(edges[:, 2], horizontal))
    turns = np.degrees(
        np.arctan2(
            np.linalg.norm(np.cross(edges[:-1], edges[1:]), axis=1),
            np.einsum("ij,ij->i", edges[:-1], edges[1:]),
        )
    )
    initial_yaw = math.atan2(goal[1] - start[1], goal[0] - start[0])
    return {
        "nonzero_segments": len(edges),
        "shortest_segment_m": float(np.min(lengths)),
        "max_segment_pitch_deg": float(np.max(np.abs(inclinations))),
        "segments_above_assumed_20deg_pitch": int(
            np.count_nonzero(np.abs(inclinations) > 20)
        ),
        "max_corner_turn_deg": float(np.max(turns)) if len(turns) else 0.0,
        "corners_above_1deg": int(np.count_nonzero(turns > 1)),
        "initial_yaw_mismatch_deg": abs(
            math.degrees(wrap(math.atan2(edges[0, 1], edges[0, 0]) - initial_yaw))
        )
        if horizontal[0] > 1e-12
        else None,
        "initial_pitch_mismatch_deg": abs(float(inclinations[0])),
    }
