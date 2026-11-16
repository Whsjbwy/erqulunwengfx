"""Capture real stage6D checks, full logs and JUnit without changing old evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from gsunlight_repro.stage5a.analysis import write_csv
from gsunlight_repro.stage6c.acceptance import environment as native_environment
from gsunlight_repro.stage6d.common import PUBLIC, save_json


def main() -> None:
    """Use separate exclusive folders for gate and final checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("gate", "final"), required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--probe-root", type=Path)
    args = parser.parse_args()
    folder = args.local_root / args.phase
    folder.mkdir(parents=True, exist_ok=False)
    llvm = args.dependency_root / "packages/llvm-mingw-20261104-ucrt-x86_64/bin"
    environment = {**os.environ, **native_environment(args.dependency_root)}
    tests = (
        ["tests/test_stage6d_reference.py", "tests/test_stage6d_maps.py"]
        if args.phase == "gate"
        else []
    )
    scope = (
        ["src/gsunlight_repro/stage6d", *tests, "scripts/stage6d_checks.py"]
        if tests
        else ["."]
    )
    junit = folder / "pytest.xml"
    commands = [
        (
            "compile",
            [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"],
        ),
        (
            "pytest",
            [sys.executable, "-m", "pytest", "-q", *tests, "--junitxml=" + str(junit)],
        ),
        ("ruff", [sys.executable, "-m", "ruff", "check", *scope]),
        ("format", [sys.executable, "-m", "ruff", "format", "--check", *scope]),
        (
            "clang-format",
            [
                str(llvm / "clang-format.exe"),
                "--dry-run",
                "--Werror",
                "-style={BasedOnStyle: LLVM, IndentWidth: 4, ColumnLimit: 100}",
                "native/stage6c/adapter.hpp",
                "native/stage6c/adapter_tests.cpp",
                "native/stage6c/ompl_runner.cpp",
            ],
        ),
    ]
    if args.phase == "final":
        if args.probe_root is None:
            raise ValueError("Final checks require the separate diagnostic build")
        commands[-1][1].append("native/stage6d/interface_probe.cpp")
        ctest = (
            args.dependency_root / "packages/cmake-3.31.8-windows-x86_64/bin/ctest.exe"
        )
        commands.extend(
            [
                (
                    "ctest_frozen_two",
                    [
                        str(ctest),
                        "--test-dir",
                        str(args.build_root / "build"),
                        "--output-on-failure",
                    ],
                ),
                (
                    "ctest_detect_known_gap",
                    [
                        str(ctest),
                        "--test-dir",
                        str(args.probe_root / "build"),
                        "--output-on-failure",
                    ],
                ),
            ]
        )
    evidence = []
    for name, command in commands:
        started = time.perf_counter()
        result = subprocess.run(
            command, capture_output=True, env=environment, check=False
        )
        raw = result.stdout + result.stderr
        (folder / f"{name}.log").write_bytes(raw)
        row = {
            "name": name,
            "command": command,
            "exit_code": result.returncode,
            "wall_s": time.perf_counter() - started,
            "output": raw.decode("utf-8", errors="replace"),
        }
        evidence.append(row)
        save_json(
            PUBLIC / f"{args.phase}_checks.json",
            {"passed": all(r["exit_code"] == 0 for r in evidence), "checks": evidence},
        )
        print(f"{name}: exit{result.returncode}", flush=True)
        if result.returncode:
            raise RuntimeError(
                f"Check failed; complete output retained at {folder / (name + '.log')}"
            )
    cases = [
        {
            "test": row.attrib["classname"] + "." + row.attrib["name"],
            "time_s": row.attrib.get("time"),
            "passed": len(row) == 0,
        }
        for row in ET.parse(junit).getroot().iter("testcase")
    ]
    write_csv(PUBLIC / f"{args.phase}_pytest_cases.csv", cases)
    result = {
        "passed": True,
        "pytest_cases": len(cases),
        "checks": evidence,
        "new_planning_searches": 0,
        "log_directory": str(folder),
    }
    save_json(PUBLIC / f"{args.phase}_checks.json", result)
    if args.phase == "gate":
        save_json(
            PUBLIC / "d1_acceptance.json",
            {
                "passed": True,
                "actual_pytest_cases": len(cases),
                "gate_checks": "gate_checks.json",
            },
        )
    print(json.dumps({"passed": True, "pytest_cases": len(cases)}))


if __name__ == "__main__":
    main()
