"""Prospective selection and failure-preserving map-level reporting."""

import pytest

from gsunlight_repro.stage5a.analysis import (
    analyze,
    choose_steps,
    comparison_summary,
    paired_map_summary,
    paired_rows,
    summaries,
)
from gsunlight_repro.stage5a.maps import read_config


def development_records() -> list[dict]:
    """Synthetic complete staging data, never substituted for actual results."""
    records = []
    for family in ("empty", "ordinary", "near_seabed", "narrow", "sealed"):
        for _seed in range(3):
            for mode in ("point", "body", "margin"):
                for _method in ("rrt_connect", "rrt_star", "informed_rrt_star"):
                    negative = family == "sealed" or (
                        family == "narrow" and mode != "point"
                    )
                    records.append(
                        {
                            "row": {
                                "phase": "pilot",
                                "family": family,
                                "strict_geometry_valid": not negative,
                                "reachability": "certified_unreachable"
                                if negative
                                else "certified_reachable",
                                "execution_success": family == "empty",
                                "execution_reason": "not_run"
                                if negative
                                else "example",
                                "planning_peak_rss_bytes": 1000,
                                "tracking_wall_s": 1,
                                "deadline_overshoot_s": 0,
                            }
                        }
                    )
    for scene in ("D5_O", "D5_B", "D5_N"):
        for seed in range(3):
            for method in ("rrt_connect", "rrt_star", "informed_rrt_star"):
                for step in [5] if method == "rrt_connect" else [3, 5]:
                    records.append(
                        {
                            "row": {
                                "phase": "development",
                                "scene": scene,
                                "seed": seed,
                                "method": method,
                                "step_m": step,
                                "best_length": 65
                                if method == "informed_rrt_star" and step == 3
                                else 71
                                if step == 3
                                else 70,
                                "strict_geometry_valid": True,
                                "reachability": "certified_reachable",
                                "execution_reason": "example",
                                "planning_peak_rss_bytes": 1000,
                                "tracking_wall_s": 1,
                                "deadline_overshoot_s": 0,
                            }
                        }
                    )
    return records


def test_selection_uses_coverage_then_paired_length_and_never_holdout() -> None:
    data = development_records()
    protocol = read_config("stage5a_protocol.json")
    selection = choose_steps(data, protocol)
    assert selection["steps_m"] == {
        "rrt_connect": 5,
        "rrt_star": 5,
        "informed_rrt_star": 3,
    }
    assert selection["resource_gate_passed"]
    data.append({"row": {"phase": "holdout"}})
    with pytest.raises(ValueError, match="held-out"):
        choose_steps(data, protocol)


def test_selection_requires_complete_data_and_rejects_negative_false_success() -> None:
    protocol = read_config("stage5a_protocol.json")
    records = development_records()
    with pytest.raises(ValueError, match="requires"):
        choose_steps(records[:-1], protocol)
    negative = next(
        item["row"]
        for item in records
        if item["row"]["reachability"] == "certified_unreachable"
    )
    negative["strict_geometry_valid"] = True
    assert not choose_steps(records, protocol)["resource_gate_passed"]


def test_empty_analysis_cannot_claim_complete_or_fill_missing_lengths(tmp_path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    output = tmp_path / "public"
    result = analyze(local, output)
    assert not result["complete"] and result["actual_independent_trials"] == 0
    assert result["accepted_geometry_trials"] == 0


def test_failed_pairs_remain_and_map_means_do_not_average_missing_lengths() -> None:
    rows = []
    for seed in range(2):
        for method in ("rrt_star", "rrt_connect"):
            solved = seed == 0 or method == "rrt_connect"
            rows.append(
                {
                    "phase": "holdout",
                    "scene": "H5_O1",
                    "family": "ordinary",
                    "geometry_mode": "body",
                    "seed": seed,
                    "method": method,
                    "reachability": "certified_reachable",
                    "strict_geometry_valid": solved,
                    "execution_success": False,
                    "best_length": (90 if method == "rrt_star" else 100)
                    if solved
                    else None,
                }
            )
    pairs = paired_rows(rows)
    assert len(pairs) == 2 and pairs[1]["length_reduction_left_relative_right"] is None
    result = paired_map_summary(pairs)[0]
    assert result["joint_valid_pairs"] == 1
    assert result["left_geometric_rate"] == 0.5
    assert result["mean_relative_length_gain_joint_only"] == pytest.approx(0.1)


def test_summary_exposes_geometric_and_execution_denominators_separately() -> None:
    row = {
        "phase": "holdout",
        "scene": "H5_O1",
        "family": "ordinary",
        "geometry_mode": "body",
        "method": "rrt_star",
        "reachability": "certified_reachable",
        "reported_success": True,
        "strict_geometry_valid": True,
        "nominal_body_valid": True,
        "nominal_margin_valid": False,
        "execution_eligible": True,
        "execution_success": False,
        "physical_execution_success": False,
        "best_length": 90,
        "first_valid_time_s": 2,
        "actual_total_s": 30,
        "query_calls": 100,
        "tracking_wall_s": 0.2,
    }
    failed = row | {
        "reported_success": False,
        "strict_geometry_valid": False,
        "execution_eligible": None,
        "best_length": None,
        "first_valid_time_s": None,
    }
    result = summaries([row, failed])[0]
    assert result["trials"] == 2 and result["geometric_solutions"] == 1
    assert result["execution_eligible"] == 1 and result["execution_successes"] == 0
    assert result["best_length_mean_solved_only"] == 90
    aggregate = comparison_summary([row, failed])[0]
    assert aggregate["known_feasible_tasks"] == 2
    assert aggregate["execution_eligible"] == 1
    assert aggregate["geometry_rate_map_mean_feasible"] == 0.5
    assert aggregate["execution_rate_of_eligible"] == 0
    unknown = comparison_summary([failed | {"reachability": "unknown"}])[0]
    assert unknown["known_infeasible_tasks"] == 0
    assert unknown["unknown_feasibility_tasks"] == 1
