"""Small evidence readers and immutable development scenario access."""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import Any

from ..stage5a.maps import ROOT
from ..stage6b.scenarios import Scenario, analytic_scenarios, historical_scenario

BASE = "73bfd383971659833373434b15c499ae909c92f4"
PUBLIC = ROOT / "results/stage6c"


def read_json(path: Path) -> Any:
    """Decode existing evidence without filling missing fields."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    """Write only stage6C evidence with finite JSON values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    """Keep CSV missing values distinct from false and zero."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def boolean(value: str) -> bool:
    """Require an explicit boolean field in archived CSV."""
    if value not in ("True", "False"):
        raise ValueError(f"Not an explicit archived boolean: {value!r}")
    return value == "True"


def scenarios() -> dict[str, Scenario]:
    """Reuse only the frozen analytic tasks and the three old F maps."""
    result = {item.id: item for item in analytic_scenarios()}
    result.update(
        {name: historical_scenario(name) for name in ("F_O1", "F_N1", "F_B1")}
    )
    return result


def saved_record(folder: Path) -> dict[str, Any]:
    """Read the one existing compressed numeric record for a job."""
    with gzip.open(
        folder / "independent_record.json.gz", "rt", encoding="utf-8"
    ) as stream:
        return json.load(stream)
