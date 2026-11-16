"""Deterministic acceptance roster and immutable-cache protection."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from gsunlight_repro.stage6dr.cases import (
    boundary_cases,
    export_scene,
    json_safe,
    shifted,
)


def test_registered_matrix_covers_both_envelopes_and_real_safety_counterexamples() -> (
    None
):
    cases = boundary_cases()
    ids = {case.scenario.id for case in cases}
    assert len(ids) == len(cases)
    assert cases[0].scenario.id == "original_interval_89"
    assert cases[0].source_interval_offset == 89
    for sign in ("neg", "pos"):
        assert sign + "_candidate_one_ulp_outside" in ids
        assert sign + "_envelope_ulp_+0" in ids
        assert sign + "_envelope_ulp_+1" in ids
        assert sign + "_yaw_illegal" in ids
        assert sign + "_pitch_illegal" in ids
    assert {
        "mid_segment_reject",
        "face_contact",
        "edge_contact",
        "corner_contact",
        "workspace_escape",
    } <= ids
    assert {case.category for case in cases} >= {
        "invalid_initial",
        "invalid_control",
        "middle_collision",
    }


def test_ulp_enumeration_is_reversible_and_not_a_decimal_tolerance() -> None:
    limit = math.pi / 9 + 1e-12
    assert shifted(limit, 1) > limit
    assert shifted(shifted(limit, 8), -8) == limit
    assert shifted(limit, 1) - limit < 1e-12


def test_nonfinite_json_keeps_explicit_input_tags() -> None:
    assert json_safe([math.nan, math.inf, -math.inf, 0.0]) == [
        "nan",
        "+inf",
        "-inf",
        0.0,
    ]


def test_existing_cache_mismatch_is_rejected_without_replacement(
    tmp_path: Path,
) -> None:
    case = boundary_cases()[1].scenario
    source = tmp_path / "old"
    source.mkdir()
    old_file = source / (case.physical_key + ".u8")
    old_file.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="voxel bytes differ"):
        export_scene(case, [source], tmp_path / "new")
    assert old_file.read_bytes() == b"wrong"


def test_new_cache_cannot_write_into_a_historical_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="historical"):
        export_scene(boundary_cases()[0].scenario, [tmp_path], tmp_path / "old")
