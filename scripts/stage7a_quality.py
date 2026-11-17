"""Run real Python checks at the current commit, without native/control execution."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from gsunlight_repro.stage5a.maps import ROOT
from gsunlight_repro.stage7a import BASE, PUBLIC


def main() -> None:
    """Write fresh execution evidence and reject edits to frozen historical paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    if out.exists() or not out.is_relative_to(PUBLIC):
        raise ValueError("Use a fresh evidence directory under results/stage7a")
    out.mkdir(parents=True)
    changes = subprocess.check_output(
        ["git", "diff", "--name-status", BASE], cwd=ROOT, text=True, encoding="utf-8"
    ).splitlines()
    if any(not line.startswith("A\t") for line in changes):
        raise RuntimeError("Historical tracked paths changed; stop before checks")
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
            [sys.executable, "-m", "gsunlight_repro.stage7a.public_evidence"],
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
        (out / "commands.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{name}: exit {result.returncode}", flush=True)
        if result.returncode:
            raise RuntimeError(f"{name} failed; inspect preserved log")
    counts = {k: 0 for k in ("tests", "errors", "failures", "skipped")}
    for suite in ET.parse(out / "pytest.xml").getroot().iter("testsuite"):
        for key in counts:
            counts[key] += int(suite.get(key, "0"))
    if counts["tests"] < 552 or any(
        counts[k] for k in ("errors", "failures", "skipped")
    ):
        raise RuntimeError("Full Python regression suite did not pass")
    evidence = {
        "passed": True,
        "head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "platform": platform.platform(),
        "python": sys.version,
        "pytest": counts,
        "historical_tracked_changes": 0,
        "native_cpp_changed": False,
        "new_native_build_or_ctest": False,
        "new_planning_searches": 0,
        "new_control_replays": 0,
        "commands": records,
    }
    (out / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
