"""Prefix references preserve numbers, reject drift, cycles and old outputs."""

import gzip
import json
from pathlib import Path

import pytest

from gsunlight_repro.stage5af.storage import Records, check_prefix, public_output


def test_prefix_check_detects_state_drift_and_stopping_drift() -> None:
    old = [{"position": [1.0, 2.0, 3.0], "physical_reason": "ok"}]
    assert check_prefix(old, old, None) == 1
    with pytest.raises(ValueError, match="differs"):
        check_prefix(
            [{"position": [1.0, 2.0, 3.01], "physical_reason": "ok"}], old, None
        )
    with pytest.raises(ValueError, match="termination"):
        check_prefix([], old, None)


def test_single_prefix_reference_and_immutable_storage(tmp_path) -> None:
    records = Records(tmp_path / "new", tmp_path / "old", tmp_path / "ar")
    original = {
        "meta": {"case_id": "old"},
        "summary": {},
        "trace": [{"position": [1, 2, 3]}],
    }
    records.save("old", original)
    corrected = {
        "meta": {"case_id": "new"},
        "summary": {},
        "trace": [{"position": [1, 2, 3]}, {"position": [2, 2, 3]}],
    }
    assert records.save("new", corrected, {"stage": "5af", "case_id": "old"}) == 1
    assert records.read("new")["trace"] == corrected["trace"]
    with pytest.raises(FileExistsError):
        records.save("new", corrected)
    with gzip.open(records.path("loop"), "wt", encoding="utf-8") as stream:
        json.dump(
            {
                "prefix_source": {"stage": "5af", "case_id": "loop"},
                "prefix_steps": 1,
                "trace_suffix": [],
            },
            stream,
        )
    with pytest.raises(ValueError, match="Cyclic"):
        records.read("loop")
    with pytest.raises(ValueError):
        records.path("../escape")
    with pytest.raises(ValueError, match="historical"):
        public_output(Path("results/stage5ae"))
