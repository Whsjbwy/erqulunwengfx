"""Paired denominators, missing outcomes and lineage must fail closed."""

import pytest

from gsunlight_repro.stage5ar.analysis import (
    condition_summary,
    geometry_associations,
    paired_sensitivity,
    rankdata,
    shortcut_rows,
    spearman,
    waterfall,
)
from gsunlight_repro.stage5ar.runner import Runner


def test_sensitivity_keeps_losses_and_requires_every_condition() -> None:
    base = {
        "job_id": "task",
        "path_id": 1,
        "variant": "selected",
        "condition_id": "baseline",
        "primary_class": "success",
        "execution_success": True,
    }
    alternate = base | {
        "condition_id": "C1",
        "primary_class": "tracking_error_limit",
        "execution_success": False,
    }
    conditions = [{"id": "baseline"}, {"id": "C1"}]
    rows = paired_sensitivity([base, alternate], conditions)
    assert len(rows) == 2 and rows[1]["delta_execution_success"] == -1
    assert rows[1]["delta_final_position_error_m"] is None
    with pytest.raises(ValueError, match="Missing"):
        paired_sensitivity([base], conditions)
    with pytest.raises(ValueError, match="Duplicate"):
        paired_sensitivity([base, base], conditions)


def test_shortcut_rejects_unrelated_incumbents() -> None:
    with pytest.raises(ValueError, match="same raw"):
        shortcut_rows([{"raw_path_id": "raw1", "shortcut_source_id": "raw2"}])


def test_gate_prevents_scanning_before_validation(tmp_path) -> None:
    runner = Runner.__new__(Runner)
    runner.local = tmp_path
    with pytest.raises(ValueError, match="p0"):
        runner.require_gate("p0")


def test_map_statistics_and_tied_ranks_are_explicit() -> None:
    assert rankdata([1.0, 2.0, 2.0, 4.0]).tolist() == [0.0, 1.5, 1.5, 3.0]
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1)
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_waterfall_does_not_turn_geometry_rejection_into_tracking() -> None:
    row = {
        "phase": "holdout",
        "geometry_mode": "point",
        "method": "rrt_star",
        "reachability": "certified_reachable",
        "strict_geometry_valid": True,
        "execution_eligible": False,
        "physical_execution_success": False,
        "execution_success": False,
    }
    result = waterfall([{"row": row}])[0]
    assert result["registered_tasks"] == result["geometric_path"] == 1
    assert result["nominal_precheck"] == result["actually_tracked"] == 0


def test_unequal_map_counts_still_use_map_mean() -> None:
    base = {
        "condition_id": "baseline",
        "mode": "body",
        "physical_execution_success": False,
        "delta_execution_success": 0,
        "primary_class": "tracking_error_limit",
        "max_tracking_error_m": 3.1,
    }
    rows = [base | {"scene": "A", "execution_success": True}]
    rows += [base | {"scene": "B", "execution_success": False} for _ in range(3)]
    result = next(
        row for row in condition_summary(rows) if row["scene"] == row["mode"] == "ALL"
    )
    assert result["frozen_planning_outputs"] == 4
    assert result["strict_successes"] == 1
    assert result["success_rate_map_mean"] == 0.5


def test_missing_geometry_stays_undefined_instead_of_zero() -> None:
    rows = geometry_associations(
        [{"scene": "A", "execution_success": False, "max_tracking_error_m": 3.1}]
    )
    assert all(row["spearman_with_success"] is None for row in rows)
    assert all(row["n"] == 0 and row["missing"] == 1 for row in rows)
