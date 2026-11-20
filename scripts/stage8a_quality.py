"""Save actual Python checks and history-preservation evidence, without trials."""

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

BASE = "c99588362f72348260a33e463cb94774d2b3896f"


def main() -> None:
    """Require a fresh directory and retain failure output before stopping."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    out = parser.parse_args().output.resolve()
    if not out.is_relative_to(ROOT.parent) or out.exists():
        raise ValueError("Use a fresh output directory within the project workspace")
    out.mkdir(parents=True)
    changes = subprocess.check_output(
        ["git", "diff", "--name-status", BASE], cwd=ROOT, text=True, encoding="utf-8"
    ).splitlines()
    if any(not change.startswith("A\t") for change in changes):
        raise RuntimeError("Historical tracked files changed")
    commands = {
        "compileall": [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            "src",
            "tests",
            "scripts",
        ],
        "pytest": [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml=" + str(out / "pytest.xml"),
        ],
        "ruff": [sys.executable, "-m", "ruff", "check", "."],
        "format": [sys.executable, "-m", "ruff", "format", "--check", "."],
        "review": [sys.executable, "-m", "gsunlight_repro.stage8a.review"],
    }
    records = []
    for name, command in commands.items():
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
            json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{name}: exit {result.returncode}", flush=True)
        if result.returncode:
            raise RuntimeError(f"{name} failed; actual output retained in {out}")
    counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    for suite in ET.parse(out / "pytest.xml").getroot().iter("testsuite"):
        for key in counts:
            counts[key] += int(suite.get(key, "0"))
    if counts["tests"] < 584 or any(
        counts[key] for key in ("failures", "errors", "skipped")
    ):
        raise RuntimeError("The full deterministic regression suite did not pass")
    evidence = {
        "passed": True,
        "head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "platform": platform.platform(),
        "python": sys.version,
        "pytest": counts,
        "historical_tracked_changes": 0,
        "new_cpp_checks": False,
        "new_flow_model_executions": 0,
        "new_planning_searches": 0,
        "gate_A": "NEED_MORE_EVIDENCE",
        "commands": records,
    }
    (out / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
