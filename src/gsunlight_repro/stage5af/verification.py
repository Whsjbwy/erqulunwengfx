"""Analytic and frozen-output acceptance before any development replay."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.maps import Scene, read_config
from ..stage5a.tracking import Route, State
from ..stage5ae.guidance import LOS
from ..stage5ae.tracking import simulate as frozen
from ..stage5ar.audit import check_trace
from ..stage5ar.p0 import empty_scene
from ..stage5ar.replay import compare_frozen
from .guidance import TerminalLOS
from .storage import check_prefix
from .tracking import simulate


def command_cases() -> list[dict]:
    """Check direction after overshoot and exact unchanged guidance before entry."""
    rows = []
    for name, path, position in (
        ("overshoot", [(0, 0, 0), (10, 0, 0)], (11, 0, 0)),
        ("short_last", [(0, 0, 0), (10, 0, 0), (10.01, 0, 0)], (11, 0, 0)),
        ("zero_last", [(0, 0, 0), (10, 0, 0), (10, 0, 0)], (11, 0, 0)),
        ("all_zero", [(10, 0, 0), (10, 0, 0)], (11, 0, 0)),
        ("up", [(0, 0, 0), (10, 0, 2)], (11, 0, 2.2)),
        ("down", [(0, 0, 2), (10, 0, 0)], (11, 0, -0.2)),
    ):
        route = Route(path)
        old = LOS(route, 2.0)
        new = TerminalLOS(route, 2.0, 2.0)
        old.progress = route.cumulative[-1]
        new.base.progress = route.cumulative[-1]
        state = State(position, 0.0, 0.0, 1.0)
        a, _ = old.command(state, 0.1)
        b, detail = new.command(state, 0.1)
        direction = route.points[-1] - position
        old_dot = float((a - position) @ direction)
        new_dot = float((b - position) @ direction)
        if new_dot <= 0 or not detail["terminal_switch"]:
            raise ValueError("Terminal direction acceptance failed")
        _, second = new.command(state, 0.1)
        if second["terminal_switch"] or not second["terminal_mode"]:
            raise ValueError("Terminal latch oscillated")
        rows.append(
            {"case": name, "old_dot": old_dot, "corrected_dot": new_dot, "switches": 1}
        )
    folded = Route([(0, 0, 0), (20, 0, 0), (20, 10, 0), (1, 0, 0)])
    old, new = LOS(folded, 2.0), TerminalLOS(folded, 2.0, 2.0)
    state = State((0, 0, 0), 0.0, 0.0, 1.0)
    a, _ = old.command(state, 0.1)
    b, detail = new.command(state, 0.1)
    if detail["terminal_mode"] or not np.array_equal(a, b):
        raise ValueError("Endpoint proximity caused premature folded-route switch")
    rows.append({"case": "folded_no_early_switch", "passed": True})
    return rows


def acceptance() -> dict:
    """Run actual positive/negative model cases, independent checks and parity."""
    vehicle = read_config("stage5a_protocol.json")
    settings = read_config("stage5af_protocol.json")
    cases = []
    for name, start, goal in (
        ("line", (8, 8, 8), (38, 8, 8)),
        ("small_offset", (8, 8, 8), (38, 9, 8)),
        ("up", (8, 8, 8), (38, 8, 13)),
        ("down", (8, 8, 13), (38, 8, 8)),
        ("very_short", (8, 8, 8), (8.01, 8, 8)),
        ("zero_length", (8, 8, 8), (8, 8, 8)),
    ):
        scene = empty_scene(start, goal)
        cases.append((name, scene, [start, goal], True, None))
    theta = np.linspace(0, math.pi / 4, 81)
    arc = [(8 + 30 * math.sin(a), 8 + 30 * (1 - math.cos(a)), 10.0) for a in theta]
    cases.append(("radius30_arc", empty_scene(arc[0], arc[-1]), arc, True, None))
    scene = empty_scene((8, 8, 8), (38, 8, 8))
    cases.append(
        (
            "misaligned",
            scene,
            [scene.start, scene.goal],
            False,
            State(scene.start, math.pi, 0.0, 1.0),
        )
    )
    sharp = Scene(
        {"family": "analytic"},
        OccupancyMap(np.zeros((60, 45, 25), dtype=bool)),
        None,
        (5, 10, 6),
        (45, 10, 6),
        None,
    )
    sharp.grid.occupancy[19:31, :25, :12] = True
    cases.append(
        (
            "sharp_obstacle",
            sharp,
            [
                sharp.start,
                (17, 10, 6),
                (17, 28, 6),
                (33, 28, 6),
                (33, 10, 6),
                sharp.goal,
            ],
            False,
            None,
        )
    )
    # Valid references whose terminal corner cuts toward an obstacle/ceiling.
    obstacle = empty_scene((8, 8, 8), (38, 8, 8))
    obstacle.grid.occupancy[35:37, 9:12, 6:10] = True
    cases.append(
        (
            "terminal_obstacle",
            obstacle,
            [obstacle.start, (34, 13, 8), (38, 13, 8), obstacle.goal],
            False,
            None,
        )
    )
    band = empty_scene((8, 8, 8), (38, 8, 11))
    ceiling = np.zeros(band.grid.shape, dtype=bool)
    ceiling[:, :, 12:] = True
    band.ceiling = OccupancyMap(ceiling)
    cases.append(("mission_boundary", band, [band.start, band.goal], False, None))
    cases = [(*case, 0.0) for case in cases]
    terminal_obstacle = empty_scene((8, 8, 8), (38, 8, 8))
    terminal_obstacle.grid.occupancy[40:42, 7:10, 6:11] = True
    cases.append(
        (
            "active_terminal_obstacle",
            terminal_obstacle,
            [terminal_obstacle.start, terminal_obstacle.goal],
            False,
            State((38.8, 8, 8), 0.0, 0.0, 1.0),
            30.0,
        )
    )
    terminal_band = empty_scene((8, 8, 10), (38, 8, 10))
    terminal_band.ceiling = OccupancyMap(ceiling.copy())
    cases.append(
        (
            "active_terminal_ceiling",
            terminal_band,
            [terminal_band.start, terminal_band.goal],
            False,
            State((38, 8, 10.9), 0.0, math.radians(20), 1.0),
            30.0,
        )
    )
    rows = []
    maximum = 0.0
    for name, scene, path, expected, initial, progress in cases:
        result = simulate(
            path,
            scene,
            vehicle,
            0.0,
            settings,
            initial=initial,
            initial_progress=progress,
        )
        if result.summary["execution_success"] != expected:
            raise ValueError(f"Analytic expected outcome failed: {name}")
        audit = check_trace(
            {"summary": result.summary, "trace": result.trace}, vehicle["kinematics"]
        )
        maximum = max(maximum, audit["max_rk4_error_m"])
        if name.startswith("active_terminal_"):
            expected_class = (
                "swept_safety_reject"
                if name.endswith("obstacle")
                else "mission_band_reject"
            )
            if (
                result.summary["terminal_switch_index"] != 0
                or result.summary["primary_class"] != expected_class
            ):
                raise ValueError("Active terminal mode bypassed continuous safety")
        if initial is None:
            previous = frozen(
                path, scene, vehicle, 0.0, {"kind": "los3d", "lookahead_m": 2.0}
            )
            adapter = simulate(path, scene, vehicle, 0.0, settings, corrected=False)
            compare_frozen(adapter.summary, previous.summary)
            check_prefix(adapter.trace, previous.trace, None)
            check_prefix(
                result.trace,
                previous.trace,
                result.summary.get("terminal_switch_index"),
            )
        rows.append({"case": name, "expected_success": expected, **result.summary})
    return {
        "passed": True,
        "commands": command_cases(),
        "executions": rows,
        "maximum_rk4_error_m": maximum,
        "tolerance_m": 1e-10,
    }
