"""Run bounded, serial author experiments and independently validate each path."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .metrics import endpoints_match, environment_info, path_length

LOGGER = logging.getLogger(__name__)
FIELDS = (
    "mode",
    "seed",
    "map",
    "stage",
    "start",
    "goal",
    "parameters",
    "status",
    "exit_code",
    "reported_success",
    "strict_valid",
    "endpoints_match",
    "path_length",
    "collision_segment_count",
    "checked_segments",
    "first_collision_segment",
    "first_collision_voxel",
    "first_collision_point",
    "wall_seconds",
    "algorithm_seconds",
    "worker_seconds",
    "validation_seconds",
    "node_count",
    "counted_iterations",
    "failure_reason",
)


class WorkerClient:
    """Own one serial subprocess; replace it after timeout or unexpected exit."""

    def __init__(self, command: list[str], startup_log: Path) -> None:
        self.command = command
        self.startup_log = startup_log
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.error_stream: Any = None
        self.map_load_count: int | None = None

    def _read_protocol(
        self, stream: Any, messages: queue.Queue[dict[str, Any]]
    ) -> None:
        try:
            for line in stream:
                try:
                    messages.put(json.loads(line))
                except json.JSONDecodeError as error:
                    messages.put({"event": "protocol_error", "error": str(error)})
        finally:
            messages.put({"event": "closed"})

    def start(self, timeout: float) -> None:
        """Load the worker's map once; raise on startup error or startup timeout."""
        self.messages = queue.Queue()
        self.error_stream = self.startup_log.open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.error_stream,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(
            target=self._read_protocol,
            args=(self.process.stdout, self.messages),
            daemon=True,
        ).start()
        try:
            message = self.messages.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("Worker initialization exceeded timeout.") from error
        if message.get("event") != "ready":
            raise RuntimeError(f"Worker initialization failed: {message}")
        self.map_load_count = message.get("map_load_count")

    def run_seed(self, seed: int, timeout: float) -> dict[str, Any]:
        """Return an explicit seed outcome, including crash and timeout failures."""
        started = time.perf_counter()
        try:
            if self.process is None:
                self.start(timeout)
            assert self.process is not None and self.process.stdin is not None
            self.process.stdin.write(json.dumps({"seed": seed}) + "\n")
            self.process.stdin.flush()
            remaining = max(0.001, timeout - (time.perf_counter() - started))
            message = self.messages.get(timeout=remaining)
            if message.get("event") != "result" or message.get("seed") != seed:
                raise RuntimeError(f"Worker protocol failed: {message}")
            message["parent_seconds"] = time.perf_counter() - started
            message["worker_pid"] = self.process.pid
            message["map_load_count"] = self.map_load_count
            return message
        except (queue.Empty, TimeoutError):
            process = self.process
            self.close()
            return {
                "seed": seed,
                "status": "timeout",
                "exit_code": process.returncode if process is not None else None,
                "reported_success": False,
                "parameters": None,
                "parameters_state": "not_captured_before_timeout",
                "wall_seconds": time.perf_counter() - started,
                "failure_reason": (
                    f"seed_timeout_after_{timeout:g}_seconds;parameters_not_captured"
                ),
            }
        except (OSError, RuntimeError) as error:
            process = self.process
            self.close()
            return {
                "seed": seed,
                "status": "crash",
                "exit_code": process.returncode if process is not None else None,
                "reported_success": False,
                "parameters": None,
                "parameters_state": "not_captured_before_worker_exit",
                "wall_seconds": time.perf_counter() - started,
                "failure_reason": f"{type(error).__name__}: {error}",
            }

    def close(self) -> None:
        """Stop and reap the subprocess without leaving background experiments."""
        if self.process is not None:
            if self.process.poll() is None:
                if self.process.stdin is not None:
                    self.process.stdin.close()
                try:
                    self.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
            if self.process.stdout is not None:
                self.process.stdout.close()
            self.process = None
        if self.error_stream is not None:
            self.error_stream.close()
            self.error_stream = None


def result_rows(
    result: dict[str, Any], grid: Any, map_name: str, mode: str
) -> list[dict[str, Any]]:
    """Validate raw and processed paths separately in the original map's units."""
    from .collision_checker import validate_path

    captured_parameters = result.get("parameters")
    parameters = captured_parameters or {}
    rows = []
    for stage, path_key in (
        ("raw", "raw_path"),
        ("postprocessed", "postprocessed_path"),
    ):
        row = {
            "mode": mode,
            "seed": result["seed"],
            "map": map_name,
            "stage": stage,
            "start": json.dumps(parameters.get("start")),
            "goal": json.dumps(parameters.get("goal")),
            "parameters": json.dumps(captured_parameters, sort_keys=True),
            "status": result["status"],
            "exit_code": result.get("exit_code"),
            "reported_success": result.get("reported_success", False),
            "strict_valid": False,
            "endpoints_match": False,
            "path_length": None,
            "collision_segment_count": None,
            "checked_segments": 0,
            "first_collision_segment": None,
            "first_collision_voxel": None,
            "first_collision_point": None,
            "wall_seconds": result.get("wall_seconds"),
            "algorithm_seconds": result.get("algorithm_seconds"),
            "worker_seconds": result.get("worker_seconds"),
            "validation_seconds": None,
            "node_count": result.get("node_count"),
            "counted_iterations": result.get("counted_iterations"),
            "failure_reason": result.get("failure_reason", ""),
        }
        points = result.get(path_key)
        if points is not None:
            started = time.perf_counter()
            validation = asdict(validate_path(points, grid))
            row["validation_seconds"] = time.perf_counter() - started
            row["strict_valid"] = validation.pop("valid")
            reason = validation.pop("reason")
            row.update(validation)
            row["endpoints_match"] = endpoints_match(
                points, parameters.get("start"), parameters.get("goal")
            )
            if reason != "invalid_path":
                row["path_length"] = path_length(points)
            if not row["strict_valid"]:
                row["failure_reason"] = ";".join(
                    part for part in (row["failure_reason"], reason) if part
                )
            if not row["endpoints_match"]:
                row["strict_valid"] = False
                row["failure_reason"] = ";".join(
                    part
                    for part in (row["failure_reason"], "endpoint_mismatch")
                    if part
                )
            for key in ("first_collision_voxel", "first_collision_point"):
                if row[key] is not None:
                    row[key] = json.dumps(row[key])
        rows.append(row)
    return rows


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse explicit local inputs and conservative per-seed resource limits."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--map-path", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(5)))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--mode", default="author_headless")
    parser.add_argument("--adapter-path", type=Path)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive.")
    if len(args.seeds) != len(set(args.seeds)):
        parser.error("--seeds must not contain duplicates.")
    if any(seed < 0 or seed >= 2**32 for seed in args.seeds):
        parser.error("--seeds must be in NumPy's range [0, 2**32).")
    args.source_dir = args.source_dir.resolve()
    args.map_path = args.map_path.resolve()
    args.local_dir = args.local_dir.resolve()
    args.output = args.output.resolve()
    repository = Path(__file__).resolve().parents[2]
    if args.local_dir.is_relative_to(repository):
        parser.error("--local-dir must be outside the public repository.")
    for filename in ("main_sunlight_3Dgrid.py", "utils.py"):
        if not (args.source_dir / filename).is_file():
            parser.error(f"Missing local author file: {filename}")
    if not args.map_path.is_file():
        parser.error("--map-path must be an existing local VTI file.")
    if args.adapter_path is not None:
        args.adapter_path = args.adapter_path.resolve()
        if not args.adapter_path.is_file():
            parser.error("--adapter-path must be an existing local Python file.")
        if args.mode == "author_headless":
            parser.error("An adapter requires a separate diagnostic --mode label.")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested batch; save compact public rows and private path evidence."""
    from .map_reader import read_map

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_arguments(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.local_dir.mkdir(parents=True, exist_ok=True)
    grid = read_map(args.map_path)
    metadata = {
        "environment": environment_info(),
        "mode": args.mode,
        "map": {
            "filename": args.map_path.name,
            "bytes": args.map_path.stat().st_size,
            "shape": list(grid.occupancy.shape),
            "origin": grid.origin,
            "spacing": grid.spacing,
            "bounds": grid.bounds,
            "occupied_cells": int(grid.occupancy.sum()),
        },
        "source_files": {
            name: (args.source_dir / name).stat().st_size
            for name in ("main_sunlight_3Dgrid.py", "utils.py")
        },
        "seeds": args.seeds,
        "timeout_seconds": args.timeout,
        "command": [
            sys.executable,
            "-m",
            "gsunlight_repro.experiment_runner",
            *sys.argv[1:],
        ],
        "timing_note": (
            "author time excludes postprocessing; wall includes rendering adapter "
            "and postprocessing"
        ),
    }
    (args.local_dir / "environment.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    command = [
        sys.executable,
        "-m",
        "gsunlight_repro.author_worker",
        "--source-dir",
        str(args.source_dir),
        "--map-path",
        str(args.map_path),
        "--local-dir",
        str(args.local_dir),
        "--mode",
        args.mode,
    ]
    if args.adapter_path is not None:
        command.extend(("--adapter-path", str(args.adapter_path)))
    worker = WorkerClient(command, args.local_dir / "worker_stderr.log")
    try:
        with (
            args.output.open("w", encoding="utf-8", newline="") as output,
            (args.local_dir / "paths.jsonl").open("a", encoding="utf-8") as paths,
        ):
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            for seed in args.seeds:
                result = worker.run_seed(seed, args.timeout)
                paths.write(
                    json.dumps({"mode": args.mode, **result}, ensure_ascii=False) + "\n"
                )
                paths.flush()
                rows = result_rows(result, grid, args.map_path.name, args.mode)
                writer.writerows(rows)
                output.flush()
                LOGGER.info(
                    "mode=%s seed=%d status=%s raw_valid=%s post_valid=%s",
                    args.mode,
                    seed,
                    result["status"],
                    rows[0]["strict_valid"],
                    rows[1]["strict_valid"],
                )
    finally:
        worker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
