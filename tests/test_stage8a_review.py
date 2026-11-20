"""Protect stop rules and distinguish unrun records from failed trajectories."""

from __future__ import annotations

from copy import deepcopy

import pytest

from gsunlight_repro.stage8a.review import (
    PUBLIC,
    GateEvidence,
    check_sources,
    demonstration_rows,
    gate_status,
    load_json,
    validate,
)


@pytest.mark.parametrize(
    ("equivalent", "unknown", "different", "expected"),
    [
        (True, False, False, "PIVOT"),
        (True, True, False, "PIVOT"),
        (False, True, False, "NEED_MORE_EVIDENCE"),
        (False, False, False, "NEED_MORE_EVIDENCE"),
        (False, False, True, "PASS"),
    ],
)
def test_gate_stop_rules(
    equivalent: bool, unknown: bool, different: bool, expected: str
) -> None:
    assert gate_status(GateEvidence(equivalent, unknown, different)) == expected


@pytest.mark.parametrize("flags", [(True, False, True), (False, True, True)])
def test_conflicting_gate_evidence_is_an_error(flags: tuple[bool, ...]) -> None:
    with pytest.raises(ValueError, match="conflicts"):
        gate_status(GateEvidence(*flags))


def test_unknown_is_not_false_when_serialized_as_text() -> None:
    with pytest.raises(ValueError, match="explicit booleans"):
        gate_status(GateEvidence(False, "false", False))  # type: ignore[arg-type]


def test_unrun_measurements_are_absent() -> None:
    rows = demonstration_rows(["zero", "constant"])
    assert all(row["run_state"] == "not_run_gate_A" for row in rows)
    for row in rows:
        for key in ("success", "wall_s", "minimum_clearance_m", "final_state"):
            assert row[key] is None


@pytest.mark.parametrize("change", ["duplicate", "no_doi", "no_method_access"])
def test_incomplete_or_duplicate_sources_are_rejected(change: str) -> None:
    papers = deepcopy(load_json(PUBLIC / "literature_sources.json"))
    if change == "duplicate":
        papers[-1] = papers[0]
    elif change == "no_doi":
        papers[0]["doi"] = ""
    else:
        papers[0]["access"] = "assumed_full_from_title"
    with pytest.raises(ValueError):
        check_sources(papers)


def test_public_review_has_no_model_success_claim() -> None:
    evidence = validate()
    assert evidence["passed"]
    assert evidence["gate_A"] == "NEED_MORE_EVIDENCE"
    assert evidence["new_model_or_planning_trials"] == 0
