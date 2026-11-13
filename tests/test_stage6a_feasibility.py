"""Analytic limits and witness semantics without implementing a planner."""

import json
import math
from pathlib import Path

import pytest

from gsunlight_repro.stage5a.maps import read_config
from gsunlight_repro.stage6a.feasibility import curvature, output_directory, run_case


def test_known_quarter_turns_match_analytic_endpoints() -> None:
    protocol, vehicle = (
        read_config("stage6a_feasibility_protocol.json"),
        read_config("stage5a_protocol.json"),
    )
    for identity, sign in (("left_arc", 1), ("right_arc", -1)):
        spec = next(row for row in protocol["cases"] if row["id"] == identity)
        summary, trace = run_case(spec, protocol, vehicle)
        radius = 1 / math.radians(10)
        assert summary["motion_witness_feasible"]
        assert summary["last_accepted_position"] == pytest.approx(
            (20 + radius, 20 + sign * radius, 15), abs=1e-10
        )
        assert summary["last_accepted_yaw_rad"] == pytest.approx(sign * math.pi / 2)
        assert summary["maximum_rk4_error_m"] < 1e-10
        json.dumps(trace, allow_nan=False)


def test_total_curvature_does_not_replace_separate_rate_bounds() -> None:
    yaw_bound, pitch_bound = math.radians(10), math.radians(5)
    invalid_pitch = math.radians(8)
    assert curvature(1, 0, 0, invalid_pitch) < yaw_bound
    assert invalid_pitch > pitch_bound
    assert curvature(1, 0, yaw_bound, pitch_bound) > yaw_bound
    with pytest.raises(ValueError, match="positive speed"):
        curvature(0, 0, 0, 0)


def test_rejected_candidate_is_not_reported_as_accepted_state() -> None:
    protocol, vehicle = (
        read_config("stage6a_feasibility_protocol.json"),
        read_config("stage5a_protocol.json"),
    )
    spec = next(row for row in protocol["cases"] if row["id"] == "pitch_angle_reject")
    summary, trace = run_case(spec, protocol, vehicle)
    assert summary["actual"] == "pitch_bound" and not trace[-1]["accepted"]
    assert summary["last_accepted_position"] == trace[-1]["start_position"]
    assert summary["accepted_intervals"] == len(trace) - 1
    with pytest.raises(ValueError, match="historical"):
        output_directory(Path("results/stage5af"))
