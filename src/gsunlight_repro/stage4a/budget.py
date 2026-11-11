"""One wall-clock budget shared by planning, validation and shortcut."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..planning import BudgetExceeded


@dataclass(slots=True)
class Budget:
    """Use an injected monotonic clock for deterministic boundary tests."""

    seconds: float
    clock: Callable[[], float] = time.perf_counter
    started: float = field(init=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError("Budget must be positive")
        self.started = self.clock()

    @property
    def elapsed(self) -> float:
        """Return actual elapsed wall time, including an atomic-query overrun."""
        return self.clock() - self.started

    @property
    def remaining(self) -> float:
        """Return the nonnegative allowance for the next operation."""
        return max(0.0, self.seconds - self.elapsed)

    def check(self) -> None:
        """Refuse new work after the common deadline."""
        if self.elapsed >= self.seconds:
            raise BudgetExceeded("time_budget")
