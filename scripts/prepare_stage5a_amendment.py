"""Preserve the aborted root and link every unchanged completed experiment once."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import types
from collections import Counter
from pathlib import Path

import numpy as np

from gsunlight_repro.stage5a.maps import ROOT, load_scene, read_config
from gsunlight_repro.stage5a.runner import Runner


def prepare(old: Path, new: Path, output: Path) -> dict:
    """Validate unchanged numeric inputs before creating Windows directory links."""
    old, new = old.resolve(), new.resolve()
    allowed = ROOT.parent / "local_only"
    if (
        os.name != "nt"
        or not old.is_relative_to(allowed)
        or not new.is_relative_to(allowed)
        or old == new
    ):
        raise ValueError(
            "One-off Windows reuse must stay within local_only sibling roots"
        )
    if new.parent != old.parent:
        raise ValueError("Reuse roots must be siblings, preventing reference loops")
    if new.exists():
        for child in new.iterdir():
            if child.is_dir() and child.resolve().parent != old:
                raise FileExistsError("Amended root contains non-reference trials")
    previous = json.loads((old / "configuration.json").read_text(encoding="utf-8"))
    if previous["protocol"] != read_config("stage5a_protocol.json"):
        raise ValueError("Search, vehicle and tracking configuration must be unchanged")
    source = subprocess.run(
        ["git", "show", "2096266:src/gsunlight_repro/stage5a/maps.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    name = "gsunlight_repro.stage5a._frozen_map_recipe"
    original = types.ModuleType(name)
    original.__file__ = str(ROOT / "src/gsunlight_repro/stage5a/maps.py")
    original.__package__ = "gsunlight_repro.stage5a"
    sys.modules[name] = original
    exec(compile(source, original.__file__, "exec"), original.__dict__)
    unchanged = 0
    for specification in previous["maps"]["maps"]:
        scene_id = specification["id"]
        before = original.load_scene(scene_id, previous["maps"])
        after = load_scene(scene_id)
        equal = np.array_equal(before.grid.occupancy, after.grid.occupancy)
        if scene_id == "H5_O2":
            if equal:
                raise ValueError("The duplicate O2 geometry was not corrected")
            continue
        same_ceiling = (
            before.ceiling is None
            and after.ceiling is None
            or before.ceiling is not None
            and after.ceiling is not None
            and np.array_equal(before.ceiling.occupancy, after.ceiling.occupancy)
        )
        if (
            not equal
            or not same_ceiling
            or before.start != after.start
            or before.goal != after.goal
            or before.witness != after.witness
        ):
            raise ValueError(f"Inputs changed for an already-used scene: {scene_id}")
        unchanged += 1
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in old.glob("*/result.json")
    ]
    phases = Counter(item["row"]["phase"] for item in records)
    if dict(phases) != {"pilot": 135, "development": 45, "holdout": 5} or any(
        item["row"]["scene"] == "H5_O2" for item in records
    ):
        raise ValueError("Unexpected completed matrix; review before any reuse")
    runner = Runner(new, output)

    def literal(path: Path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    command = (
        "$ErrorActionPreference='Stop'; "
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$OutputEncoding=[Console]::OutputEncoding; "
        f"$sourceRoot={literal(old)}; $targetRoot={literal(new)}; "
        "Get-ChildItem -LiteralPath $sourceRoot -Directory | "
        "Where-Object { Test-Path -LiteralPath "
        "(Join-Path $_.FullName 'result.json') } | "
        "ForEach-Object { $link=Join-Path $targetRoot $_.Name; "
        "if (-not (Test-Path -LiteralPath $link)) { "
        "New-Item -ItemType Junction -Path $link "
        "-Target $_.FullName | Out-Null } }"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace"))
    if len(list(new.glob("*/result.json"))) != len(records):
        raise ValueError("Incomplete reference creation; retain both roots for review")
    for phase, count in (("pilot", 135), ("development", 45)):
        (new / f"{phase}_completed.json").write_text(
            json.dumps(
                {
                    "phase": phase,
                    "completed": True,
                    "reused_trials": count,
                    "source_root": str(old),
                }
            ),
            encoding="utf-8",
        )
    provenance = {
        "reason": (
            "Correct identical O1/O2 before any O2 planning; "
            "never select on performance"
        ),
        "unchanged_map_recipes_verified_against_frozen_code": unchanged,
        "changed_scene_only": "H5_O2",
        "reused_complete_trials": len(records),
        "reused_phase_counts": dict(phases),
        "original_root": str(old),
        "interrupted_original_trials": [
            p.parent.name
            for p in old.glob("*/operator_stop.json")
            if not (p.parent / "result.json").exists()
        ],
        "storage": "Junctions reference original single-copy immutable results",
        "protocol_equal": previous["protocol"] == runner.protocol,
    }
    (new / "reuse_provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )
    public = {key: value for key, value in provenance.items() if key != "original_root"}
    (output / "map_amendment_regression.json").write_text(
        json.dumps(public, indent=2), encoding="utf-8"
    )
    return public


def main() -> None:
    """Apply the documented one-off correction; fresh replications need no reuse."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--amended", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5a"))
    args = parser.parse_args()
    print(json.dumps(prepare(args.original, args.amended, args.output)))


if __name__ == "__main__":
    main()
