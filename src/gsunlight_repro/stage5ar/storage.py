"""Read trace references so identical replay coordinates are stored once."""

from __future__ import annotations

import gzip
import json
from pathlib import Path


def read_record(path: Path, seen: frozenset[Path] = frozenset()) -> dict:
    """Resolve local basename-only trace references and reject cycles."""
    path = path.resolve()
    if path in seen:
        raise ValueError("Cyclic replay trace reference")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        record = json.load(stream)
    reference = record.get("trace_reference")
    if reference is not None:
        if Path(reference).name != reference:
            raise ValueError("Replay trace reference must be a local basename")
        source = read_record(path.parent / reference, seen | {path})
        record["trace"] = source["trace"]
    return record
