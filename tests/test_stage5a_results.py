"""Verify public matrix completeness and geometry/execution/time separation."""

import csv
import json
import math
from pathlib import Path

from gsunlight_repro.stage5a.audit import expected_identities
from gsunlight_repro.stage5a.maps import read_config

RESULTS = Path("results/stage5a")


def table(name: str) -> list[dict[str, str]]:
    """Read compact public synthetic records, requiring no private trajectory."""
    with (RESULTS / name).open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_complete_matrix_contains_every_registered_task_and_negative_seed() -> None:
    config = {
        "protocol": read_config("stage5a_protocol.json"),
        "maps": read_config("stage5a_maps.json"),
    }
    selected = read_config("stage5a_selected.json")
    rows = table("runs.csv")
    assert len(rows) == len({row["job_id"] for row in rows}) == 450
    assert {row["job_id"] for row in rows} == expected_identities(config, selected)
    assert sum(row["phase"] == "holdout" for row in rows) == 270
    for row in rows:
        if row["reachability"].startswith("certified_unreachable"):
            assert row["strict_geometry_valid"] == "False"
        if row["strict_geometry_valid"] == "True":
            assert float(row["best_length"]) > 0
        else:
            assert not row["best_length"] and not row["first_valid_time_s"]


def test_checkpoints_and_budget_accounting_cannot_backfill_future_paths() -> None:
    rows = {row["job_id"]: row for row in table("runs.csv")}
    curves = table("anytime_curves.csv")
    assert len(curves) == 1305
    assert len({(row["job_id"], row["checkpoint_s"]) for row in curves}) == 1305
    for checkpoint in curves:
        source = rows[checkpoint["job_id"]]
        assert float(checkpoint["checkpoint_s"]) <= float(source["time_budget_s"])
        if checkpoint["valid"] == "True":
            assert float(source["first_valid_time_s"]) <= float(
                checkpoint["checkpoint_s"]
            )
            assert float(checkpoint["best_length"]) > 0
        else:
            assert not checkpoint["best_length"]
    for row in rows.values():
        assert math.isclose(
            sum(
                float(row[key])
                for key in ("search_and_bookkeeping_s", "validation_s", "shortcut_s")
            ),
            float(row["actual_total_s"]),
            abs_tol=1e-8,
        )


def test_execution_success_requires_body_geometry_constraints_and_final_replay() -> (
    None
):
    protocol = read_config("stage5a_protocol.json")
    for row in table("runs.csv"):
        if row["execution_success"] == "True":
            assert row["nominal_body_valid"] == row["execution_eligible"] == "True"
            assert row["physical_execution_success"] == "True"
            assert all(
                row[key] == "0"
                for key in (
                    "rate_limit_violations",
                    "pitch_limit_violations",
                    "speed_limit_violations",
                )
            )
            margin = (
                protocol["vehicle"]["safety_margin_m"]
                if row["geometry_mode"] == "margin"
                else 0
            )
            assert float(row["min_physical_clearance_lower_bound_m"]) >= margin - 1e-9
            assert float(row["min_mission_clearance_lower_bound_m"]) >= margin - 1e-9
    audit = json.loads((RESULTS / "certificate_audit.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed" and audit["trials"] == 450
    assert audit["invalid_paths"] == audit["late_certificates"] == 0
    replays = table("execution_replay.csv")
    assert len(replays) == audit["replayed_selected_paths"]
    assert all(row["same_outcome_and_metrics"] == "True" for row in replays)
