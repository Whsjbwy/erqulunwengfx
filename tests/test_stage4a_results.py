"""Check complete public trial coverage and certified checkpoint consistency."""

import csv
import json
from pathlib import Path

import pytest


def rows(name: str) -> list[dict[str, str]]:
    """Read a compact result table using only committed synthetic evidence."""
    with (Path("results/stage4a") / name).open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_complete_matrix_contains_all_tasks_once() -> None:
    protocol = json.loads(
        Path("configs/stage4a_protocol.json").read_text(encoding="utf-8")
    )
    maps = json.loads(Path("configs/stage4a_maps.json").read_text(encoding="utf-8"))[
        "maps"
    ]
    expected = {
        (m["id"], method, seed)
        for m in maps
        for method in protocol["methods"]
        for seed in protocol["planning_seeds"]
    }
    expected.update(
        ("S1", method, seed)
        for method in protocol["angles"]
        for seed in protocol["pilot_seeds"]
    )
    actual = rows("runs.csv")
    keys = {(r["scene"], r["method"], int(r["seed"])) for r in actual}
    assert keys == expected
    assert len(actual) == len(keys) == 402
    assert not {"H1", "H2"}.intersection(r["scene"] for r in actual)


def test_checkpoint_views_and_time_accounting_match_executed_trials() -> None:
    runs = {r["job_id"]: r for r in rows("runs.csv")}
    curves = rows("anytime_curves.csv")
    assert len(curves) == 402 * 5
    assert len({(r["job_id"], r["checkpoint_s"]) for r in curves}) == len(curves)
    for point in curves:
        source = runs[point["job_id"]]
        if point["valid"] == "True":
            assert source["first_valid_time_s"]
            assert float(source["first_valid_time_s"]) <= float(point["checkpoint_s"])
            assert float(point["best_length"]) > 0
        else:
            assert not point["best_length"] and not point["best_kind"]
    for source in runs.values():
        total = sum(
            float(source[k])
            for k in ("search_and_bookkeeping_s", "external_validation_s", "shortcut_s")
        )
        assert total == pytest.approx(float(source["actual_total_s"]), abs=1e-6)
        assert int(source["invalid_candidates"]) == 0


def test_geometry_audit_and_decision_have_complete_evidence() -> None:
    root = Path("results/stage4a")
    accounting = json.loads(
        (root / "experiment_accounting.json").read_text(encoding="utf-8")
    )
    audit = json.loads((root / "certificate_audit.json").read_text(encoding="utf-8"))
    decision = json.loads((root / "decision.json").read_text(encoding="utf-8"))
    assert accounting["complete"] and accounting["actual_unique_trials"] == 402
    assert accounting["technical_error_records"] == 0
    assert audit["independent_trials"] == 402 and audit["invalid_paths"] == 0
    assert audit["checkpoints_checked"] == 2010
    assert decision["recommendation"] in ("Go", "Pivot")
    assert (
        decision["primary_method"] == "A4" and decision["comparator"] == "rrt_restart"
    )
