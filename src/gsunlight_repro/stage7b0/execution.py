"""Nominal tracking and separate frozen-model certification, without planning."""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from ..stage5a.geometry import Geometry
from ..stage5a.maps import body_radius, read_config
from ..stage5a.tracking import State, chord_error_bound, integrate
from ..stage5ar.reference import rk4_position
from ..stage6b.replay import _replay
from ..stage6b.scenarios import Scenario
from .lqr import Limits, Matrix, bounded_control, command, state_error


class Safety:
    """Reuse the frozen body/mission/margin oracles on each entire curved step."""

    def __init__(self, scenario: Scenario) -> None:
        radius = body_radius(read_config("stage5a_protocol.json"))
        self.oracles = {
            "physical": Geometry(scenario.scene.grid, radius),
            "mission": Geometry(scenario.scene.grid, radius, scenario.scene.ceiling),
            "margin": Geometry(
                scenario.scene.grid, radius + 0.25, scenario.scene.ceiling
            ),
        }

    def interval(
        self, start: State, end: State, rates: Matrix, step: float
    ) -> dict[str, Any]:
        """Use the acceleration-derived chord deviation, never endpoint-only safety."""
        bound = chord_error_bound(start.speed, float(rates[0]), float(rates[1]), step)
        reasons = {
            name + "_reason": oracle.segment(
                start.position, end.position, extra_radius=bound
            ).reason
            for name, oracle in self.oracles.items()
        }
        return {
            **reasons,
            "chord_error_bound_m": bound,
            "minimum_required_gap_lower_bound_m": self.oracles["margin"].clearance(
                start.position, end.position, mission=True
            )
            - bound,
        }


def execute(
    scenario: Scenario,
    references: list[State],
    inputs: list[Matrix],
    gains: list[Matrix],
    limits: Limits,
    deadline: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute once, stopping at goal, first rejection or native horizon exhaustion."""
    if len(references) != len(inputs) + 1 or len(gains) != len(inputs):
        raise ValueError("Reference state/control/gain horizons differ")
    if not np.array_equal(state_error(scenario.initial, references[0]), np.zeros(5)):
        raise ValueError("Nominal comparison requires the original full initial state")
    state, trace, safety = scenario.initial, [], Safety(scenario)
    bounded_control(state, np.zeros(2), limits)
    initial_verdict = safety.interval(state, state, np.zeros(2), 0.0)
    if any(
        initial_verdict[name + "_reason"] != "ok"
        for name in ("physical", "mission", "margin")
    ):
        raise ValueError("Initial state lacks the frozen strict safety certificate")
    reached = math.dist(state.position, scenario.scene.goal) <= limits.goal
    reason, safe = "goal_reached" if reached else "reference_exhausted", True
    for index, (feedforward, gain) in enumerate(zip(inputs, gains, strict=True)):
        if math.dist(state.position, scenario.scene.goal) <= limits.goal:
            reason, reached = "goal_reached", True
            break
        if time.perf_counter() > deadline:
            reason = "execution_deadline"
            break
        requested, applied = command(
            state, references[index], feedforward, gain, limits
        )
        following = integrate(state, float(applied[0]), float(applied[1]), limits.step)
        verdict = safety.interval(state, following, applied, limits.step)
        error = state_error(following, references[index + 1])
        row = {
            "index": index,
            "time_start_s": index * limits.step,
            "time_s": (index + 1) * limits.step,
            "start_position": list(state.position),
            "position": list(following.position),
            "start_yaw_rad": state.yaw,
            "start_pitch_rad": state.pitch,
            "yaw_rad": following.yaw,
            "pitch_rad": following.pitch,
            "speed_m_s": following.speed,
            "yaw_rate_rad_s": float(applied[0]),
            "pitch_rate_rad_s": float(applied[1]),
            "requested_yaw_rate_rad_s": float(requested[0]),
            "requested_pitch_rate_rad_s": float(requested[1]),
            "yaw_saturated": bool(applied[0] != requested[0]),
            "pitch_saturated": bool(applied[1] != requested[1]),
            "feedforward_difference_rad_s": float(
                np.max(np.abs(applied - feedforward))
            ),
            "position_reference_error_m": float(np.linalg.norm(error[:3])),
            "angle_reference_error_rad": float(np.max(np.abs(error[3:]))),
            "goal_distance_after_m": math.dist(following.position, scenario.scene.goal),
            **verdict,
        }
        trace.append(row)
        state = following
        if abs(state.pitch) > limits.pitch + limits.tolerance:
            reason, safe = "pitch_bound", False
            break
        rejected = next(
            (
                name
                for name in ("physical", "mission", "margin")
                if verdict[name + "_reason"] != "ok"
            ),
            None,
        )
        if rejected is not None:
            reason, safe = (
                rejected + "_rejected_" + verdict[rejected + "_reason"],
                False,
            )
            break
        if math.dist(state.position, scenario.scene.goal) <= limits.goal:
            reason, reached = "goal_reached", True
            break
    summary = {
        "reached": reached,
        "online_safe": safe,
        "online_strict_success": reached and safe,
        "termination_reason": reason,
        "intervals": len(trace),
        "simulation_time_s": len(trace) * limits.step,
        "native_horizon_intervals": len(inputs),
        "final_goal_distance_m": math.dist(state.position, scenario.scene.goal),
        "maximum_reference_position_error_m": max(
            (r["position_reference_error_m"] for r in trace), default=0.0
        ),
        "maximum_reference_angle_error_rad": max(
            (r["angle_reference_error_rad"] for r in trace), default=0.0
        ),
        "maximum_feedforward_difference_rad_s": max(
            (r["feedforward_difference_rad_s"] for r in trace), default=0.0
        ),
        "minimum_required_gap_lower_bound_m": min(
            (r["minimum_required_gap_lower_bound_m"] for r in trace), default=None
        ),
        "yaw_saturation_steps": sum(r["yaw_saturated"] for r in trace),
        "pitch_saturation_steps": sum(r["pitch_saturated"] for r in trace),
    }
    for name in ("physical", "mission", "margin"):
        first = next((r for r in trace if r[name + "_reason"] != "ok"), None)
        summary["first_" + name + "_rejection_time_s"] = (
            first["time_s"] if first else None
        )
        summary["first_" + name + "_rejection_position"] = (
            first["position"] if first else None
        )
    return summary, trace


def certify(scenario: Scenario, trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Independently reintegrate actual new controls and verify every stored state.

    Frozen6B replay starts from the original initial state. Additional RK4 checks
    cover every new interval; no old native safety certificate is transferred.
    """
    controls = [
        {
            "yaw_rate_rad_s": r["yaw_rate_rad_s"],
            "pitch_rate_rad_s": r["pitch_rate_rad_s"],
            "duration_s": 0.1,
        }
        for r in trace
    ]
    audit, rebuilt, _ = _replay(scenario, controls)
    if len(rebuilt) != len(trace):
        raise ValueError("Independent certification stopped at a different interval")
    maximum_position, maximum_angle, maximum_rk4 = 0.0, 0.0, 0.0
    for original, independent in zip(trace, rebuilt, strict=True):
        start = State(
            tuple(original["start_position"]),
            original["start_yaw_rad"],
            original["start_pitch_rad"],
            original["speed_m_s"],
        )
        maximum_position = max(
            maximum_position, math.dist(original["position"], independent["position"])
        )
        a = State(
            tuple(original["position"]),
            original["yaw_rad"],
            original["pitch_rad"],
            original["speed_m_s"],
        )
        b = State(
            tuple(independent["position"]),
            independent["yaw_rad"],
            independent["pitch_rad"],
            independent["speed_m_s"],
        )
        maximum_angle = max(maximum_angle, float(np.max(np.abs(state_error(a, b)[3:]))))
        point = rk4_position(
            start,
            original["yaw_rate_rad_s"],
            original["pitch_rate_rad_s"],
            0.1,
            steps=50,
        )
        maximum_rk4 = max(maximum_rk4, math.dist(point, independent["position"]))
        if independent["reason"] != original["margin_reason"]:
            raise ValueError("Online and independent strict safety reasons disagree")
    if maximum_position > 1e-10 or maximum_angle > 1e-12 or maximum_rk4 > 1e-10:
        raise ValueError("Independent state or RK4 numerical consistency failed")
    return {
        "certificate_consistent": True,
        "certified_intervals": len(rebuilt),
        "full_margin_safe": audit["reason"] == "ok",
        "goal_reached": audit["goal_reached"],
        "certificate_reason": audit["reason"],
        "maximum_position_disagreement_m": maximum_position,
        "maximum_angle_disagreement_rad": maximum_angle,
        "maximum_all_interval_rk4_error_m": maximum_rk4,
        "minimum_required_gap_lower_bound_m": audit["minimum_gap_lower_bound_m"],
        "rk4_intervals": len(rebuilt),
        "rk4_substeps_per_interval": 50,
    }
