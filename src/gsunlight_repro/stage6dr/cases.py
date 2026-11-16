"""Preregistered deterministic states, controls and unchanged obstacle witnesses."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..stage5a.maps import ROOT, Scene, read_config
from ..stage5a.tracking import State
from ..stage6b.scenarios import (
    Scenario,
    analytic_scenarios,
    effective_radius,
    mid_segment_scenario,
    state_values,
)
from ..stage6c.common import read_json


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    """One fixed input, never a stochastic planning trial."""

    scenario: Scenario
    category: str
    mode: str = "inspect"
    source_interval_offset: int = 0


def shifted(value: float, ulps: int) -> float:
    """Move a binary64 value by a signed number of representable neighbours."""
    direction = math.inf if ulps > 0 else -math.inf
    for _ in range(abs(ulps)):
        value = math.nextafter(value, direction)
    return value


def control(yaw: float = 0.0, pitch: float = 0.0) -> tuple[dict[str, float], ...]:
    """Define one frozen0.1s input in radians per second."""
    return ({"yaw_rate_rad_s": yaw, "pitch_rate_rad_s": pitch, "duration_s": 0.1},)


def variant(
    identity: str,
    state: State,
    base: Scenario,
    controls: tuple[dict[str, float], ...] = (),
) -> Scenario:
    """Keep grid semantics while explicitly replacing only the test state/input."""
    scene = Scene(
        {"id": identity, "family": "pitch_contract_acceptance"},
        base.scene.grid,
        base.scene.ceiling,
        state.position,
        base.scene.goal,
        None,
    )
    return Scenario(
        identity,
        scene,
        state,
        controls,
        "frozen_oracle_determined",
        "deterministic_interface_case",
        base.physical_key,
        base.ceiling_key,
    )


def boundary_cases() -> list[AcceptanceCase]:
    """Enumerate every registered sign/ULP/invalid-control and safety counterexample."""
    cfg = read_config("stage6dr_protocol.json")["F2"]
    base = next(case for case in analytic_scenarios() if case.id == "straight")
    limit, tolerance = math.pi / 9, 1e-12
    envelope = limit + tolerance
    result = []

    def add(
        identity: str,
        pitch: float,
        *,
        speed: float = 1,
        yaw: float = 0,
        inputs: tuple[dict[str, float], ...] = (),
        category: str = "pitch_state",
    ) -> None:
        state = State((5.0, 5.0, 5.0), yaw, pitch, speed)
        result.append(
            AcceptanceCase(
                variant(identity, state, base, inputs),
                category,
                "replay" if inputs else "inspect",
            )
        )

    for sign in cfg["pitch_signs"]:
        label = "neg" if sign < 0 else "pos"
        for center, values, offsets in (
            ("nominal", limit, cfg["nominal_boundary_ulp_offsets"]),
            ("envelope", envelope, cfg["numeric_envelope_ulp_offsets"]),
        ):
            for index in offsets:
                add(f"{label}_{center}_ulp_{index:+d}", sign * shifted(values, index))
        for index, offset in enumerate(cfg["extra_pitch_offsets_rad"]):
            add(f"{label}_offset_{index}", sign * (limit + offset))
        for boundary, value in (("nominal", limit), ("envelope", envelope)):
            add(
                f"{label}_{boundary}_zero_control",
                sign * value,
                inputs=control(),
                category="boundary_interval",
            )
        increment = (math.nextafter(envelope, math.inf) - envelope) / 0.1
        add(
            f"{label}_candidate_one_ulp_outside",
            sign * envelope,
            inputs=control(pitch=sign * increment),
            category="epsilon_filter_interval",
        )
        for axis, rate in (("yaw", math.pi / 18), ("pitch", math.pi / 36)):
            for kind, extra in (("legal", 0.0), ("illegal", 1e-9)):
                yaw_rate = sign * (rate + extra) if axis == "yaw" else 0.0
                pitch_rate = sign * (rate + extra) if axis == "pitch" else 0.0
                add(
                    f"{label}_{axis}_{kind}",
                    0,
                    inputs=control(yaw_rate, pitch_rate),
                    category="control_limit",
                )
    subnormal = math.nextafter(0.0, math.inf)
    for index, value in enumerate(
        (0, subnormal, -subnormal, 1e-16, -1e-16, 1e-12, -1e-12)
    ):
        add(f"near_zero_{index}", value)
    for index, speed in enumerate((0.0, 1.1)):
        add(f"invalid_speed_{index}", 0, speed=speed, category="invalid_initial")
    add("canonical_yaw_lower", 0, yaw=-math.pi, category="initial_representation")
    add("noncanonical_yaw_upper", 0, yaw=math.pi, category="invalid_initial")
    for index, value in enumerate((math.nan, math.inf, -math.inf)):
        add(f"nonfinite_pitch_{index}", value, category="invalid_initial")
    add("nonfinite_yaw", 0, yaw=math.nan, category="invalid_initial")
    add(
        "nonfinite_yaw_control",
        0,
        inputs=control(math.nan, 0),
        category="invalid_control",
    )
    add(
        "nonfinite_pitch_control",
        0,
        inputs=control(0, math.inf),
        category="invalid_control",
    )

    middle = mid_segment_scenario()
    result.append(AcceptanceCase(middle, "middle_collision", "replay"))
    corner = np.array((30.0, 20.0, 15.0))
    for name, yaw, pitch, touch in (
        ("face_contact", 0.0, 0.0, (30 - effective_radius(), 20.25, 15.25)),
        (
            "edge_contact",
            math.pi / 4,
            0.0,
            (
                30 - effective_radius() / math.sqrt(2),
                20 - effective_radius() / math.sqrt(2),
                15.25,
            ),
        ),
        ("corner_contact", math.pi / 4, math.pi / 18, None),
    ):
        direction = np.array(
            (
                math.cos(pitch) * math.cos(yaw),
                math.cos(pitch) * math.sin(yaw),
                math.sin(pitch),
            )
        )
        target = (
            np.asarray(touch)
            if touch is not None
            else corner - effective_radius() * direction
        )
        start = tuple(float(x) for x in target - 0.1 * direction)
        state = State(start, yaw, pitch, 1.0)
        result.append(
            AcceptanceCase(
                variant(name, state, middle, control()), "obstacle_contact", "replay"
            )
        )
    escape = State((effective_radius() + 0.05, 5, 5), -math.pi, 0, 1)
    result.append(
        AcceptanceCase(
            variant("workspace_escape", escape, base, control()),
            "workspace_boundary",
            "replay",
        )
    )
    failure = read_json(ROOT / "results/stage6d/model_mapping_failure.json")
    from ..stage6d.maps import build_scenarios

    terrain = next(case for case in build_scenarios() if case.id == "terrain_1")
    values = failure["source_state"]
    source = State(tuple(values[:3]), *values[3:])
    result.insert(
        0,
        AcceptanceCase(
            variant("original_interval_89", source, terrain, control(0, math.pi / 36)),
            "original_failure_interval",
            "replay",
            89,
        ),
    )
    ids = [case.scenario.id for case in result]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate registered deterministic case")
    return result


def json_safe(value: Any) -> Any:
    """Preserve nonfinite test inputs as explicit tags in strict JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return "nan" if math.isnan(value) else "+inf" if value > 0 else "-inf"
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    return value


def export_scene(case: Scenario, references: list[Path], cache: Path) -> dict[str, Any]:
    """Reference matching old voxel files; write missing maps only to the new cache."""
    cache = cache.resolve()
    if cache.is_relative_to(ROOT) or any(
        cache.is_relative_to(ref.resolve()) for ref in references
    ):
        raise ValueError("New map cache must be outside Git and historical directories")
    cache.mkdir(parents=True, exist_ok=True)

    def grid_record(grid: Any, key: str) -> dict[str, Any]:
        data = grid.occupancy.astype(np.uint8).tobytes(order="C")
        candidates = [ref / f"{key}.u8" for ref in references]
        existing = next(
            (path for path in candidates if path.is_file()), cache / f"{key}.u8"
        )
        if existing.exists():
            if existing.read_bytes() != data:
                raise ValueError("Stored voxel bytes differ from the frozen recipe")
        else:
            with existing.open("xb") as stream:
                stream.write(data)
        return {
            "shape": list(grid.shape),
            "origin": list(grid.origin),
            "spacing": list(grid.spacing),
            "data_file": str(existing.resolve()),
        }

    ceiling = (
        grid_record(case.scene.ceiling, case.ceiling_key)
        if case.scene.ceiling is not None
        else None
    )
    return {
        "id": case.id,
        "initial": json_safe(state_values(case.initial)),
        "goal": list(case.scene.goal),
        "radius_m": effective_radius(),
        "physical": grid_record(case.scene.grid, case.physical_key),
        "ceiling": ceiling,
    }
