"""Standard horizontal circular fillets with conservative continuous validation."""

from __future__ import annotations

import math

import numpy as np

from ..metrics import path_length
from ..stage5a.tracking import State, chord_error_bound, integrate


def fillet(path: list, geometry, turn_radius: float) -> dict:
    """Construct tangent circle corners; reject unsupported 3D or short edges.

    This is a bounded horizontal reference, not a new general 3D smoother.
    Every curved primitive is certified by enlarged chords, not sparse points.
    """
    points = np.array(path, dtype=float)
    if np.ptp(points[:, 2]) > 1e-8:
        return {"status": "unsupported_nonhorizontal", "valid": False}
    edges = np.diff(points, axis=0)
    lengths = np.linalg.norm(edges, axis=1)
    if np.any(lengths <= 1e-10):
        return {"status": "degenerate_edge", "valid": False}
    unit = edges / lengths[:, None]
    offsets = np.zeros(len(points))
    angles = np.zeros(len(points))
    for i in range(1, len(points) - 1):
        angles[i] = math.acos(float(np.clip(unit[i - 1] @ unit[i], -1, 1)))
        if angles[i] >= math.pi - 1e-8:
            return {"status": "reversal", "valid": False}
        offsets[i] = turn_radius * math.tan(angles[i] / 2)
    if np.any(offsets[:-1] + offsets[1:] > lengths + 1e-10):
        return {"status": "insufficient_segment_length", "valid": False}
    shown = [points[0].tolist()]
    current, total, arc_count = points[0], 0.0, 0
    maximum_enclosure = 0.0
    for i in range(1, len(points) - 1):
        entry = points[i] - offsets[i] * unit[i - 1]
        exit_point = points[i] + offsets[i] * unit[i]
        if not geometry.segment(current, entry).valid:
            return {"status": "line_safety_reject", "valid": False}
        total += math.dist(current, entry)
        shown.append(entry.tolist())
        if angles[i] > 1e-8:
            sign = math.copysign(1.0, np.cross(unit[i - 1], unit[i])[2])
            duration = turn_radius * angles[i]
            yaw = math.atan2(unit[i - 1, 1], unit[i - 1, 0])
            state = State(tuple(entry), yaw, 0.0, 1.0)
            count = max(1, math.ceil(duration / 0.1))
            dt = duration / count
            for _ in range(count):
                following = integrate(state, sign / turn_radius, 0.0, dt)
                enclosure = chord_error_bound(1.0, sign / turn_radius, 0.0, dt)
                maximum_enclosure = max(maximum_enclosure, enclosure)
                if not geometry.segment(
                    state.position, following.position, extra_radius=enclosure
                ).valid:
                    return {"status": "arc_safety_reject", "valid": False}
                state = following
                shown.append(list(state.position))
            if math.dist(state.position, exit_point) > 1e-8:
                raise RuntimeError(
                    "Fillet analytic exit does not match tangent geometry"
                )
            total += duration
            arc_count += 1
        current = exit_point
    if not geometry.segment(current, points[-1]).valid:
        return {"status": "line_safety_reject", "valid": False}
    total += math.dist(current, points[-1])
    shown.append(points[-1].tolist())
    return {
        "status": "certified_horizontal",
        "valid": True,
        "length_m": total,
        "raw_length_m": path_length(path),
        "max_curvature_m_inv": 1 / turn_radius if arc_count else 0.0,
        "max_pitch_deg": 0.0,
        "max_yaw_rate_rad_s_at_v1": 1 / turn_radius,
        "maximum_chord_enclosure_m": maximum_enclosure,
        "arc_count": arc_count,
        "display_points": shown,
    }
