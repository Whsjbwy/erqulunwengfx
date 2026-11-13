"""Denominators, missing inputs, lineage and immutable trace references."""

from pathlib import Path

import pytest

from gsunlight_repro.stage5ae.analysis import (
    bootstrap_ratio,
    flatten,
    map_summary,
    paired_rows,
)
from gsunlight_repro.stage5ae.storage import Records, public_output


def test_imported_metadata_cannot_override_pairing_identity() -> None:
    record = {
        "summary": {"path_id": 7, "raw_path_id": "old", "execution_success": True},
        "meta": {"path_id": "job::shortcut", "raw_path_id": "job::raw"},
    }
    assert flatten(record)["path_id"] == "job::shortcut"
    assert flatten(record)["raw_path_id"] == "job::raw"


def test_three_denominators_preserve_no_path_and_negative_envelope() -> None:
    base = {"scene": "A", "family": "ordinary", "method": "rrt_star", "mode": "body"}
    plans = [
        base
        | {
            "job_id": "good",
            "reachability": "certified_reachable",
            "geometry_success": True,
        },
        base
        | {
            "job_id": "missing",
            "reachability": "certified_reachable",
            "geometry_success": False,
        },
        base
        | {
            "job_id": "negative",
            "reachability": "certified_unreachable_aperture",
            "geometry_success": False,
        },
    ]
    executions = [
        base
        | {
            "job_id": "good",
            "processing": p,
            "controller": "legacy",
            "eligible": True,
            "execution_success": True,
            "physical_execution_success": True,
            "primary_class": "success",
        }
        for p in ("raw", "shortcut")
    ]
    row = map_summary(plans, executions, ["legacy"])[0]
    assert row["known_feasible_tasks"] == 2 and row["geometry_rate"] == 0.5
    assert row["conditional_execution_rate"] == 1 and row["end_to_end_rate"] == 0.5
    assert row["envelope_unreachable"] == 1


def test_undefined_interval_and_missing_pairs_are_not_zero_success_claims() -> None:
    assert bootstrap_ratio([0, 0], [0, 0]) == (None, None, 0)
    with pytest.raises(ValueError, match="Missing"):
        paired_rows(
            [{"job_id": "a", "processing": "raw", "controller": "legacy"}], "los_d2"
        )


def test_trace_reference_and_historical_output_protection(tmp_path) -> None:
    records = Records(tmp_path / "new", tmp_path / "old")
    records.save(
        "source", {"meta": {"id": "source"}, "summary": {}, "trace": [{"time_s": 0.1}]}
    )
    records.save(
        "alias", {"meta": {"id": "alias"}, "summary": {}, "trace_reference": "source"}
    )
    assert records.read("alias")["trace"] == [{"time_s": 0.1}]
    with pytest.raises(FileExistsError):
        records.save("alias", {})
    with pytest.raises(ValueError, match="historical"):
        public_output(Path("results/stage5ar"))
