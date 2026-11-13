"""Predeclared analytic positive/negative acceptance for the LOS cascade."""

from __future__ import annotations

import math

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.maps import Scene, load_scene, read_config
from ..stage5a.tracking import Route, State, integrate
from ..stage5ar.p0 import empty_scene
from ..stage5ar.reference import rk4_position
from .guidance import frame, project
from .tracking import simulate


def analytic_cases() -> list[dict]:
    """Require stable open-space tracking and reject certified negative inputs."""
    protocol = read_config("stage5a_protocol.json")
    controllers = [
        read_config("stage5ae_protocol.json")["legacy"],
        *read_config("stage5ae_protocol.json")["controller_candidates"],
    ]
    line = empty_scene()
    angles = np.linspace(0, math.pi / 4, 81)
    arc = [(8 + 30 * math.sin(t), 8 + 30 * (1 - math.cos(t)), 10.0) for t in angles]
    arc_scene = empty_scene(arc[0], arc[-1])
    slope = empty_scene((8, 8, 8), (38, 8, 13))
    reverse = empty_scene((8, 8, 8), (38, 8, 8))
    reverse_path = [reverse.start, (8, 28, 8), (38, 28, 8), reverse.goal]
    values = np.zeros((60, 45, 25), dtype=bool)
    values[19:31, :25, :12] = True
    sharp = Scene(
        {"family": "analytic"},
        OccupancyMap(values),
        None,
        (5, 10, 6),
        (45, 10, 6),
        None,
    )
    sharp_path = [
        sharp.start,
        (17, 10, 6),
        (17, 28, 6),
        (33, 28, 6),
        (33, 10, 6),
        sharp.goal,
    ]
    gap = load_scene("F5_GAP")
    ceiling_values = np.zeros((60, 60, 30), dtype=bool)
    ceiling_values[:, :, 12:] = True
    band = empty_scene((8, 8, 11), (38, 8, 11))
    band.ceiling = OccupancyMap(ceiling_values)
    cases = [
        ("line", line, [line.start, line.goal], True),
        ("radius30_arc", arc_scene, arc, True),
        ("controlled_slope", slope, [slope.start, slope.goal], True),
        ("initial_heading", reverse, reverse_path, False),
        ("sharp_obstacle", sharp, sharp_path, False),
        ("aperture_precheck", gap, gap.witness, False),
        ("mission_precheck", band, [band.start, band.goal], False),
    ]
    output = []
    for name, scene, path, expected in cases:
        for controller in controllers:
            result = simulate(path, scene, protocol, 0.0, controller)
            if result.summary["execution_success"] != expected:
                raise ValueError(
                    f"Analytic expectation failed: {name}/{controller['id']}"
                )
            output.append(
                {
                    "case": name,
                    "controller": controller["id"],
                    "expected_success": expected,
                    **result.summary,
                }
            )
    state = State((3, 4, 5), 0.4, -0.1, 1.0)
    exact = integrate(state, 0.17, -0.08, 0.7)
    error = float(
        np.linalg.norm(np.array(exact.position) - rk4_position(state, 0.17, -0.08, 0.7))
    )
    if error > 1e-10 or not np.allclose(
        frame(np.array([1.0, 2.0, 3.0])).T @ frame(np.array([1.0, 2.0, 3.0])),
        np.eye(3),
        atol=1e-12,
    ):
        raise ValueError("Independent integration or LOS frame acceptance failed")
    output.append(
        {"case": "independent_reference", "maximum_error_m": error, "passed": True}
    )
    return output


def folded_projection_case() -> dict:
    """A possible nearest-map jump is a diagnostic, not proof of a code bug."""
    route = Route([(0, 0, 0), (10, 0, 0), (10, 0.2, 0), (0, 0.2, 0)])
    before = project(route, (2, 0.099, 0))
    after = project(route, (2, 0.101, 0))
    return {
        "position_step_m": 0.002,
        "projection_step_m": after[0] - before[0],
        "segment_before": before[2],
        "segment_after": after[2],
        "interpretation": "expected_global_nearest_mapping_discontinuity",
    }


def horizontal_reference() -> list[dict]:
    """Run the bounded E2 reference on one fixed open horizontal corner."""
    from ..stage5a.maps import body_radius
    from ..stage5ar.runner import shortcut
    from .curves import fillet

    protocol = read_config("stage5a_protocol.json")
    cfg = read_config("stage5ae_protocol.json")
    scene = Scene(
        {"family": "analytic"},
        OccupancyMap(np.zeros((70, 70, 30), dtype=bool)),
        None,
        (10.0, 10.0, 10.0),
        (45.0, 45.0, 10.0),
        None,
    )
    raw = [scene.start, (45.0, 10.0, 10.0), scene.goal]
    radius = body_radius(protocol)
    processed, _ = shortcut(raw, scene, radius)
    curved = fillet(raw, scene.geometry(radius), 1 / math.radians(10))
    if not curved["valid"]:
        raise ValueError("Fixed horizontal reference failed continuous certification")
    rows = []
    for label, path in (
        ("raw", raw),
        ("shortcut", processed),
        ("fillet", curved["display_points"]),
    ):
        for controller in (cfg["legacy"], cfg["controller_candidates"][0]):
            result = simulate(path, scene, protocol, 0.0, controller)
            rows.append(
                {
                    "processing": label,
                    "controller": controller["id"],
                    "curve_reference": {
                        key: value
                        for key, value in curved.items()
                        if key != "display_points"
                    },
                    "summary": result.summary,
                    "trace": result.trace,
                }
            )
    return rows
