"""Explicit evidence locations and exclusive numeric records for stage6D."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from ..stage5a.maps import ROOT

BASE = "e39d88a8287d4ff98ce03a8afa1d59d3a7cc2c6d"
PUBLIC = ROOT / "results/stage6d"


def save_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    """Write finite JSON, refusing replacement for original run records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")


def save_record(path: Path, value: Any) -> None:
    """Keep each large original numeric trace once, outside the repository."""
    if path.resolve().is_relative_to(ROOT):
        raise ValueError("Full traces must remain outside Git")
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "xt", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)


def load_record(path: Path) -> Any:
    """Read one preserved numeric record without filling missing values."""
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def outcome(before: bool, after: bool) -> str:
    """Keep recovery and regression symmetric in every paired table."""
    return (
        "kept_success"
        if before and after
        else "regressed"
        if before
        else "recovered"
        if after
        else "kept_failure"
    )
