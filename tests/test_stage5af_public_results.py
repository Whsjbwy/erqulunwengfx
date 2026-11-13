"""Public matrix completeness, preserved negative results and exact pairing."""

import csv
import json
from pathlib import Path

from gsunlight_repro.stage5a.maps import read_config
from gsunlight_repro.stage5af.analysis import CONTROLLERS
from gsunlight_repro.stage5af.maps import generate, validate

RESULTS = Path("results/stage5af")


def table(name: str) -> list[dict[str, str]]:
    """Read compact exported evidence without needing private trajectory files."""
    with (RESULTS / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_new_map_geometry_is_nontrivial_and_prospectively_certified() -> None:
    document = read_config("stage5af_maps.json")
    result = validate(document, read_config("stage5a_protocol.json"))
    assert result["passed"] and len(result["maps"]) == 12
    assert all(not r["nominal_direct_valid"] for r in result["maps"])
    assert (
        sum(
            r["reachability"]["body"].startswith("certified_reachable")
            for r in result["maps"]
        )
        == 12
    )
    assert (
        sum(
            r["reachability"]["margin"].startswith("certified_reachable")
            for r in result["maps"]
        )
        == 11
    )
    for spec in document["maps"][::4]:
        first, second = generate(spec, document), generate(spec, document)
        assert (first.grid.occupancy == second.grid.occupancy).all()


def test_every_registered_job_and_no_path_condition_is_retained() -> None:
    plans = table("planning_runs.csv")
    rows = table("execution_runs.csv")
    cfg = read_config("stage5af_protocol.json")
    expected = {
        f"independent_{s['id']}_{m}_{r}_seed{k}"
        for s in read_config("stage5af_maps.json")["maps"]
        for m in cfg["methods"]
        for r in cfg["modes"]
        for k in cfg["planning_seeds"]
    }
    assert (
        len(plans) == len(expected) == 216 and {r["job_id"] for r in plans} == expected
    )
    assert len(rows) == len({r["case_id"] for r in rows}) == 1296
    assert (
        sum(r["reachability"].startswith("certified_reachable") for r in plans) == 207
    )
    assert (
        sum(r["reachability"].startswith("certified_unreachable") for r in plans) == 9
    )
    assert {r["controller"] for r in rows} == set(CONTROLLERS)
    assert all(float(r["time_budget_s"]) == 10 for r in plans)
    for row in rows:
        if row["was_run"] == "False":
            assert row["path_id"] == row["length_m"] == ""
            assert row["eligible"] == row["execution_success"] == "False"
        else:
            assert row["raw_path_id"] == row["job_id"] + "::raw"
        if row["execution_success"] == "True":
            assert row["required_clearance_satisfied"] == row["eligible"] == "True"


def test_all_recoveries_regressions_and_terminal54_ids_are_traceable() -> None:
    development = table("development_runs.csv")
    assert len(development) == 2160
    assert sum(r["was_run"] == "True" for r in development) == 1836
    index = {r["case_id"]: r for r in development}
    for name, size in (
        ("development_paired.csv", 2520),
        ("independent_paired.csv", 1512),
    ):
        rows = table(name)
        assert len(rows) == size
        assert len({(r["job_id"], r["factor"]) for r in rows}) == size
        for row in rows:
            assert int(row["delta_success"]) == int(
                row["second_success"] == "True"
            ) - int(row["first_success"] == "True")
    terminal = table("terminal54_paired.csv")
    assert len(terminal) == len({r["case_id"] for r in terminal}) == 54
    for row in terminal:
        assert row["recovered"] == index[row["corrected_case_id"]]["execution_success"]
    for row in development:
        if row["controller"] == "los_terminal_v1" and row["was_run"] == "True":
            assert int(row["terminal_switches"]) <= 1


def test_final_audits_and_denominators_reconstruct_actual_results() -> None:
    accounting = json.loads(
        (RESULTS / "experiment_accounting.json").read_text(encoding="utf-8")
    )
    dev = json.loads((RESULTS / "development_audit.json").read_text(encoding="utf-8"))
    independent = json.loads(
        (RESULTS / "independent_audit.json").read_text(encoding="utf-8")
    )
    assert accounting["complete"] and accounting["new_development_conditions"] == 612
    assert dev["passed"] and dev["new_condition_records_checked"] == 612
    assert independent["passed"] and independent["planning_tasks"] == 216
    assert (
        independent["new_condition_records_checked"]
        == accounting["independent_actual_execution_conditions"]
    )
    assert accounting["saved_condition_records"] == (
        accounting["new_development_conditions"]
        + accounting["independent_actual_execution_conditions"]
    )
    assert (
        dev["maximum_rk4_error_m"] < 1e-10
        and independent["maximum_rk4_error_m"] < 1e-10
    )
    for row in table("map_summary.csv"):
        for rate, n, d in (
            ("geometry_rate", "geometry_successes", "known_feasible_tasks"),
            ("conditional_execution_rate", "execution_successes", "execution_eligible"),
            ("end_to_end_rate", "execution_successes", "known_feasible_tasks"),
        ):
            if int(row[d]):
                assert float(row[rate]) == int(row[n]) / int(row[d])
            else:
                assert row[rate] == ""
