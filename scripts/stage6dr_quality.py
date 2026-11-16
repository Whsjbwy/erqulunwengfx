"""Run actual engineering checks and bind three separate interface verdicts."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from gsunlight_repro.stage6c.acceptance import environment
from gsunlight_repro.stage6c.common import read_json
from gsunlight_repro.stage6d.common import save_json


def main() -> None:
    """Keep real commands/logs; a green build alone cannot establish admission."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dependency-root", "build-root", "acceptance-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise FileExistsError("Use a fresh quality directory; preserve previous checks")
    out.mkdir(parents=True)
    python = os.sys.executable
    llvm = args.dependency_root.resolve() / (
        "packages/llvm-mingw-20261104-ucrt-x86_64/bin"
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
                str(llvm / "clang-format.exe"),
                "--dry-run",
                "--Werror",
                "-style={BasedOnStyle: LLVM, IndentWidth: 4, ColumnLimit: 100}",
                *map(str, sorted(Path("native/stage6dr").glob("*.hpp"))),
                *map(str, sorted(Path("native/stage6dr").glob("*.cpp"))),
            ],
        ),
    ]
    records = []
    for label, command in commands:
        started = time.perf_counter()
        with (out / f"{label}.log").open("xb") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        records.append(
            {
                "check": label,
                "command": command,
                "exit_code": result.returncode,
                "wall_s": time.perf_counter() - started,
            }
        )
        save_json(out / "commands.json", records)
        print(f"{label}: exit{result.returncode}", flush=True)
        if result.returncode:
            raise RuntimeError(f"Actual {label} check failed; inspect retained log")
    suites = list(ET.parse(out / "pytest.xml").getroot().iter("testsuite"))
    tests = {
        key: sum(int(s.attrib.get(key, "0")) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    build = read_json(args.build_root / "build_status.json")
    latest = build["commands"][-3:]
    if [r["label"] for r in latest] != ["configure", "build", "ctest"] or any(
        r["exit_code"] for r in latest
    ):
        raise RuntimeError("The isolated native build/check gate did not pass")
    ctest = (args.build_root / latest[-1]["log"]).read_text(encoding="utf-8")
    (out / "ctest.log").write_text(ctest, encoding="utf-8")
    if "100% tests passed, 0 tests failed out of 4" not in ctest:
        raise RuntimeError("Four actual CTests are required")
    original = read_json(args.acceptance_root / "original_failure_reproduced.json")
    acceptance = read_json(args.acceptance_root / "acceptance_summary.json")
    if not (
        original["mismatch_detected"]
        and original["interval_index"] == 89
        and original["expected_accepted_steps"] == 1
        and original["actual_accepted_steps"] == 0
        and acceptance["local_model_interface_passed"]
        and acceptance["boundary_cases"] == 69
        and acceptance["legacy_cases"] == 13
        and acceptance["legacy_accepted_intervals"] == 930
        and acceptance["map_accepted_intervals"] == 2440
        and acceptance["terrain_1_intervals"] == 370
        and acceptance["new_planning_searches"] == 0
        and not acceptance["h1_authorized"]
    ):
        raise RuntimeError(
            "Original failure and repaired acceptance are separate gates"
        )
    save_json(out / "forbidden-plan-input.json", {"mode": "plan"}, exclusive=True)
    guard_command = [
        str(args.build_root.resolve() / "build/auv6dr_runner.exe"),
        str(out / "forbidden-plan-input.json"),
        str(out / "forbidden-plan-output.json"),
    ]
    guard = subprocess.run(
        guard_command,
        capture_output=True,
        text=True,
        env=environment(args.dependency_root),
        timeout=10,
    )
    rejected = (
        guard.returncode == 1
        and "Only deterministic inspect/replay" in guard.stderr
        and not (out / "forbidden-plan-output.json").exists()
    )
    save_json(
        out / "forbidden-plan-evidence.json",
        {
            "command": guard_command,
            "exit_code": guard.returncode,
            "stdout": guard.stdout,
            "stderr": guard.stderr,
            "rejected_before_geometry_or_search": rejected,
        },
    )
    if (
        not rejected
        or tests["tests"] < 534
        or any(tests[key] for key in ("failures", "errors", "skipped"))
    ):
        raise RuntimeError("Scope guard or full Python tests failed")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    expected = os.environ.get("STAGE6DR_HEAD")
    if expected is not None and expected != head:
        raise RuntimeError("CI checkout differs from the actual final PR HEAD")
    result = {
        "checked_out_head": head,
        "requested_pr_head": expected,
        "exact_pr_head_ci": expected == head,
        "platform": platform.platform(),
        "pytest": tests,
        "engineering_checks_passed": True,
        "original_adapter_mismatch_still_detected": True,
        "new_model_interface_passed": True,
        "model_interface": "MODEL-INTERFACE PASS",
        "acceptance": acceptance,
        "native_build": build,
        "new_planning_searches": 0,
        "h1_authorized": False,
        "scope": "Only interface acceptance; stop for researcher review",
    }
    save_json(out / "head-evidence.json", result, exclusive=True)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
