"""Bind successful engineering checks and a failed scientific gate to actual HEAD."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def read(path: Path) -> dict:
    """Require a real result from preceding CI steps."""
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """Do not turn reproduction of a known rejection into passing admission."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dependency-root", "build-root", "probe-root", "frozen-output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("results/stage6d/ci-validation")
    )
    args = parser.parse_args()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != os.environ["STAGE6D_HEAD"]:
        raise RuntimeError("CI checkout is not the final PR HEAD")
    suites = list(ET.parse(args.output / "pytest.xml").getroot().iter("testsuite"))
    tests = {
        key: sum(int(s.attrib.get(key, "0")) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    native = read(args.output / "c2_interface_acceptance.json")
    frozen = read(args.frozen_output / "interface_acceptance.json")
    diagnostic = read(args.output / "model_mapping_failure.json")
    builds = {
        "official": read(args.dependency_root / "build_status.json"),
        "frozen_adapter": read(args.build_root / "build_status.json"),
        "diagnostic": read(args.probe_root / "build_status.json"),
    }
    if tests["failures"] or tests["errors"] or tests["skipped"] or tests["tests"] < 529:
        raise RuntimeError("Full Python checks did not pass")
    if not native["passed"] or not frozen["passed"] or native["cases"] != 13:
        raise RuntimeError("Historical deterministic interface acceptance failed")
    if (
        diagnostic["model_mapping_gate_passed"]
        or diagnostic["admission"] != "BLOCKED"
        or not diagnostic["mismatch_detected"]
    ):
        raise RuntimeError("The documented BLOCKED scientific gate was not reproduced")
    if any(row["exit_code"] for build in builds.values() for row in build["commands"]):
        raise RuntimeError("A native build/check failed")
    result = {
        "checked_out_head": head,
        "requested_pr_head": os.environ["STAGE6D_HEAD"],
        "head_matches": True,
        "platform": platform.platform(),
        "pytest": tests,
        "frozen_interface": frozen,
        "actual_si_interface": native,
        "builds": builds,
        "model_mapping_failure": diagnostic,
        "engineering_checks_passed": True,
        "scientific_admission": "BLOCKED",
        "model_mapping_gate_passed": False,
        "new_planning_searches": 0,
        "ctest_logs": [
            (root / "build/Testing/Temporary/LastTest.log").read_text(encoding="utf-8")
            for root in (args.build_root, args.probe_root)
        ],
        "scope": "CI success reproduces BLOCKED; it does not approve H1.",
    }
    (args.output / "head-evidence.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "head": head,
                "head_matches": True,
                "pytest": tests,
                "engineering_checks_passed": True,
                "scientific_admission": "BLOCKED",
                "model_mapping_gate_passed": False,
                "new_planning_searches": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
