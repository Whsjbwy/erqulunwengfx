"""Predeclared T01-T08 numerical and geometric acceptance cases."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.geometry import Geometry
from ..stage5a.maps import Scene, body_radius, read_config
from ..stage5a.tracking import Route, State, chord_error_bound, integrate, track
from .reference import rk4_position, sampled_curve_evidence
from .replay import compare_frozen, replay

BASELINE = {
    "id": "baseline",
    "initial_yaw": "goal",
    "speed_m_s": 1.0,
    "lookahead_m": 3.0,
}


def require(condition: bool, explanation: str) -> None:
    """Keep acceptance checks enabled even under optimized Python."""
    if not condition:
        raise ValueError(explanation)


def empty_scene(start=(8.0, 8.0, 8.0), goal=(38.0, 8.0, 8.0)) -> Scene:
    """Create a declared empty analytic workspace, without real-scene tuning."""
    return Scene(
        {"family": "analytic"},
        OccupancyMap(np.zeros((60, 60, 30), dtype=bool)),
        None,
        start,
        goal,
        None,
    )


def checked(path: list, scene: Scene, condition: dict = BASELINE, margin: float = 0):
    """Compare the diagnostic baseline to the original function on each case."""
    protocol = read_config("stage5a_protocol.json")
    result = replay(path, scene, protocol, margin, condition)
    if condition == BASELINE:
        compare_frozen(result.summary, track(path, scene, protocol, margin))
    return result


def run_case(case: str) -> dict:
    """Run a mathematical/geometric expectation fixed before scene scans."""
    protocol = read_config("stage5a_protocol.json")
    radius = body_radius(protocol)
    scene = empty_scene()
    path = [scene.start, scene.goal]
    metrics: dict = {}
    if case == "T01":
        result = checked(path, scene)
        require(result.summary["execution_success"], "Aligned line must reach")
        require(result.summary["max_tracking_error_m"] < 1e-10, "Line error")
        expected_steps = math.ceil((30 - 0.75) / 0.1)
        require(result.summary["steps"] == expected_steps, "Goal/update order")
        metrics = {
            "steps": result.summary["steps"],
            "expected_steps": expected_steps,
            "final_error_m": result.summary["final_position_error_m"],
        }
    elif case == "T02":
        # First leg points north while the task yaw points east.
        path = [scene.start, (8, 28, 8), (38, 28, 8), scene.goal]
        result = checked(path, scene)
        require(result.trace[0]["yaw_rate_rad_s"] > 0, "Initial northward turn")
        require(result.summary["yaw_saturation_steps"] > 0, "Yaw saturation expected")
        require(result.summary["peak_yaw_rate_deg_s"] <= 10 + 1e-10, "Yaw limit")
        metrics = {
            "initial_yaw_rad": result.summary["initial_yaw_rad"],
            "primary_class": result.summary["primary_class"],
            "max_error_m": result.summary["max_tracking_error_m"],
        }
    elif case == "T03":
        maximum = 0.0
        for speed in (0.5, 1.0):
            rate = math.radians(10)
            state = State((0, 0, 0), 0, 0, speed)
            end = integrate(state, rate, 0, math.pi / (2 * rate))
            expected = np.array([speed / rate, speed / rate, 0])
            error = float(np.linalg.norm(np.array(end.position) - expected))
            require(error < 1e-11, "Quarter circle exact solution")
            maximum = max(maximum, error)
        for yaw_rate, pitch_rate in (
            (0, 0),
            (0.17, 0.08),
            (-0.17, -0.08),
            (0.08, 0.08),
            (0.08, -0.08),
        ):
            state = State((3, 4, 5), 0.4, -0.1, 1.2)
            end = integrate(state, yaw_rate, pitch_rate, 0.7)
            reference = rk4_position(state, yaw_rate, pitch_rate, 0.7)
            error = float(np.linalg.norm(np.array(end.position) - reference))
            maximum = max(maximum, error)
            require(error < 1e-10, "Exact integration must agree with independent RK4")
            for f in np.linspace(0.01, 0.99, 99):
                actual = integrate(state, yaw_rate, pitch_rate, 0.7 * f).position
                chord = (1 - f) * np.array(state.position) + f * np.array(end.position)
                require(
                    np.linalg.norm(actual - chord)
                    <= chord_error_bound(1.2, yaw_rate, pitch_rate, 0.7) + 1e-12,
                    "Chord enclosure",
                )
        metrics = {"maximum_reference_error_m": maximum, "tolerance_m": 1e-10}
    elif case == "T04":
        scene = empty_scene((8, 20, 8), (45, 20, 8))
        path = [scene.start, (18, 25, 8), (28, 15, 8), (38, 25, 8), scene.goal]
        route = Route(path)
        require(np.allclose(route.target(0), scene.start), "Route initial target")
        require(np.allclose(route.target(1e6), scene.goal), "Route terminal target")
        result = checked(path, scene)
        require(result.summary["yaw_saturation_steps"] > 0, "Reverse-turn saturation")
        require(result.summary["rate_limit_violations"] == 0, "S-curve rate limit")
        metrics = {
            "primary_class": result.summary["primary_class"],
            "max_error_m": result.summary["max_tracking_error_m"],
        }
    elif case == "T05":
        for sign in (-1, 1):
            state = State((0, 0, 0), 0, sign * 0.1, 1)
            end = integrate(state, 0, sign * 0.05, 1)
            require(sign * end.position[2] > 0, "z must be positive upward")
            scene = empty_scene((8, 8, 15), (18, 8, 15 + sign * 10))
            result = checked([scene.start, scene.goal], scene)
            require(result.summary["pitch_saturation_steps"] > 0, "Pitch saturation")
            require(result.summary["peak_pitch_deg"] <= 20 + 1e-10, "Pitch clamp")
            require(result.summary["pitch_limit_violations"] == 0, "Pitch limit")
        metrics = {"z_convention": "up", "maximum_pitch_deg": 20}
    elif case == "T06":
        values = np.zeros((12, 12, 12), dtype=bool)
        values[5, 5, 5] = True
        grid = OccupancyMap(values)
        for point, r in (
            ((4, 5.5, 5.5), 1),
            ((4, 4, 5.5), math.sqrt(2)),
            ((4, 4, 4), math.sqrt(3)),
        ):
            require(
                not Geometry(grid, r).segment(point, point).valid, "Contact rejected"
            )
            require(
                Geometry(grid, r - 1e-6).segment(point, point).valid,
                "Nearby free point",
            )
        require(
            Geometry(grid, 1).segment((1, 2, 2), (1, 3, 2)).valid,
            "Closed workspace boundary",
        )
        require(
            not Geometry(grid, 1).segment((0.999, 2, 2), (1, 3, 2)).valid,
            "Boundary outside",
        )
        # Safe straight sphere sweep rejected only by deliberately extra enclosure.
        a, b = (3, 3.99, 5.5), (8, 3.99, 5.5)
        require(Geometry(grid, 1).segment(a, b).valid, "Nominal sweep clear")
        require(
            not Geometry(grid, 1).segment(a, b, extra_radius=0.02).valid,
            "Conservative rejection",
        )
        event = {
            "start_position": a,
            "start_yaw_rad": 0.0,
            "start_pitch_rad": 0.0,
            "speed_m_s": 1.0,
            "time_start_s": 0.0,
            "time_s": 5.0,
            "yaw_rate_rad_s": 0.0,
            "pitch_rate_rad_s": 0.0,
        }
        custom = Scene({"family": "analytic"}, grid, None, a, b, None)
        reference = sampled_curve_evidence(event, custom, 1, 1001)
        require(
            reference["reference_physical_classification"] == "curve_certified_clear",
            "Conservative refusal is not collision",
        )
        metrics = reference
    elif case == "T07":
        scene = empty_scene((radius + 0.1, 4, 8), (radius + 0.1, 34, 8))
        path = [scene.start, scene.goal]
        require(scene.geometry(radius).path(path).valid, "Nominal valid")
        require(not scene.geometry(radius + 0.25).path(path).valid, "Margin invalid")
        result = checked(path, scene, margin=0.25)
        require(result.summary["physical_execution_success"], "Nominal arrival")
        require(
            result.summary["primary_class"] == "margin_only_failure",
            "Separate margin failure",
        )
        metrics = {"primary_class": result.summary["primary_class"]}
    elif case == "T08":
        values = np.zeros((30, 30, 15), dtype=bool)
        values[10:18, :18, :10] = True
        scene = Scene(
            {"family": "analytic"},
            OccupancyMap(values),
            None,
            (4, 4, 5),
            (26, 4, 5),
            None,
        )
        path = [scene.start, (4, 23, 5), (23, 23, 5), scene.goal]
        result = checked(path, scene)
        require(result.summary["eligible"], "Sharp geometric route valid")
        require(
            not result.summary["execution_success"], "No instantaneous 90-degree turn"
        )
        require(
            result.summary["yaw_saturation_steps"] > 0, "Turning saturation recorded"
        )
        metrics = {
            "primary_class": result.summary["primary_class"],
            "max_error_m": result.summary["max_tracking_error_m"],
        }
    else:
        raise ValueError(f"Unknown analytic case {case}")
    return {"case": case, "status": "passed", **metrics}


def run_all() -> list[dict]:
    """Pass every gate before enabling historical-scene parameter replay."""
    return [run_case(f"T{i:02d}") for i in range(1, 9)]
