"""Exclusive file-based invocation of the Windows-native OMPL executable."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..stage5a.maps import ROOT


@dataclass(frozen=True, slots=True)
class NativeResult:
    """Decoded result and measured bridge costs, never an audit certificate."""

    payload: dict[str, Any]
    timing: dict[str, float | int]


def invoke_native(
    executable: Path,
    request: dict[str, Any],
    local_directory: Path,
    *,
    timeout_s: float = 20,
    environment: dict[str, str] | None = None,
) -> NativeResult:
    """Keep requests, results and failed process evidence in an exclusive directory."""
    started = time.perf_counter()
    executable = executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    folder = local_directory.resolve()
    if folder.is_relative_to(ROOT):
        raise ValueError("Native invocation records must remain outside the repository")
    folder.mkdir(parents=True, exist_ok=False)
    input_path, output_path = folder / "input.json", folder / "output.json"
    input_path.write_text(
        json.dumps(request, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    serialized = time.perf_counter()
    env = os.environ.copy()
    env.update(
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
    )
    if environment:
        env.update(environment)
    try:
        completed = subprocess.run(
            [str(executable), str(input_path), str(output_path)],
            capture_output=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        (folder / "stdout.log").write_bytes(error.stdout or b"")
        (folder / "stderr.log").write_bytes(error.stderr or b"")
        (folder / "process_failure.json").write_text(
            json.dumps({"reason": "native_process_timeout", "timeout_s": timeout_s}),
            encoding="utf-8",
        )
        raise RuntimeError(
            f"Native process timed out; evidence retained in {folder}"
        ) from error
    ended = time.perf_counter()
    (folder / "stdout.log").write_bytes(completed.stdout)
    (folder / "stderr.log").write_bytes(completed.stderr)
    timing: dict[str, float | int] = {
        "request_serialization_s": serialized - started,
        "native_process_wall_s": ended - serialized,
        "return_code": completed.returncode,
    }
    if completed.returncode != 0:
        (folder / "process_failure.json").write_text(
            json.dumps(timing), encoding="utf-8"
        )
        raise RuntimeError(
            f"Native process returned {completed.returncode}; "
            f"evidence retained in {folder}"
        )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Native output must be a JSON object")
    finished = time.perf_counter()
    timing.update(
        response_read_s=finished - ended,
        bridge_total_wall_s=finished - started,
    )
    return NativeResult(payload, timing)
