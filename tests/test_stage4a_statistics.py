"""Check clustered denominators, missing quality and the frozen decision gate."""

import json
from pathlib import Path

import numpy as np
import pytest

from gsunlight_repro.stage4a.analysis import analyze, map_summary, pair_rows
from gsunlight_repro.stage4a.runner import Runner
from gsunlight_repro.stage4a.statistics import decide, interval, paired_estimate


def fixture_pairs() -> list[dict]:
    """Construct four independent maps with known ten-percent paired reduction."""
    return [
        {
            "scene": f"T{scene}",
            "family": "ordinary" if scene < 3 else "narrow",
            "seed": seed,
            "left_valid": True,
            "right_valid": True,
            "relative_length_gain": 0.1,
        }
        for scene in range(1, 5)
        for seed in range(5)
    ]


def test_hierarchical_estimate_uses_maps_and_is_reproducible() -> None:
    rows = fixture_pairs()
    estimate = paired_estimate(rows, repetitions=100)
    assert estimate["maps"] == 4 and estimate["pairs"] == 20
    assert estimate["left_rate"] == estimate["joint_coverage"] == 1
    assert estimate["length_gain"] == pytest.approx(0.1)
    assert estimate["length_gain_ci95"] == pytest.approx([0.1, 0.1])
    assert estimate == paired_estimate(rows, repetitions=100)


def test_no_common_path_has_missing_length_not_zero() -> None:
    rows = [
        {**r, "left_valid": False, "relative_length_gain": None}
        for r in fixture_pairs()
    ]
    estimate = paired_estimate(rows, repetitions=100)
    assert estimate["joint_coverage"] == 0
    assert estimate["length_gain"] is None
    assert estimate["length_gain_ci95"] is None
    assert estimate["length_bootstrap_defined"] == 0
    assert interval(np.array([np.nan])) is None


def test_successful_survivors_cannot_override_low_coverage() -> None:
    rows = fixture_pairs()
    rows[0].update(left_valid=False, relative_length_gain=None)
    estimate = paired_estimate(rows, repetitions=100)
    gate = json.loads(Path("configs/stage4a_protocol.json").read_text())["go_gate"]
    assert (
        decide(estimate, gate, complete=True, invalid_paths=0)["recommendation"]
        == "Pivot"
    )
    assert (
        decide(estimate, gate, complete=False, invalid_paths=0)["recommendation"]
        == "Incomplete"
    )
    assert (
        decide(estimate, gate, complete=True, invalid_paths=1)["recommendation"]
        == "Blocked"
    )


def test_go_requires_all_preregistered_conditions() -> None:
    estimate = paired_estimate(fixture_pairs(), repetitions=100)
    gate = json.loads(Path("configs/stage4a_protocol.json").read_text())["go_gate"]
    assert (
        decide(estimate, gate, complete=True, invalid_paths=0)["recommendation"] == "Go"
    )
    estimate["length_gain_ci95"] = [-0.01, 0.2]
    assert (
        decide(estimate, gate, complete=True, invalid_paths=0)["recommendation"]
        == "Pivot"
    )


def test_duplicate_seeds_and_incomplete_map_blocks_are_rejected() -> None:
    rows = fixture_pairs()
    with pytest.raises(ValueError, match="Duplicate"):
        paired_estimate([*rows, rows[0]], repetitions=10)
    with pytest.raises(ValueError, match="complete"):
        paired_estimate(rows[:-1], repetitions=10)


def test_pairing_keeps_failure_rows_instead_of_selecting_successes() -> None:
    common = {
        "scene": "T1",
        "seed": 0,
        "split": "holdout",
        "family": "ordinary",
        "checkpoint_s": 30,
    }
    curves = [
        {**common, "method": "A4", "valid": False, "best_length": None},
        {**common, "method": "rrt_restart", "valid": True, "best_length": 100},
    ]
    pair = pair_rows(curves)[0]
    assert pair["comparison"] == "A4_vs_rrt_restart"
    assert pair["relative_length_gain"] is None
    assert pair["left_valid"] is False and pair["right_valid"] is True
    with pytest.raises(ValueError, match="Duplicate"):
        pair_rows([*curves, curves[0]])


def test_empty_analysis_is_incomplete_and_preserves_configuration(tmp_path) -> None:
    runner = Runner(tmp_path / "private", tmp_path / "public")
    source = runner.local / "configuration.json"
    original = source.read_bytes()
    accounting = analyze(runner.local, runner.output, figures=False)
    assert accounting["expected_unique_trials"] == 402
    assert accounting["actual_unique_trials"] == 0
    assert accounting["recommendation"] == "Incomplete"
    assert source.read_bytes() == original


def test_map_summary_keeps_coverage_and_conditional_quality_together() -> None:
    identity = {
        "scene": "T1",
        "split": "holdout",
        "family": "ordinary",
        "seed": 0,
        "checkpoint_s": 30,
    }
    curves = [
        {**identity, "method": "A4", "valid": False, "best_length": None},
        {**identity, "method": "rrt_restart", "valid": True, "best_length": 100},
    ]
    runs = [
        {
            **row,
            "first_valid_time_s": 1 if row["valid"] else None,
            "actual_total_s": 30,
            "oracle_query_calls": 100,
        }
        for row in curves
    ]
    rows = map_summary(curves, runs)
    assert rows[0]["method"] == "A4"
    assert rows[0]["rate"] == 0
    assert rows[0]["mean_length_on_valid"] is None
    assert rows[1]["rate"] == 1 and rows[1]["mean_length_on_valid"] == 100
