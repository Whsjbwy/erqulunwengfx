"""Actual full engineering checks and final commit identity, without new trials."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from gsunlight_repro.stage5a.maps import ROOT
from gsunlight_repro.stage6d.common import save_json
from gsunlight_repro.stage7b0 import BASE, PUBLIC


def main() -> None:
    """Preserve fresh logs; frozen source differences must contain additions only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    if out.exists() or not out.is_relative_to(PUBLIC):
        raise ValueError("Use a fresh quality directory inside results/stage7b0")
    out.mkdir(parents=True)
    diff = subprocess.check_output(
        ["git", "diff", "--name-status", BASE], cwd=ROOT, text=True, encoding="utf-8"
    ).splitlines()
    if any(not line.startswith("A\t") for line in diff):
        raise RuntimeError("Historical tracked files changed")
    commands = [
        (
            "compileall",
            [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"],
        ),
        (
            "pytest",
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--junitxml=" + str(out / "pytest.xml"),
            ],
        ),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        (
            "public-evidence",
            [sys.executable, "-m", "gsunlight_repro.stage7b0.public_evidence"],
        ),
    ]
    records = []
    for name, command in commands:
        started = time.perf_counter()
        with (out / f"{name}.log").open("xb") as stream:
            result = subprocess.run(
                command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False
            )
        records.append(
            {
                "check": name,
                "command": command,
                "exit_code": result.returncode,
                "wall_s": time.perf_counter() - started,
            }
        )
        save_json(out / "commands.json", records)
        print(f"{name}: exit {result.returncode}", flush=True)
        if result.returncode:
            raise RuntimeError(f"{name} failed; retained real log")
    counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for suite in ET.parse(out / "pytest.xml").getroot().iter("testsuite"):
        for key in counts:
            counts[key] += int(suite.get(key, "0"))
    if counts["tests"] < 571 or any(
        counts[key] for key in ("failures", "errors", "skipped")
    ):
        raise RuntimeError("Full regression suite did not pass")
    save_json(
        out / "evidence.json",
        {
            "passed": True,
            "head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "platform": platform.platform(),
            "python": sys.version,
            "pytest": counts,
            "historical_tracked_changes": 0,
            "cpp_changed": False,
            "new_ctest_run": False,
            "new_planning_searches_in_quality_checks": 0,
            "new_six_task_executions_in_quality_checks": 0,
            "commands": records,
        },
    )


if __name__ == "__main__":
    main()
