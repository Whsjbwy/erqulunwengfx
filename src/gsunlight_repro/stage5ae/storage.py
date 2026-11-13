"""Immutable compact records with references to existing or identical traces."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from ..stage5a.maps import ROOT
from ..stage5ar.storage import read_record as read_old


def public_output(path: Path) -> Path:
    """Reject any attempt to overwrite historical repository outputs."""
    path = path.resolve()
    if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT / "results/stage5ae"):
        raise ValueError("5AE output must not target historical repository paths")
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, value) -> None:
    """Create one immutable record with actual values and no NaN substitution."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


class Records:
    """Save each full trace once; preserve condition-specific identities."""

    def __init__(self, local: Path, old: Path) -> None:
        self.local, self.old = local, old
        self.directory = local / "replays"
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, identity: str) -> Path:
        """Build a literal filename from an internally generated identifier."""
        return self.directory / (identity + ".json.gz")

    def read(self, identity: str, seen: frozenset[str] = frozenset()) -> dict:
        """Resolve trace references, rejecting cycles and escaping basenames."""
        if identity in seen or Path(identity).name != identity:
            raise ValueError("Invalid or cyclic trace identity")
        with gzip.open(self.path(identity), "rt", encoding="utf-8") as stream:
            record = json.load(stream)
        if "trace_reference" in record:
            record["trace"] = self.read(record["trace_reference"], seen | {identity})[
                "trace"
            ]
        elif "history_reference" in record:
            name = record["history_reference"]
            if Path(name).name != name:
                raise ValueError("Historical reference must be a basename")
            record["trace"] = read_old(self.old / "replays" / name)["trace"]
        return record

    def save(self, identity: str, record: dict) -> None:
        """Refuse to overwrite an earlier result or partial failed write."""
        with gzip.open(
            self.path(identity), "xt", encoding="utf-8", compresslevel=6
        ) as stream:
            json.dump(record, stream, allow_nan=False)

    def all(self) -> list[dict]:
        """Load completed records in stable ID order."""
        return [
            self.read(p.name.removesuffix(".json.gz"))
            for p in sorted(self.directory.glob("*.json.gz"))
        ]
