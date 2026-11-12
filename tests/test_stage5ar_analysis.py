"""Paired denominators, missing outcomes and lineage must fail closed."""

import pytest

from gsunlight_repro.stage5ar.analysis import (
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
