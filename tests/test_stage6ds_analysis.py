"""Unit-only synthetic counters test scientific denominators, not performance."""

import pytest

from gsunlight_repro.stage6ds.analysis import group_rates, leave_one_map_out


def record(name: str, model: bool, executed: bool, success: bool) -> dict:
    return {
        "scenario": name,
        "model_feasible": str(model),
        "reference_geometry_safe": "True" if executed else "",
        "los_was_run": str(executed),
        "los_eligible": str(executed),
        "los_strict_success": str(success),
    }


def test_conditional_and_complete_denominators_remain_distinct() -> None:
    rows = [
        record("a", True, True, True),
        record("a", True, True, False),
        record("b", False, False, False),
    ]
    rates = group_rates(rows)
    assert (rates["K"], rates["M"], rates["E"], rates["S"]) == (3, 2, 2, 1)
    assert rates["M_K"] == 2 / 3 and rates["S_E"] == 0.5 and rates["S_K"] == 1 / 3


def test_no_execution_has_undefined_conditional_success() -> None:
    rates = group_rates([record("a", False, False, False)])
    assert rates["Gref"] == 0 and rates["S_E"] is None and rates["S_K"] == 0


def test_map_sensitivity_is_not_pseudoreplicated_confidence() -> None:
    rows = [record("a", True, True, True), record("b", False, False, False)]
    assert leave_one_map_out(rows) == (0, 1)


def test_missing_native_boolean_is_rejected() -> None:
    row = record("a", True, True, True)
    row["model_feasible"] = ""
    with pytest.raises(ValueError, match="explicit"):
        group_rates([row])
