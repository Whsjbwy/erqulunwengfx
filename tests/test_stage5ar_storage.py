"""Single-copy replay trace storage must reject loops and missing sources."""

import gzip
import json

import pytest

from gsunlight_repro.stage5ar.storage import read_record


def save(path, record: dict) -> None:
    """Write a tiny synthetic storage fixture."""
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(record, stream)


def test_reference_reuses_trace_but_keeps_condition_identity(tmp_path) -> None:
    save(
        tmp_path / "source.gz",
        {"summary": {"variant": "selected"}, "trace": [{"time_s": 0.1}]},
    )
    save(
        tmp_path / "alias.gz",
        {"summary": {"variant": "raw"}, "trace_reference": "source.gz"},
    )
    record = read_record(tmp_path / "alias.gz")
    assert record["summary"]["variant"] == "raw"
    assert record["trace"] == [{"time_s": 0.1}]


def test_reference_cycle_and_escaping_path_raise(tmp_path) -> None:
    save(tmp_path / "loop.gz", {"trace_reference": "loop.gz"})
    with pytest.raises(ValueError, match="Cyclic"):
        read_record(tmp_path / "loop.gz")
    save(tmp_path / "outside.gz", {"trace_reference": "../outside.gz"})
    with pytest.raises(ValueError, match="basename"):
        read_record(tmp_path / "outside.gz")
