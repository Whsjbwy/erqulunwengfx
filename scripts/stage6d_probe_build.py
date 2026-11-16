"""Build a read-only interface diagnostic; never patch frozen OMPL or the model."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def main() -> None:
    """Preserve every build attempt and the explicit known-gap CTest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).absolute().parents[1]
    )
    args = parser.parse_args()
    dep, root = args.dependency_root, args.local_root
    root.mkdir(parents=True, exist_ok=True)
    llvm = dep / "packages/llvm-mingw-20261104-ucrt-x86_64/bin"
    cmake = dep / "packages/cmake-3.31.8-windows-x86_64/bin/cmake.exe"
    environment = {**os.environ, "PATH": str(llvm) + os.pathsep + os.environ["PATH"]}
    commands = [
        (
            "configure",
            [
                str(cmake),
                "-S",
                (args.repository_root / "native/stage6d").as_posix(),
                "-B",
                (root / "build").as_posix(),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DCMAKE_MAKE_PROGRAM=" + (dep / "packages/ninja/ninja.exe").as_posix(),
                "-DCMAKE_CXX_COMPILER="
                + (llvm / "x86_64-w64-mingw32-clang++.exe").as_posix(),
                "-DCMAKE_CXX_FLAGS=-no-canonical-prefixes "
                "-D_WIN32_WINNT=0x0A00 -DWINVER=0x0A00",
                "-DCMAKE_PREFIX_PATH=" + (dep / "prefix").as_posix(),
                "-DSTAGE6D_JSON_INCLUDE=" + (dep / "include").as_posix(),
            ],
        ),
        ("build", [str(cmake), "--build", str(root / "build"), "--parallel", "2"]),
        (
            "ctest_detect_known_gap",
            [
                str(cmake.with_name("ctest.exe")),
                "--test-dir",
                str(root / "build"),
                "--output-on-failure",
            ],
        ),
    ]
    status_path = root / "build_status.json"
    status = (
        json.loads(status_path.read_text(encoding="utf-8"))
        if status_path.exists()
        else {"commands": []}
    )
    for name, command in commands:
        log = root / f"build-{len(status['commands']):02d}-{name}.log"
        started = time.perf_counter()
        with log.open("xb") as stream:
            result = subprocess.run(
                command,
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=environment,
                check=False,
            )
        status["commands"].append(
            {
                "label": name,
                "command": command,
                "exit_code": result.returncode,
                "wall_s": time.perf_counter() - started,
                "log": log.name,
            }
        )
        status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: exit{result.returncode}", flush=True)
        if result.returncode:
            raise RuntimeError(f"Build failed; evidence retained in {log}")


if __name__ == "__main__":
    main()
