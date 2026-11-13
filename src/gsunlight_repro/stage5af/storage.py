"""Exclusive evidence and exact prefix references, never historical rewrites."""

from __future__ import annotations

import gzip
import json
import math
from pathlib import Path

from ..stage5a.maps import ROOT
from ..stage5ae.storage import Records as OldRecords


def public_output(path: Path) -> Path:
    """Restrict repository writes to this stage's own result directory."""
    path = path.resolve()
    if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT / "results/stage5af"):
        raise ValueError("5AF output cannot overwrite historical repository files")
    path.mkdir(parents=True, exist_ok=True)
    return path


def canonical(value):
    """Normalize tuple/list representations without rounding or file hashes."""
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    return value


def near(a, b) -> bool:
    """Compare trace values at the predeclared state/control tolerance."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(near(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return math.isclose(a, b, rel_tol=0, abs_tol=1e-12)
    return a == b


def check_prefix(trace: list[dict], previous: list[dict], switch: int | None) -> int:
    """Reject any nonterminal drift, including early stopping or skipped steps."""
    count = switch if switch is not None else len(trace)
    if count > len(previous):
        raise ValueError("Corrected trajectory extended before terminal switching")
    for a, b in zip(trace[:count], previous[:count], strict=True):
        if any(key not in a or not near(a[key], value) for key, value in b.items()):
            raise ValueError("Nonterminal trajectory differs from frozen LOS")
    if switch is None and len(trace) != len(previous):
        raise ValueError("Nonterminal termination differs from frozen LOS")
    return count


class Records:
    """Store only each changed suffix; preserve source and condition identities."""

    def __init__(self, local: Path, old: Path, ar: Path) -> None:
        self.directory = local / "replays"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.old = OldRecords(old, ar)

    def path(self, identity: str) -> Path:
        """Accept internal basename IDs only."""
        if Path(identity).name != identity or identity in ("", ".", ".."):
            raise ValueError("Trace ID must be a nonempty basename")
        return self.directory / (identity + ".json.gz")

    def read(self, identity: str, seen: frozenset[str] = frozenset()) -> dict:
        """Resolve exact references with cycle protection and no path escape."""
        if identity in seen:
            raise ValueError("Cyclic trace reference")
        with gzip.open(self.path(identity), "rt", encoding="utf-8") as stream:
            value = json.load(stream)
        if "prefix_source" in value:
            source = value["prefix_source"]
            if source["stage"] not in ("5ae", "5af"):
                raise ValueError("Unknown trace source stage")
            previous = (
                self.old.read(source["case_id"])
                if source["stage"] == "5ae"
                else self.read(source["case_id"], seen | {identity})
            )
            if not 0 <= value["prefix_steps"] <= len(previous["trace"]):
                raise ValueError("Trace prefix length is outside its source")
            value["trace"] = (
                previous["trace"][: value["prefix_steps"]] + value["trace_suffix"]
            )
        return value

    def save(self, identity: str, record: dict, source: dict | None = None) -> int:
        """Reference only bit-equal common trace fields, never approximate states."""
        count = 0
        value = dict(record)
        if source is not None:
            previous = (
                self.old.read(source["case_id"])
                if source["stage"] == "5ae"
                else self.read(source["case_id"])
            )
            for a, b in zip(record["trace"], previous["trace"], strict=False):
                if any(
                    key not in a or canonical(a[key]) != canonical(item)
                    for key, item in b.items()
                ):
                    break
                count += 1
            if count:
                value.pop("trace")
                value.update(
                    prefix_source=source,
                    prefix_steps=count,
                    trace_suffix=record["trace"][count:],
                )
        with gzip.open(
            self.path(identity), "xt", encoding="utf-8", compresslevel=6
        ) as stream:
            json.dump(value, stream, allow_nan=False)
        return count
