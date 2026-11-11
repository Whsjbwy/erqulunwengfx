"""Explicit no-current forward kinematics and continuous swept-body evaluation."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from ..map_reader import Point
from ..metrics import endpoints_match, path_length
from .geometry import Geometry
from .maps import Scene, body_radius


@dataclass(frozen=True, slots=True)
class State:
    """Position, yaw, upward-positive pitch and water-relative speed."""

    position: Point
    yaw: float
    pitch: float
    speed: float


def wrap(angle: float) -> float:
    """Return a heading error in [-pi,pi)."""
    return (angle + math.pi) % (2 * math.pi) - math.pi


def integrate(state: State, yaw_rate: float, pitch_rate: float, step: float) -> State:
    """Exactly integrate constant rates/speed, including simultaneous turns."""
    if step <= 0 or not all(
        math.isfinite(value)
        for value in (
            *state.position,
            state.yaw,
            state.pitch,
            state.speed,
            yaw_rate,
            pitch_rate,
            step,
        )
    ):
        raise ValueError("Integration requires finite state/input and positive step")

    def integral(angle: float, rate: float, sine: bool = False) -> float:
        half = rate * step / 2
        scale = float(np.sinc(half / math.pi))
        return (
            step * scale * (math.sin(angle + half) if sine else math.cos(angle + half))
        )

    dx = (
        state.speed
        / 2
        * (
            integral(state.yaw + state.pitch, yaw_rate + pitch_rate)
            + integral(state.yaw - state.pitch, yaw_rate - pitch_rate)
        )
    )
    dy = (
        state.speed
        / 2
        * (
            integral(state.yaw + state.pitch, yaw_rate + pitch_rate, True)
            + integral(state.yaw - state.pitch, yaw_rate - pitch_rate, True)
        )
    )
    dz = state.speed * integral(state.pitch, pitch_rate, True)
    position = tuple(
        float(value) for value in np.asarray(state.position) + [dx, dy, dz]
    )
    return State(
        position,
        wrap(state.yaw + yaw_rate * step),
        state.pitch + pitch_rate * step,
        state.speed,
    )


def chord_error_bound(
    speed: float, yaw_rate: float, pitch_rate: float, step: float
) -> float:
    """Bound curved motion relative to its chord by sup|p''|*dt^2/8."""
    return abs(speed) * math.hypot(yaw_rate, pitch_rate) * step * step / 8


class Route:
    """Arc-length targets and tracking errors; corners have no finite curvature."""

    def __init__(self, path: list[Point]) -> None:
        points = np.asarray(path, dtype=float)
        keep = np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-12]
        self.points = points[keep]
        if len(self.points) == 1:
            self.points = np.repeat(self.points, 2, axis=0)
        self.edges = np.diff(self.points, axis=0)
        self.lengths = np.linalg.norm(self.edges, axis=1)
        self.cumulative = np.r_[0.0, np.cumsum(self.lengths)]

    def projection(self, position: Point) -> tuple[float, float]:
        """Return nearest arc length and tracking error on the complete route."""
        delta = np.asarray(position) - self.points[:-1]
        numerator = np.einsum("ij,ij->i", delta, self.edges)
        t = np.divide(
            numerator,
            self.lengths**2,
            out=np.zeros_like(numerator),
            where=self.lengths > 0,
        )
        t = np.clip(t, 0, 1)
        errors = np.linalg.norm(delta - t[:, None] * self.edges, axis=1)
        index = int(np.argmin(errors))
        return float(self.cumulative[index] + t[index] * self.lengths[index]), float(
            errors[index]
        )

    def target(self, progress: float) -> np.ndarray:
        """Interpolate a fixed lookahead distance; do not smooth geometry silently."""
        if progress >= self.cumulative[-1]:
            return self.points[-1]
        index = min(
            len(self.edges) - 1,
            int(np.searchsorted(self.cumulative, progress, side="right") - 1),
        )
        fraction = (progress - self.cumulative[index]) / max(self.lengths[index], 1e-12)
        return self.points[index] + fraction * self.edges[index]


def track(
    path: list[Point], scene: Scene, protocol: dict, required_margin: float
) -> dict:
    """Execute one fixed controller; safety acceptance covers inter-step curves.

    Full collision checks run every step. One-second poses are retained only
    for compact display; they are not the collision detector.
    """
    started = time.perf_counter()
    cfg = protocol["kinematics"]
    radius = body_radius(protocol)
    mission = Geometry(scene.grid, radius, scene.ceiling)
    verdict = mission.path(path)
    if not verdict.valid or not endpoints_match(path, scene.start, scene.goal):
        return {
            "eligible": False,
            "execution_success": False,
            "physical_execution_success": False,
            "failure_reason": "geometry_rejected_before_tracking_"
            + (verdict.reason if not verdict.valid else "endpoints"),
            "tracking_wall_s": time.perf_counter() - started,
            "trajectory": [],
            "steps": 0,
        }
    physical = Geometry(scene.grid, radius)
    required = Geometry(scene.grid, radius + required_margin, scene.ceiling)
    route = Route(path)
    yaw = math.atan2(scene.goal[1] - scene.start[1], scene.goal[0] - scene.start[0])
    state = State(scene.start, yaw, 0.0, cfg["speed_m_s"])
    max_yaw, max_pitch_rate, max_pitch = (
        math.radians(cfg[key])
        for key in ("max_yaw_rate_deg_s", "max_pitch_rate_deg_s", "max_pitch_deg")
    )
    step = cfg["step_s"]
    limit = min(600, max(60, 3 * path_length(path) / state.speed + 30))
    trajectory = [[0.0, *state.position, state.yaw, state.pitch]]
    progress, error = route.projection(state.position)
    max_error, sum_squared_error, steps = error, 0.0, 0
    minimum_clearance = physical.clearance(state.position, state.position)
    minimum_mission = mission.clearance(state.position, state.position, mission=True)
    saturation_yaw = saturation_pitch = 0
    peak_yaw_rate = peak_pitch_rate = peak_pitch = 0.0
    clearance_satisfied = required.segment(state.position, state.position).valid
    reached = False
    reason = "simulation_timeout"
    violated_speed = not cfg["min_speed_m_s"] <= state.speed <= cfg["max_speed_m_s"]
    while steps * step < limit:
        if math.dist(state.position, scene.goal) <= cfg["goal_tolerance_m"]:
            reached, reason = True, "goal_reached"
            break
        if time.perf_counter() - started > cfg["wall_guard_s"]:
            reason = "execution_resource_timeout"
            break
        projection, error = route.projection(state.position)
        progress = max(progress, projection)
        target = route.target(progress + cfg["lookahead_m"])
        direction = target - state.position
        desired_yaw = math.atan2(direction[1], direction[0])
        desired_pitch = math.atan2(direction[2], math.hypot(direction[0], direction[1]))
        requested_yaw = cfg["angle_gain_s_inv"] * wrap(desired_yaw - state.yaw)
        requested_pitch = cfg["angle_gain_s_inv"] * (desired_pitch - state.pitch)
        yaw_rate = float(np.clip(requested_yaw, -max_yaw, max_yaw))
        pitch_rate = float(
            np.clip(
                requested_pitch,
                max(-max_pitch_rate, (-max_pitch - state.pitch) / step),
                min(max_pitch_rate, (max_pitch - state.pitch) / step),
            )
        )
        saturation_yaw += int(abs(requested_yaw - yaw_rate) > 1e-12)
        saturation_pitch += int(abs(requested_pitch - pitch_rate) > 1e-12)
        following = integrate(state, yaw_rate, pitch_rate, step)
        deviation = chord_error_bound(state.speed, yaw_rate, pitch_rate, step)
        physical_verdict = physical.segment(
            state.position, following.position, extra_radius=deviation
        )
        mission_verdict = mission.segment(
            state.position, following.position, extra_radius=deviation
        )
        clearance_satisfied &= required.segment(
            state.position, following.position, extra_radius=deviation
        ).valid
        minimum_clearance = min(
            minimum_clearance,
            physical.clearance(state.position, following.position) - deviation,
        )
        minimum_mission = min(
            minimum_mission,
            mission.clearance(state.position, following.position, mission=True)
            - deviation,
        )
        peak_yaw_rate = max(peak_yaw_rate, abs(yaw_rate))
        peak_pitch_rate = max(peak_pitch_rate, abs(pitch_rate))
        peak_pitch = max(peak_pitch, abs(following.pitch))
        state = following
        steps += 1
        _, error = route.projection(state.position)
        max_error = max(max_error, error)
        sum_squared_error += error * error
        if steps % 10 == 0:
            trajectory.append([steps * step, *state.position, state.yaw, state.pitch])
        if not physical_verdict.valid:
            reason = "physical_sweep_rejected_" + physical_verdict.reason
            break
        if not mission_verdict.valid:
            reason = "mission_band_sweep_rejected"
            break
        if error > cfg["max_cross_track_m"]:
            reason = "tracking_error_limit"
            break
    if trajectory[-1][0] != steps * step:
        trajectory.append([steps * step, *state.position, state.yaw, state.pitch])
    rate_violations = int(
        peak_yaw_rate > max_yaw + 1e-12 or peak_pitch_rate > max_pitch_rate + 1e-12
    )
    pitch_violations = int(peak_pitch > max_pitch + 1e-12)
    physical_success = (
        reached and not violated_speed and not rate_violations and not pitch_violations
    )
    success = physical_success and clearance_satisfied
    if reached and not clearance_satisfied:
        reason = "goal_reached_required_margin_violated"
    return {
        "eligible": True,
        "execution_success": success,
        "physical_execution_success": physical_success,
        "required_clearance_satisfied": bool(clearance_satisfied),
        "failure_reason": reason,
        "steps": steps,
        "simulation_time_s": steps * step,
        "tracking_wall_s": time.perf_counter() - started,
        "min_physical_clearance_lower_bound_m": minimum_clearance,
        "min_mission_clearance_lower_bound_m": minimum_mission,
        "max_tracking_error_m": max_error,
        "rms_tracking_error_m": math.sqrt(sum_squared_error / steps) if steps else 0.0,
        "peak_yaw_rate_deg_s": math.degrees(peak_yaw_rate),
        "peak_pitch_rate_deg_s": math.degrees(peak_pitch_rate),
        "peak_pitch_deg": math.degrees(peak_pitch),
        "yaw_saturation_steps": saturation_yaw,
        "pitch_saturation_steps": saturation_pitch,
        "rate_limit_violations": rate_violations,
        "pitch_limit_violations": pitch_violations,
        "speed_limit_violations": int(violated_speed),
        "query_calls": physical.query_calls
        + mission.query_calls
        + required.query_calls,
        "final_position_error_m": math.dist(state.position, scene.goal),
        "trajectory_sample_interval_s": 1.0,
        "trajectory": trajectory,
    }
