"""Compare the new actual SI adapter against all13 preserved frozen cases."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from ..stage5a.analysis import write_csv
from ..stage6b.bridge import invoke_native
from .common import PUBLIC, read_json, write_json


def environment(dependency: Path) -> dict[str, str]:
    """Provide only a child-process toolchain DLL path."""
    binary = dependency / "packages/llvm-mingw-20261104-ucrt-x86_64/bin"
    return {"PATH": str(binary.resolve()) + os.pathsep + os.environ["PATH"]}


def run(
    source: Path, executable: Path, dependency: Path, local: Path, output: Path
) -> dict:
    """Check all accepted states, rejection reasons and real propagation counts."""
    rows = []
    for folder in sorted((source / "acceptance").iterdir()):
        old = read_json(folder / "output.json")
        result = invoke_native(
            executable,
            read_json(folder / "input.json"),
            local / "acceptance" / folder.name,
            environment=environment(dependency),
        ).payload
        if result["reason"] != old["reason"]:
            raise ValueError("New SI adapter rejected a different condition")
        accepted = [row for row in old["trace"] if row["accepted"]]
        if len(result["states"]) != len(accepted):
            raise ValueError("New SI adapter accepted a different interval count")
        maximum = 0.0
        for state, expected in zip(result["states"], accepted, strict=True):
            values = expected["following"]
            maximum = max(
                maximum, max(abs(a - b) for a, b in zip(state, values, strict=True))
            )
        if maximum > 1e-10 or result["ompl_version"] != "2.0.2":
            raise ValueError("New SI state mapping/version differs from frozen6B")
        rows.append(
            {
                "case": folder.name,
                "passed": True,
                "reason": result["reason"],
                "accepted_intervals": len(accepted),
                "maximum_state_error": maximum,
                "actual_propagator_calls": result["propagator_calls"],
            }
        )
    if len(rows) != 13:
        raise ValueError("Expected all13 cases before any calibration search")
    summary = {
        "passed": True,
        "cases": len(rows),
        "accepted_intervals": sum(r["accepted_intervals"] for r in rows),
        "actual_propagator_calls": sum(r["actual_propagator_calls"] for r in rows),
        "maximum_state_error": max(r["maximum_state_error"] for r in rows),
        "new_searches": 0,
    }
    write_csv(output / "c2_interface_cases.csv", rows)
    write_json(output / "c2_interface_acceptance.json", summary)
    return summary


def main() -> None:
    """Use existing or fresh deterministic6B fixtures, never search."""
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.source_root,
                args.executable,
                args.dependency_root,
                args.local_root,
                args.output,
            )
        )
    )


if __name__ == "__main__":
    main()
