"""Build only the new adapter, reusing the pinned official6B dependency tree."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def build(repository: Path, dependency: Path, root: Path, jobs: int) -> None:
    """Preserve every configure/build/test attempt in a new local tree."""
    if not 1 <= jobs <= 2 or root.resolve() == dependency.resolve():
        raise ValueError("Use1-2 workers and a new stage6C build directory")
    root.mkdir(parents=True, exist_ok=True)
    llvm = dependency / "packages/llvm-mingw-20261104-ucrt-x86_64/bin"
    cmake = dependency / "packages/cmake-3.31.8-windows-x86_64/bin/cmake.exe"
    ninja = dependency / "packages/ninja/ninja.exe"
    if not ninja.is_file():
        ninja = dependency / "packages/ninja.exe"
    if not ninja.is_file():
        matches = list((dependency / "packages").rglob("ninja.exe"))
        if len(matches) != 1:
            raise FileNotFoundError("Expected exactly one pinned Ninja")
        ninja = matches[0]
    json_headers = list(dependency.rglob("nlohmann/json.hpp"))
    if len(json_headers) != 1:
        raise FileNotFoundError("Expected one pinned nlohmann JSON header")
    include = json_headers[0].parent.parent
    environment = os.environ.copy()
    environment["PATH"] = str(llvm) + os.pathsep + environment["PATH"]
    temporary = root / "tmp"
    temporary.mkdir(exist_ok=True)
    environment.update(TEMP=str(temporary), TMP=str(temporary))
    status_path = root / "build_status.json"
    status = (
        json.loads(status_path.read_text(encoding="utf-8"))
        if status_path.exists()
        else {
            "official_ompl": "2.0.2",
            "dependency_root": str(dependency),
            "commands": [],
        }
    )
    flags = "-no-canonical-prefixes -D_WIN32_WINNT=0x0A00 -DWINVER=0x0A00"
    configure = [
        str(cmake),
        "-S",
        (repository / "native/stage6c").as_posix(),
        "-B",
        (root / "build").as_posix(),
        "-G",
        "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_POLICY_DEFAULT_CMP0176=NEW",
        "-DCMAKE_MAKE_PROGRAM=" + ninja.as_posix(),
        "-DCMAKE_CXX_COMPILER=" + (llvm / "x86_64-w64-mingw32-clang++.exe").as_posix(),
        "-DCMAKE_CXX_FLAGS=" + flags,
        "-DCMAKE_PREFIX_PATH=" + (dependency / "prefix").as_posix(),
        "-DSTAGE6C_JSON_INCLUDE=" + include.as_posix(),
    ]
    commands = [
        ("configure", configure),
        (
            "build",
            [str(cmake), "--build", str(root / "build"), "--parallel", str(jobs)],
        ),
        (
            "ctest",
            [
                str(cmake.with_name("ctest.exe")),
                "--test-dir",
                str(root / "build"),
                "--output-on-failure",
            ],
        ),
    ]
    for label, command in commands:
        log = root / f"build-{len(status['commands']):02d}-{label}.log"
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
                "label": label,
                "command": command,
                "exit_code": result.returncode,
                "wall_s": time.perf_counter() - started,
                "log": log.name,
            }
        )
        status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        print(f"{label}: exit{result.returncode}; {log.name}", flush=True)
        if result.returncode:
            raise RuntimeError(f"Native build failed; preserved evidence in {log}")


def main() -> None:
    """Accept external source/build roots without altering historical outputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).absolute().parents[1]
    )
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    build(args.repository_root, args.dependency_root, args.local_root, args.jobs)


if __name__ == "__main__":
    main()
