"""Minimal latched terminal capture around the unchanged 5A-E LOS guidance."""

from __future__ import annotations

import math

import numpy as np

from ..stage5a.tracking import Route, State
from ..stage5ae.guidance import LOS


class TerminalLOS:
    """Retain normal LOS, then point to the finite endpoint with one switch.

    The desired direction is correct after overshoot; bounded actuators and
    fixed forward speed do not imply immediate or global distance convergence.
    """

    def __init__(
        self, route: Route, lookahead: float, terminal_distance: float
    ) -> None:
        if not math.isfinite(terminal_distance) or terminal_distance <= 0:
            raise ValueError("Terminal distance must be positive and finite")
        self.base = LOS(route, lookahead)
        self.goal = route.points[-1]
        nonzero = np.flatnonzero(route.lengths > 1e-12)
        last_start = route.cumulative[nonzero[-1]] if len(nonzero) else 0.0
        self.switch_progress = max(last_start, route.cumulative[-1] - terminal_distance)
        self.terminal = False

    def command(self, state: State, dt: float) -> tuple[np.ndarray, dict]:
        """Test pre-update progress and latch; never alter frozen normal guidance."""
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError("Control period must be positive and finite")
        target, details = self.base.command(state, dt)
        switched = bool(
            not self.terminal
            and details["reference_progress_m"] >= self.switch_progress
        )
        self.terminal |= switched
        jump = 0.0
        if switched:
            before, after = target - state.position, self.goal - state.position
            denominator = np.linalg.norm(before) * np.linalg.norm(after)
            if denominator > 0:
                jump = math.degrees(
                    math.acos(float(np.clip(before @ after / denominator, -1, 1)))
                )
        return (self.goal.copy() if self.terminal else target), {
            **details,
            "terminal_mode": self.terminal,
            "terminal_switch": switched,
            "switch_direction_jump_deg": jump,
        }
