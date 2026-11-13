"""The delivered matrix, three denominators and corrected reference fields."""

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from gsunlight_repro.stage5a.maps import read_config

RESULTS = Path("results/stage5ae")


def table(name: str) -> list[dict[str, str]]:
    """Read public compact evidence without requiring local full trajectories."""
    with (RESULTS / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_full_registered_matrix_and_unreachable_tasks_are_preserved() -> None:
    plans = table("planning_runs.csv")
    protocol = read_config("stage5ae_protocol.json")
    expected = {
        f"independent_{spec['id']}_{method}_{mode}_seed{seed}"
        for spec in read_config("stage5ae_maps.json")["maps"]
        for method in protocol["methods"]
        for mode in protocol["modes"]
        for seed in protocol["planning_seeds"]
    }
    assert len(plans) == len(expected) == 360
    assert {row["job_id"] for row in plans} == expected
    assert all(float(row["time_budget_s"]) == 10 for row in plans)
    assert (
        sum(row["reachability"].startswith("certified_reachable") for row in plans)
        == 345
    )
    assert (
        sum(row["reachability"].startswith("certified_unreachable") for row in plans)
        == 15
    )
    assert all(
        row["first_valid_time_s"] == ""
        for row in plans
        if row["geometry_success"] == "False"
    )


def test_paired_execution_identity_no_path_and_three_denominators() -> None:
    rows = table("execution_runs.csv")
    plans = {row["job_id"]: row for row in table("planning_runs.csv")}
    assert len(rows) == len({row["case_id"] for row in rows}) == 1440
    assert set(Counter(row["job_id"] for row in rows).values()) == {4}
    assert {row["controller"] for row in rows} == {"legacy", "los_d2"}
    for row in rows:
        if row["was_run"] == "False":
            assert row["length_m"] == row["path_id"] == ""
            assert row["eligible"] == row["execution_success"] == "False"
        else:
            assert plans[row["job_id"]]["geometry_success"] == "True"
            assert row["raw_path_id"] == row["job_id"] + "::raw"
            if row["processing"] == "shortcut":
                assert row["shortcut_source_id"] == row["raw_path_id"]
        if row["execution_success"] == "True":
            assert row["eligible"] == row["physical_execution_success"] == "True"
            assert row["required_clearance_satisfied"] == "True"
        assert row["primary_class"] != "resource_timeout"
    for row in table("map_summary.csv"):
        known, eligible, success = (
            int(row[key])
            for key in (
                "known_feasible_tasks",
                "execution_eligible",
                "execution_successes",
            )
        )
        assert (
            row["geometry_rate"] == ""
            if not known
            else float(row["geometry_rate"]) == int(row["geometry_successes"]) / known
        )
        assert (
            row["conditional_execution_rate"] == ""
            if not eligible
            else float(row["conditional_execution_rate"]) == success / eligible
        )
        assert (
            row["end_to_end_rate"] == ""
            if not known
            else float(row["end_to_end_rate"]) == success / known
        )


def test_accounting_independent_audit_and_figure_sources_are_complete() -> None:
    accounting = json.loads(
        (RESULTS / "experiment_accounting.json").read_text(encoding="utf-8")
    )
    audit = json.loads((RESULTS / "independent_audit.json").read_text(encoding="utf-8"))
    assert accounting["complete"] and accounting["independent_planning_trials"] == 360
    assert audit["status"] == "passed" and audit["planning_tasks_checked"] == 360
    assert (
        audit["records_checked"]
        == 1099 + accounting["independent_execution_conditions"]
    )
    assert audit["geometry_paths_checked"] == accounting["geometry_successes"]
    assert audit["maximum_rk4_error_m"] <= 1e-10
    references = table("failure_curve_reference.csv")
    assert len(references) == audit["failure_curve_reference_conditions"]
    assert all(int(row["reference_samples"]) == 101 for row in references)
    assert {row["primary_class"] for row in references} <= {
        "swept_safety_reject",
        "mission_band_reject",
        "margin_only_failure",
    }
    manifest = table("figure_manifest.csv")
    assert len(manifest) == 36
    assert all("_body_seed0--" in row["case_id"] for row in manifest)
    assert {row["figure"] for row in manifest} == {
        "ordinary_tracks.png",
        "narrow_tracks.png",
        "nearbed_tracks.png",
    }


def test_horizontal_reference_lengths_belong_to_their_own_inputs() -> None:
    rows = table("horizontal_reference.csv")
    assert len(rows) == 6
    for row in rows:
        assert row["input_continuous_geometry_valid"] == "True"
        if row["processing"] == "raw":
            assert float(row["input_path_length_m"]) == 70
            assert row["input_max_curvature_m_inv"] == ""
            assert row["execution_success"] == "False"
        elif row["processing"] == "shortcut":
            assert float(row["input_path_length_m"]) == pytest.approx(35 * 2**0.5)
            assert row["execution_success"] == "True"
        else:
            assert float(row["input_path_length_m"]) == float(
                row["curve_reference_length_m"]
            )
            assert float(row["input_path_length_m"]) < 70
            assert row["execution_success"] == "True"


def test_resource_recheck_never_substitutes_the_primary_matrix() -> None:
    deviation = json.loads(
        (RESULTS / "operational_deviation.json").read_text(encoding="utf-8")
    )
    recheck = json.loads(
        (RESULTS / "resource_recheck.json").read_text(encoding="utf-8")
    )
    accounting = json.loads(
        (RESULTS / "experiment_accounting.json").read_text(encoding="utf-8")
    )
    primary = {row["case_id"]: row for row in table("execution_runs.csv")}
    assert accounting["independent_planning_trials"] == 360
    assert accounting["additional_unarchived_search_attempts"] == 1
    assert deviation["duplicate_exit_code"] == 1 and deviation["record_overwrites"] == 0
    assert recheck["original_job_id"] == deviation["duplicate_job_id"]
    assert recheck["extra_searches"] == 1 and not recheck["primary_matrix_replaced"]
    assert (
        sum(
            row["known_resource_overlap"] == "True"
            for row in table("planning_runs.csv")
        )
        == 1
    )
    for row in table("resource_recheck_runs.csv"):
        assert row["case_id"] not in primary
        assert (
            row["primary_execution_success"]
            == primary[row["primary_case_id"]]["execution_success"]
        )
