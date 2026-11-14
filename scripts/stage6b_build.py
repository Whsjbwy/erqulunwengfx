"""Build unmodified official OMPL with a private native Windows toolchain."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "llvm": (
        "https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/"
        "llvm-mingw-20261104-ucrt-x86_64.zip",
        "llvm-mingw-20261104-ucrt-x86_64",
    ),
    "cmake": (
        "https://github.com/Kitware/CMake/releases/download/v3.31.8/"
        "cmake-3.31.8-windows-x86_64.zip",
        "cmake-3.31.8-windows-x86_64",
    ),
    "ninja": (
        "https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip",
        "ninja",
    ),
    "boost": (
        "https://github.com/boostorg/boost/releases/download/boost-1.89.0/"
        "boost-1.89.0-cmake.tar.xz",
        "boost-1.89.0",
    ),
    "eigen": (
        "https://gitlab.com/libeigen/eigen/-/archive/3.4.0/eigen-3.4.0.tar.gz",
        "eigen-3.4.0",
    ),
    "ompl": (
        "https://github.com/ompl/ompl/archive/refs/tags/2.0.2.tar.gz",
        "ompl-2.0.2",
    ),
}


class Builder:
    """Keep source, tools, logs and compiled products in one explicit local tree."""

    def __init__(self, local: Path, jobs: int, repository: Path = ROOT) -> None:
        # Preserve an explicitly supplied temporary drive alias for native tools.
        self.local = local.absolute()
        self.repository = repository.absolute()
        if self.repository.resolve() != ROOT:
            raise ValueError("Repository alias does not resolve to this checkout")
        if self.local.resolve().is_relative_to(ROOT):
            raise ValueError(
                "Build dependencies must remain outside the Git repository"
            )
        if not 1 <= jobs <= 2:
            raise ValueError("Stage6B permits at most two compilation workers")
        self.local.mkdir(parents=True, exist_ok=True)
        self.jobs = jobs
        self.record_file = self.local / "build_status.json"
        self.record = (
            json.loads(self.record_file.read_text(encoding="utf-8"))
            if self.record_file.exists()
            else {"packages": {}, "commands": [], "file_hash_manifests": False}
        )
        self.environment = os.environ.copy()

    def save(self) -> None:
        """Persist actual outcomes, including unsuccessful attempts."""
        self.record_file.write_text(
            json.dumps(self.record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def package(self, name: str) -> Path:
        """Download a pinned official archive once and safely unpack it locally."""
        url, directory = PACKAGES[name]
        destination = self.local / "packages" / directory
        if self.record["packages"].get(name, {}).get("extracted"):
            if not destination.is_dir():
                raise FileNotFoundError(destination)
            return destination
        cache = self.local / "downloads"
        cache.mkdir(exist_ok=True)
        archive = cache / (name + (".zip" if url.endswith(".zip") else ".tar"))
        print(f"Downloading {name} from {url}", flush=True)
        request = urllib.request.Request(url, headers={"User-Agent": "AUV-stage6b"})
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=60) as response:
            total = 0
            with archive.open("xb") as stream:
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
                    total += len(chunk)
                    if total % (32 * 1024 * 1024) == 0:
                        print(f"{name}: {total // (1024 * 1024)} MiB", flush=True)
        entry = {
            "url": url,
            "downloaded_bytes": total,
            "download_s": time.perf_counter() - start,
            "extracted": False,
        }
        self.record["packages"][name] = entry
        self.save()
        target = destination if name == "ninja" else destination.parent
        target.mkdir(parents=True, exist_ok=True)
        if url.endswith(".zip"):
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    if (
                        not (target / member.filename)
                        .resolve()
                        .is_relative_to(target.resolve())
                    ):
                        raise ValueError("Archive path escapes extraction directory")
                source.extractall(target)
        else:
            with tarfile.open(archive, "r:*") as source:
                source.extractall(target, filter="data")
        if not destination.is_dir():
            raise FileNotFoundError(f"Unexpected source archive layout: {destination}")
        entry["extracted"] = True
        self.save()
        archive.unlink()
        print(f"Extracted {name}; removed its download archive", flush=True)
        return destination

    def command(self, label: str, arguments: list[str]) -> None:
        """Capture a real build command without discarding failure logs."""
        index = len(self.record["commands"])
        log = self.local / f"build-{index:02d}-{label}.log"
        start = time.perf_counter()
        with log.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(arguments, ensure_ascii=False) + "\n")
            stream.flush()
            result = subprocess.run(
                arguments,
                cwd=self.local,
                env=self.environment,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.record["commands"].append(
            {
                "label": label,
                "arguments": arguments,
                "exit_code": result.returncode,
                "elapsed_s": time.perf_counter() - start,
                "log": log.name,
            }
        )
        self.save()
        print(f"{label}: exit {result.returncode}; log {log.name}", flush=True)
        if result.returncode:
            raise RuntimeError(f"{label} failed; retain {log} and inspect before retry")

    def run(self, dependencies_only: bool, adapter_only: bool) -> None:
        """Build dependencies first, then the separately maintained AUV adapter."""
        llvm, cmake_dir, ninja = (
            self.package(name) for name in ("llvm", "cmake", "ninja")
        )
        cmake = str(cmake_dir / "bin/cmake.exe")
        self.environment["PATH"] = os.pathsep.join(
            (str(llvm / "bin"), str(ninja), self.environment["PATH"])
        )
        temporary = self.local / "tmp"
        temporary.mkdir(exist_ok=True)
        self.environment.update(TEMP=str(temporary), TMP=str(temporary))
        prefix = self.local / "prefix"
        native_flags = "-no-canonical-prefixes -D_WIN32_WINNT=0x0A00 -DWINVER=0x0A00"
        c_compiler = (llvm / "bin/x86_64-w64-mingw32-clang.exe").as_posix()
        cxx_compiler = (llvm / "bin/x86_64-w64-mingw32-clang++.exe").as_posix()
        options = [
            "-G",
            "Ninja",
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_POLICY_DEFAULT_CMP0176=NEW",
            f"-DCMAKE_C_FLAGS={native_flags}",
            f"-DCMAKE_CXX_FLAGS={native_flags}",
            f"-DCMAKE_C_COMPILER={c_compiler}",
            f"-DCMAKE_CXX_COMPILER={cxx_compiler}",
            f"-DCMAKE_INSTALL_PREFIX={prefix.as_posix()}",
            f"-DCMAKE_PREFIX_PATH={prefix.as_posix()}",
        ]
        if not adapter_only:
            for name, flags in (
                (
                    "boost",
                    [
                        "-DBOOST_INCLUDE_LIBRARIES=serialization;program_options;math;graph;random;algorithm;range;foreach;dynamic_bitset;numeric/odeint",
                        "-DBUILD_SHARED_LIBS=OFF",
                    ],
                ),
                ("eigen", ["-DBUILD_TESTING=OFF", "-DEIGEN_BUILD_DOC=OFF"]),
                (
                    "ompl",
                    [
                        "-DOMPL_BUILD_VAMP=OFF",
                        "-DOMPL_BUILD_PYTHON_BINDINGS=OFF",
                        "-DOMPL_BUILD_SHARED=OFF",
                        "-DOMPL_BUILD_TESTS=OFF",
                        "-DOMPL_BUILD_DEMOS=OFF",
                    ],
                ),
            ):
                installed = self.record.setdefault("installed_configuration", {})
                signature = {"flags": flags, "options": options}
                if installed.get(name) == signature:
                    print(f"Reusing completed {name} build", flush=True)
                    continue
                source = self.package(name)
                # Keep the first failed generated configuration intact.
                build = self.local / "build" / (name + "-portable")
                self.command(
                    name + "-configure",
                    [cmake, "-S", str(source), "-B", str(build), *options, *flags],
                )
                self.command(
                    name + "-install",
                    [
                        cmake,
                        "--build",
                        str(build),
                        "--target",
                        "install",
                        "--parallel",
                        str(self.jobs),
                    ],
                )
                installed[name] = signature
                self.save()
        if dependencies_only:
            return
        include = self.local / "include/nlohmann"
        include.mkdir(parents=True, exist_ok=True)
        for filename, remote in (
            ("json.hpp", "single_include/nlohmann/json.hpp"),
            ("LICENSE.MIT", "LICENSE.MIT"),
        ):
            path = include / filename
            if not path.exists():
                request = urllib.request.Request(
                    "https://raw.githubusercontent.com/nlohmann/json/v3.12.0/" + remote,
                    headers={"User-Agent": "AUV-stage6b"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    path.write_bytes(response.read())
        build = self.local / "build/adapter"
        self.command(
            "adapter-configure",
            [
                cmake,
                "-S",
                str(self.repository / "native/stage6b"),
                "-B",
                str(build),
                *options,
                f"-DSTAGE6B_JSON_INCLUDE={include.parent.as_posix()}",
            ],
        )
        self.command(
            "adapter-build",
            [cmake, "--build", str(build), "--parallel", str(self.jobs)],
        )
        self.command(
            "adapter-ctest",
            [
                str(cmake_dir / "bin/ctest.exe"),
                "--test-dir",
                str(build),
                "--output-on-failure",
            ],
        )


def main() -> None:
    """Use an explicit local directory, without altering system installations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--dependencies-only", action="store_true")
    parser.add_argument("--adapter-only", action="store_true")
    args = parser.parse_args()
    if args.dependencies_only and args.adapter_only:
        raise ValueError("Choose only one build stage restriction")
    Builder(args.local_root, args.jobs, args.repository_root).run(
        args.dependencies_only, args.adapter_only
    )


if __name__ == "__main__":
    main()
