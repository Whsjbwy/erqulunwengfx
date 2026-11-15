"""Archive actual HEAD, JUnit and native acceptance without a commit loop."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def read(path: Path) -> dict:
    """Require a real previously produced CI result."""
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """Run after successful checks and bind artifact evidence to checked-out HEAD."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("results/stage6c/ci-validation")
    )
    args = parser.parse_args()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != os.environ["STAGE6C_HEAD"]:
        raise RuntimeError("CI checkout does not match the requested final HEAD")
    junit = ET.parse(args.output / "pytest.xml").getroot()
    suites = list(junit.iter("testsuite"))
    tests = {
        key: sum(int(s.attrib.get(key, "0")) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    native = read(args.output / "c2_interface_acceptance.json")
    frozen = read(Path("results/stage6c/ci-frozen/interface_acceptance.json"))
    build = read(args.build_root / "build_status.json")
    if (
        tests["failures"]
        or tests["errors"]
        or not native["passed"]
        or not frozen["passed"]
    ):
        raise RuntimeError("Cannot publish a passing proof for failed checks")
    if build["commands"][-1]["label"] != "ctest" or build["commands"][-1]["exit_code"]:
        raise RuntimeError("Missing actual CTest success")
    result = {
        "checked_out_head": head,
        "requested_pr_head": os.environ["STAGE6C_HEAD"],
        "head_matches": True,
        "platform": platform.platform(),
        "pytest": tests,
        "frozen_interface": frozen,
        "stage6c_interface": native,
        "official_dependency_build": read(args.dependency_root / "build_status.json"),
        "stage6c_build": build,
        "ctest_log": (
            args.build_root / "build/Testing/Temporary/LastTest.log"
        ).read_text(encoding="utf-8"),
        "new_planning_searches": 0,
        "note": (
            "Only deterministic synthetic fixtures, no local research "
            "trajectories or dependency sources. Git object identifier "
            "is not an extra file checksum manifest."
        ),
    }
    (args.output / "head-evidence.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "head": head,
                "pytest": tests,
                "native_cases": native["cases"],
                "head_matches": True,
                "planning_searches": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
