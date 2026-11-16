"""The restored matrix is immutable; missing trials are not manufactured failures."""

from copy import deepcopy

import pytest

from gsunlight_repro.stage6ds.planning import ledger, resource_check
from gsunlight_repro.stage6ds.protocol import frozen, request_for


def test_original54_roster_and_three_pilots() -> None:
    cfg, tasks = frozen()
    assert len(tasks) == len({t["job_id"] for t in tasks}) == 54
    assert [(t["scenario"], t["seed"], t["id"]) for t in tasks[:3]] == [
        ("wide_1", 1, "rrt_first"),
        ("wide_1", 1, "sst_radius2_first"),
        ("wide_1", 1, "sst_radius2_anytime"),
    ]
    assert [
        cfg[k]
        for k in ("search_cap_s", "planning_cap_s", "execution_cap_s", "pipeline_cap_s")
    ] == [8, 10, 20, 30]


def test_configuration_drift_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import gsunlight_repro.stage6ds.protocol as module

    original = module.read_config("stage6d_protocol.json")
    changed = deepcopy(original)
    changed["d2"]["selection_radius"] = 0.2
    monkeypatch.setattr(module, "read_config", lambda _: changed)
    with pytest.raises(ValueError, match="changed"):
        frozen()


def test_search_request_never_contains_witness_controls() -> None:
    _, tasks = frozen()
    scene = {"id": "synthetic_test_only", "initial": [8, 12, 10, 0, 0, 1]}
    for task in tasks:
        request = request_for(task, scene)
        assert "controls" not in request
        assert request["seed"] == task["seed"]
        assert request["search_budget_s"] == 8


def test_unrun_ledger_keeps54_rows_and_null_measurements() -> None:
    _, tasks = frozen()
    rows = ledger(tasks, {})
    assert len(rows) == 54
    assert all(
        r["run_state"] == "not_run" and r["model_feasible"] is None for r in rows
    )
    completed = {
        tasks[0]["job_id"]: {"run_state": "completed", "model_feasible": False}
    }
    rows = ledger(tasks, completed)
    assert rows[0]["model_feasible"] is False
    assert sum(r["model_feasible"] is None for r in rows) == 53


def test_resource_gate_rejects_missing_peak_and_oversized_records(tmp_path) -> None:
    cfg = {"maximum_native_rss_bytes": 1000, "maximum_job_record_bytes": 10}
    with pytest.raises(RuntimeError, match="RSS"):
        resource_check(tmp_path, {"peak_native_rss_bytes": None}, cfg)
    (tmp_path / "test-data.txt").write_text("x" * 11)
    with pytest.raises(RuntimeError, match="size"):
        resource_check(tmp_path, {"peak_native_rss_bytes": 100}, cfg)
