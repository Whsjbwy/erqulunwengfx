"""Run and preserve the deterministic admission before the six real executions."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from gsunlight_repro.stage5a.analysis import write_csv
from gsunlight_repro.stage5a.maps import ROOT
from gsunlight_repro.stage6d.common import save_json
from gsunlight_repro.stage7b0 import PUBLIC
from gsunlight_repro.stage7b0.lqr import Limits, weights


def main() -> None:
    """Use real pytest/JUnit evidence; a nonzero result cannot open the gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PUBLIC / "admission")
    output = parser.parse_args().output.resolve()
    if output.exists() or not output.is_relative_to(PUBLIC):
        raise ValueError("Admission output must be a fresh stage7b0 directory")
    output.mkdir(parents=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_stage7b0_lqr.py",
        "-q",
        "--junitxml=" + str(output / "pytest.xml"),
    ]
    started = time.perf_counter()
    with (output / "pytest.log").open("xb") as stream:
        result = subprocess.run(
            command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False
        )
    cases = []
    if (output / "pytest.xml").is_file():
        for item in ET.parse(output / "pytest.xml").getroot().iter("testcase"):
            cases.append(
                {
                    "test": item.get("name"),
                    "time_s": float(item.get("time", "0")),
                    "passed": not any(
                        item.find(k) is not None
                        for k in ("failure", "error", "skipped")
                    ),
                }
            )
    write_csv(output / "cases.csv", cases)
    q, r, qf = weights(Limits.frozen())
    summary = {
        "passed": result.returncode == 0
        and len(cases) == 19
        and all(c["passed"] for c in cases),
        "command": command,
        "exit_code": result.returncode,
        "wall_s": time.perf_counter() - started,
        "tests": len(cases),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "Q": q.tolist(),
        "R": r.tolist(),
        "Qf": qf.tolist(),
        "finite_difference_absolute_tolerance": 2e-9,
        "new_six_task_executions": 0,
        "cpp_changed": False,
        "new_ctest_run": False,
    }
    save_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["passed"]:
        raise RuntimeError("B1 admission failed; no historical-path execution allowed")


if __name__ == "__main__":
    main()
