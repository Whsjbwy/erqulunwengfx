"""Guard evidence boundaries and denominators before any future planner study."""

import json

import pytest

from gsunlight_repro.stage5a.maps import ROOT, read_config
from gsunlight_repro.stage6a.review import boolean, historical_review, read_rows


def test_missing_boolean_cannot_silently_reduce_the_failure_count() -> None:
    with pytest.raises(ValueError, match="Unexpected historical Boolean"):
        boolean("")


def test_historical_rates_keep_distinct_denominators() -> None:
    summary, rates = historical_review(ROOT)
    assert summary["stage5af_planning_trials"] == 216
    assert summary["stage5af_geometry_successes"] == 194
    assert summary["stage5af_actual_execution_rows"] == 1164
    for row in rates:
        assert row["actual_executions_E"] == 194
        assert row["conditional_execution_rate_S_over_E"] == pytest.approx(
            row["strict_successes_S"] / 194
        )
        assert row["complete_task_rate_S_over_K"] == pytest.approx(
            row["strict_successes_S"] / 216
        )


def test_literature_and_future_protocol_do_not_claim_unperformed_validation() -> None:
    rows = read_rows(ROOT / "results/stage6a/literature_matrix.csv")
    assert len(rows) >= 12
    assert len({row["doi"].lower() for row in rows}) == len(rows)
    assert all(row["metadata_status"] == "verified" for row in rows)
    assert all(row["paper_url"].startswith("https://") for row in rows)
    assert any(row["text_review_status"] == "abstract_only" for row in rows)
    assert any(row["code_license"] == "not_verified" for row in rows)
    future = read_config("stage6a_future_experiment_protocol.json")
    assert future["execution_authorized"] is False
    assert future["independent_maps_generated"] is False
    assert future["model"]["inherit_vehicle"] == "stage5a_protocol.json"
    acceptance = json.loads(
        (ROOT / "results/stage6a/feasibility_acceptance.json").read_text()
    )
    assert acceptance["planner_searches"] == 0
    assert acceptance["ompl_native_baseline_executed"] is False
