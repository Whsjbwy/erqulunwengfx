"""Read-only full native audit of6B/6C and fresh official-interface acceptance."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from ..stage5a.analysis import write_csv
from ..stage5a.maps import ROOT
from ..stage6b.replay import audit_controls
from ..stage6c.acceptance import run as accept_interface
from ..stage6c.common import boolean, read_csv, read_json, saved_record, scenarios
from ..stage6c.reference import certify_los
from .common import BASE, PUBLIC, save_json


def run(
    source: Path,
    previous: Path,
    dependency: Path,
    build: Path,
    executable: Path,
    output: Path,
) -> dict[str, Any]:
    """Re-certify every old returned control, keeping the known missing clock."""
    changed = subprocess.run(
        ["git", "diff", "--name-status", "--diff-filter=MD", BASE],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if changed.strip():
        raise RuntimeError("Historical tracked files were modified or deleted")
    ci = read_json(
        ROOT.parent / "local_only/stage6c_quality/final-head-evidence-e39d88a.json"
    )
    if (
        ci["checked_out_head"] != BASE
        or not ci["head_matches"]
        or ci["pytest"]["failures"]
    ):
        raise RuntimeError("Previous exact-HEAD CI proof does not match")
    status = read_json(build / "build_status.json")
    if (
        status["commands"][-1]["label"] != "ctest"
        or status["commands"][-1]["exit_code"]
    ):
        raise RuntimeError("Fresh native build/CTest not passed")
    interface = accept_interface(
        source, executable, dependency, build / "interface", output / "d0_interface"
    )
    cases, rows, totals = scenarios(), [], {}
    for stage, folder in (("6b", source), ("6c", previous)):
        records = read_csv(ROOT / f"results/stage{stage}/planning_runs.csv")
        expected = 36 if stage == "6b" else 72
        if len(records) != expected or len({r["job_id"] for r in records}) != expected:
            raise RuntimeError("Previous run roster is incomplete")
        if {p.name for p in (folder / "search").iterdir()} != {
            r["job_id"] for r in records
        }:
            raise RuntimeError("Previous raw directory denominator differs")
        native_m = strict_s = intervals = los_intervals = missing = 0
        for old in records:
            raw = folder / "search" / old["job_id"]
            payload, stored = read_json(raw / "output.json"), saved_record(raw)
            case = cases[old["scenario"]]
            audit, trace = audit_controls(case, payload)
            if not audit["independent_audit_passed"]:
                raise RuntimeError("Previous native control safety/model audit failed")
            clock_key = (
                "independent_certificate_finish_s"
                if stage == "6b"
                else "best_independent_certificate_finish_s"
            )
            clock = float(old[clock_key]) if old[clock_key] else None
            model = bool(audit["model_feasible"] and clock is not None and clock <= 10)
            if (
                model != boolean(old["model_feasible"])
                or old["native_status"] != payload["status"]
            ):
                raise RuntimeError(
                    "Previous success/status disagrees with raw evidence"
                )
            missing += clock is None
            intervals += len(trace)
            if model:
                los = certify_los(stored["los_trace"], case)
                los_intervals += los["los_intervals"]
                if boolean(old["los_strict_success"]) and not (
                    los["full_margin_safe"] and los["goal_reached"]
                ):
                    raise RuntimeError("Previous LOS strict success is unsafe")
            native_m += model
            strict_s += boolean(old["los_strict_success"])
            rows.append(
                {
                    "stage": stage,
                    "job_id": old["job_id"],
                    "native_M": model,
                    "original_clock_s": clock,
                    "intervals": len(trace),
                    "audit_passed": True,
                }
            )
        totals[stage] = {
            "K": len(records),
            "M": native_m,
            "S": strict_s,
            "native_intervals": intervals,
            "LOS_intervals": los_intervals,
            "missing_clocks_retained": missing,
        }
    if (totals["6b"]["M"], totals["6b"]["S"], totals["6c"]["M"], totals["6c"]["S"]) != (
        21,
        11,
        46,
        34,
    ):
        raise RuntimeError("Historical actual denominators differ")
    write_csv(output / "d0_historical_runs.csv", rows)
    result = {
        "passed": True,
        "base_commit": BASE,
        "previous_exact_head_ci": ci["pytest"],
        "fresh_interface": interface,
        "historical": totals,
        "official_ompl": "2.0.2",
        "license": "BSD-3-Clause",
        "build": status,
        "new_searches": 0,
        "historical_modifications": [],
    }
    save_json(output / "d0_audit.json", result)
    return result


def main() -> None:
    """Accept explicit immutable evidence and isolated build roots."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "source-root",
        "previous-root",
        "dependency-root",
        "build-root",
        "executable",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.source_root,
                args.previous_root,
                args.dependency_root,
                args.build_root,
                args.executable,
                args.output,
            )
        )
    )


if __name__ == "__main__":
    main()
