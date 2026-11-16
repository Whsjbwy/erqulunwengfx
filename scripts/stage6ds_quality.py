"""Actual full engineering checks, real planner admission and exact HEAD proof."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from gsunlight_repro.stage5a.maps import ROOT
from gsunlight_repro.stage6c.common import read_json
from gsunlight_repro.stage6d.common import save_json
from gsunlight_repro.stage6ds import PUBLIC


def main() -> None:
    """Preserve fresh check logs; no performance searches are run here."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dependency-root", "build-root", "acceptance-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(PUBLIC):
        raise ValueError("Use a fresh quality output inside results/stage6ds")
    out.mkdir(parents=True)
    python = os.sys.executable
    clang = args.dependency_root.resolve() / (
        "packages/llvm-mingw-20261104-ucrt-x86_64/bin/clang-format.exe"
    )
    commands = [
        ("compileall", [python, "-m", "compileall", "-q", "src", "tests", "scripts"]),
        (
            "pytest",
            [python, "-m", "pytest", "-q", "--junitxml=" + str(out / "pytest.xml")],
        ),
        ("ruff", [python, "-m", "ruff", "check", "."]),
        ("python-format", [python, "-m", "ruff", "format", "--check", "."]),
        (
            "clang-format",
            [
                str(clang),
                "--dry-run",
                "--Werror",
                "-style={BasedOnStyle: LLVM, IndentWidth: 4, ColumnLimit: 100}",
                *map(str, sorted(Path("native/stage6ds").glob("*.hpp"))),
                *map(str, sorted(Path("native/stage6ds").glob("*.cpp"))),
            ],
        ),
    ]
    records = []
    for name, command in commands:
        started = time.perf_counter()
        with (out / f"{name}.log").open("xb") as stream:
            process = subprocess.run(
                command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False
            )
        records.append(
            {
                "check": name,
                "command": command,
                "exit_code": process.returncode,
                "wall_s": time.perf_counter() - started,
            }
        )
        save_json(out / "commands.json", records)
        print(f"{name}: exit{process.returncode}", flush=True)
        if process.returncode:
            raise RuntimeError(f"Actual {name} check failed; retained original log")
    suites = ET.parse(out / "pytest.xml").getroot().iter("testsuite")
    counts = {k: 0 for k in ("tests", "failures", "errors", "skipped")}
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.attrib.get(key, "0"))
    if counts["tests"] < 539 or any(
        counts[k] for k in ("failures", "errors", "skipped")
    ):
        raise RuntimeError("Complete regression suite did not pass")
    build = read_json(args.build_root / "build_status.json")
    latest = build["commands"][-3:]
    if [r["label"] for r in latest] != ["configure", "build", "ctest"] or any(
        r["exit_code"] for r in latest
    ):
        raise RuntimeError("Native build gate did not pass")
    ctest = (args.build_root / latest[-1]["log"]).read_text(encoding="utf-8")
    if "100% tests passed, 0 tests failed out of 5" not in ctest:
        raise RuntimeError("Five actual native tests must pass")
    (out / "ctest.log").write_text(ctest, encoding="utf-8")
    gate = read_json(args.acceptance_root / "acceptance_summary.json")
    original = read_json(args.acceptance_root / "original_failure.json")
    if not (
        gate["passed"]
        and gate["boundary_cases"] == 69
        and gate["legacy_cases"] == 13
        and gate["map_accepted_intervals"] == 2440
        and gate["terrain_1_intervals"] == 370
        and gate["planner_identity_checks"] == 3
        and gate["new_planning_searches"] == 0
        and original["mismatch_detected"]
        and original["interval_index"] == 89
        and original["expected_accepted_steps"] == 1
        and original["actual_accepted_steps"] == 0
    ):
        raise RuntimeError(
            "Actual-entry acceptance/original failure evidence is incomplete"
        )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    expected = os.environ.get("STAGE6DS_HEAD")
    if expected is not None and expected != head:
        raise RuntimeError("Checked out HEAD differs from the final PR HEAD")
    result = {
        "checked_out_head": head,
        "requested_pr_head": expected,
        "exact_pr_head_ci": expected == head,
        "platform": platform.platform(),
        "pytest": counts,
        "engineering_checks_passed": True,
        "original_adapter_mismatch_still_detected": True,
        "new_model_interface_passed": True,
        "actual_planner_identity_passed": True,
        "acceptance": gate,
        "native_build": build,
        "new_planning_searches_in_quality_checks": 0,
        "h1_implementation_authorized": False,
    }
    save_json(out / "head-evidence.json", result, exclusive=True)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
