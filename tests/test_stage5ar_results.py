"""Public results must preserve paired denominators and exact path lineage."""

import csv
import json
from pathlib import Path

from gsunlight_repro.stage5a.maps import read_config

RESULTS = Path("results/stage5ar")


def table(name: str) -> list[dict[str, str]]:
    """Read compact synthetic public evidence, requiring no private traces."""
    with (RESULTS / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_registered_conditions_change_exactly_one_input_factor() -> None:
    protocol = read_config("stage5ar_protocol.json")
    baseline = protocol["conditions"][0]
    for condition in protocol["conditions"][1:]:
        changed = {
            key for key in baseline if key != "id" and condition[key] != baseline[key]
        }
        assert len(changed) == 1
    assert len(protocol["conditions"]) == 5


def test_every_frozen_eligible_path_has_all_five_conditions_and_no_replacement() -> (
    None
):
    manifest = table("sampling_manifest.csv")
    assert len({row["job_id"] for row in manifest}) == 270
    eligible = {
        (row["job_id"], row["path_id"])
        for row in manifest
        if row["in_expansion"] == "True"
    }
    pilot = {
        (row["job_id"], row["path_id"])
        for row in manifest
        if row["is_selected"] == "True"
    }
    assert len(pilot) == 18 and pilot <= eligible
    rows = table("sensitivity_paired.csv")
    assert len(rows) == len(eligible) * 5 == 785
    identities = {(row["job_id"], row["path_id"], row["condition_id"]) for row in rows}
    assert len(identities) == len(rows)
    assert {(job, path) for job, path, _ in identities} == eligible
    index = {
        (row["job_id"], row["path_id"]): row
        for row in rows
        if row["condition_id"] == "baseline"
    }
    for row in rows:
        source = index[(row["job_id"], row["path_id"])]
        delta = int(row["execution_success"] == "True") - int(
            source["execution_success"] == "True"
        )
        assert int(row["delta_execution_success"]) == delta
        if row["execution_success"] == "True":
            assert (
                row["physical_execution_success"]
                == row["required_clearance_satisfied"]
                == "True"
            )
        assert row["primary_class"] != "resource_timeout"


def test_shortcut_lineage_and_independent_trace_audit_are_complete() -> None:
    pairs = table("shortcut_pairs.csv")
    assert len(pairs) == len({row["job_id"] for row in pairs}) == 157
    assert len({row["shortcut_path_id"] for row in pairs}) == 157
    for row in pairs:
        assert row["raw_path_id"] == row["shortcut_source_id"]
        assert row["shortcut_path_uid"] == row["shortcut_path_id"]
        indices = json.loads(row["source_indices"])
        assert indices[0] == 0 and indices == sorted(set(indices))
        assert float(row["shortcut_length_m"]) <= float(row["raw_length_m"]) + 1e-10
    accounting = json.loads(
        (RESULTS / "experiment_accounting.json").read_text(encoding="utf-8")
    )
    audit = json.loads((RESULTS / "trace_audit.json").read_text(encoding="utf-8"))
    assert accounting["complete"] and accounting["new_searches"] == 0
    assert audit["status"] == "passed"
    assert audit["replay_records_checked"] == accounting["unique_saved_replays"]
    assert (
        accounting["unique_saved_traces"] + accounting["trace_reference_records"]
        == accounting["unique_saved_replays"]
    )
    assert audit["maximum_rk4_error_m"] <= audit["tolerance_m"]
