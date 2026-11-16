"""Build only6DS; reuse the frozen command recorder and official dependencies."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from stage6b_build import Builder


def main() -> None:
    """Keep isolated logs with at most two workers and no dependency downloads."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument(
        "--repository-root", type=Path, default=Path(__file__).absolute().parents[1]
    )
    args = parser.parse_args()
    dep, root, repo = args.dependency_root, args.local_root, args.repository_root
    if root.resolve().is_relative_to(dep.resolve()):
        raise ValueError("Do not write into historical dependencies")
    builder = Builder(root, 2, repo)
    if builder.record.get("stage", "6DS") != "6DS":
        raise ValueError("Refusing another stage's build directory")
    builder.record["stage"] = "6DS"
    llvm = dep / "packages/llvm-mingw-20261104-ucrt-x86_64/bin"
    builder.environment["PATH"] = str(llvm.absolute()) + os.pathsep + os.environ["PATH"]
    temporary = root / "tmp"
    temporary.mkdir(exist_ok=True)
    builder.environment.update(TEMP=str(temporary), TMP=str(temporary))
    cmake = dep / "packages/cmake-3.31.8-windows-x86_64/bin/cmake.exe"
    builder.command(
        "configure",
        [
            str(cmake),
            "-S",
            (repo / "native/stage6ds").as_posix(),
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
            "-DSTAGE6DR_JSON_INCLUDE=" + (dep / "include").as_posix(),
        ],
    )
    builder.command(
        "build", [str(cmake), "--build", str(root / "build"), "--parallel", "2"]
    )
    builder.command(
        "ctest",
        [
            str(cmake.with_name("ctest.exe")),
            "--test-dir",
            str(root / "build"),
            "--output-on-failure",
        ],
    )


if __name__ == "__main__":
    main()
