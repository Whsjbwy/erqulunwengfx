"""Execute untouched local author files with isolated, auditable display adapters.

The JSON protocol uses a duplicated stdout descriptor. Author Python output and
native-library output go to local log files, never to that protocol channel.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib
import importlib.util
import json
import os
import random
import runpy
import sys
import time
import traceback
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, TextIO

DISPLAY_FUNCTIONS = (
    "showpoint",
    "showline",
    "showline1",
    "showdashedline",
    "showvoxel",
)
PARAMETER_NAMES = (
    "map_bounds",
    "grid_length",
    "max_num",
    "max_iter",
    "start",
    "goal",
    "step",
    "angle_step",
    "theta1_limit",
    "phi_step",
    "alpha",
    "epsilon",
    "process_times",
)


class DisplayCamera:
    """Keep the author's camera assignment without allocating a render window."""

    position: tuple[float, float, float] | None = None


class DisplayPlotter:
    """Replace only the rendering methods exercised by the supplied demo."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.camera = DisplayCamera()

    def render(self, *args: Any, **kwargs: Any) -> None:
        """Skip a display-only render request."""

    def show(self, *args: Any, **kwargs: Any) -> None:
        """Skip a display-only window request."""


def ignore_display(*args: Any, **kwargs: Any) -> None:
    """Skip an audited author visualization function, without touching geometry."""


@contextlib.contextmanager
def local_output(log_path: Path) -> Iterator[None]:
    """Capture Python and native stdout/stderr to one UTF-8 local log."""
    sys.stdout.flush()
    sys.stderr.flush()
    saved_stdout = os.dup(1)
    saved_stderr = os.dup(2)
    with log_path.open("w", encoding="utf-8", buffering=1) as stream:
        try:
            os.dup2(stream.fileno(), 1)
            os.dup2(stream.fileno(), 2)
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                yield
        finally:
            stream.flush()
            os.dup2(saved_stdout, 1)
            os.dup2(saved_stderr, 2)
            os.close(saved_stdout)
            os.close(saved_stderr)


def load_adapter(path: Path | None) -> ModuleType | None:
    """Load a researcher-selected local diagnostic hook, if explicitly supplied."""
    if path is None:
        return None
    spec = importlib.util.spec_from_file_location("_gsunlight_local_adapter", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load diagnostic adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "adapt", None)):
        raise TypeError(
            "A diagnostic adapter must expose adapt(utils, grid, parameters)."
        )
    return module


def capacity_random_lines(source_path: Path) -> set[int]:
    """Find the sole randint inside the known author's capacity-overflow block.

    Unsupported source structures return an empty set; their eviction count is
    unavailable rather than an invented zero. Reading the AST never edits code.
    """
    tree = ast.parse(source_path.read_bytes())
    lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if not (
            len(test.ops) == len(test.comparators) == 1
            and isinstance(test.ops[0], ast.Gt)
            and isinstance(test.comparators[0], ast.Name)
            and test.comparators[0].id == "max_num"
            and isinstance(test.left, ast.Call)
            and isinstance(test.left.func, ast.Name)
            and test.left.func.id == "len"
            and any(
                isinstance(item, ast.Name) and item.id == "grids_ids"
                for item in ast.walk(test.left)
            )
        ):
            continue
        for statement in node.body:
            for call in ast.walk(statement):
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "random"
                    and call.func.attr == "randint"
                ):
                    lines.add(call.lineno)
    return lines if len(lines) == 1 else set()


@contextlib.contextmanager
def observe_author_calls(
    utils: ModuleType,
    source_path: Path,
    counters: dict[str, Any],
    raw_candidates_observable: bool,
) -> Iterator[None]:
    """Count outputs and known capacity draws without additional RNG calls."""
    original_tangent = getattr(utils, "findtangent", None)
    original_randint = random.randint
    eviction_lines = capacity_random_lines(source_path)
    counters.update(
        candidate_batches=None,
        empty_candidate_batches=None,
        emitted_candidates=None,
        raw_candidates=None,
        collision_filter_valid_candidates=None,
        grid_evictions=0 if eviction_lines else None,
    )
    if callable(original_tangent):
        counters.update(
            candidate_batches=0, empty_candidate_batches=0, emitted_candidates=0
        )
        if raw_candidates_observable:
            counters["raw_candidates"] = 0

        def observed_tangent(*args: Any, **kwargs: Any) -> Any:
            counters["candidate_batches"] += 1
            candidates = original_tangent(*args, **kwargs)
            count = len(candidates)
            counters["emitted_candidates"] += count
            counters["empty_candidate_batches"] += int(count == 0)
            if raw_candidates_observable:
                counters["raw_candidates"] += count
            return candidates

        utils.findtangent = observed_tangent

    def observed_randint(first: int, last: int) -> int:
        value = original_randint(first, last)
        caller = sys._getframe(1)
        if (
            eviction_lines
            and caller.f_code.co_filename == str(source_path)
            and caller.f_lineno in eviction_lines
        ):
            counters["grid_evictions"] += 1
        return value

    if eviction_lines:
        random.randint = observed_randint
    try:
        yield
    finally:
        if callable(original_tangent):
            utils.findtangent = original_tangent
        random.randint = original_randint


def final_counters(
    namespace: dict[str, Any] | None, observed: dict[str, Any]
) -> dict[str, Any]:
    """Add final frontier sizes; absent source state remains explicitly unknown."""
    result = dict(observed)
    state = namespace or {}
    result["expanded_nodes"] = len(state["Closeset"]) if "Closeset" in state else None
    result["open_nodes"] = len(state["Openset"]) if "Openset" in state else None
    result["observation_note"] = (
        "Emitted counts describe findtangent outputs. Raw and filter-valid counts "
        "are null when not directly observed; evictions require a recognized AST block."
    )
    return result


def author_termination(namespace: dict[str, Any], found: bool) -> str:
    """Identify the author's first-batch success or actual no-path stop condition."""
    if found:
        return "found_first_batch"
    if (
        "iter" in namespace
        and "max_iter" in namespace
        and namespace["iter"] >= namespace["max_iter"]
    ):
        return "iteration_budget"
    if "Openset" in namespace and len(namespace["Openset"]) == 0:
        return "open_exhausted"
    return "unknown_no_path_stop"


def execute_author(
    source_dir: Path,
    map_path: Path,
    map_data: Any,
    seed: int,
    mode: str,
    adapter: ModuleType | None = None,
) -> dict[str, Any]:
    """Run the author's unmodified entry point; restore all process-local patches."""
    import numpy as np
    import pyvista as pv

    if adapter is not None and mode in ("author_headless", "author_original"):
        raise ValueError("Author-original modes cannot enable a safety adapter.")
    previous_dir = Path.cwd()
    previous_argv = sys.argv[:]
    previous_path = sys.path[:]
    previous_utils = sys.modules.pop("utils", None)
    previous_read = pv.read
    previous_plotter = pv.Plotter
    python_random_state = random.getstate()
    numpy_random_state = np.random.get_state()
    parameter_context = {"seed": seed, "mode": mode}
    counters: dict[str, Any] = {}
    context_started = time.perf_counter()

    def cached_read(filename: Any, *args: Any, **kwargs: Any) -> Any:
        requested = Path(filename).resolve()
        if requested not in (map_path, source_dir / "map.vti"):
            raise ValueError(f"Unexpected author map read: {requested}")
        return map_data

    try:
        os.chdir(source_dir)
        sys.path.insert(0, str(source_dir))
        sys.argv = [
            str(source_dir / "main_sunlight_3Dgrid.py"),
            "--noanimate",
            "--noshow",
        ]
        random.seed(seed)
        np.random.seed(seed)
        pv.read = cached_read
        pv.Plotter = DisplayPlotter
        author_utils = importlib.import_module("utils")
        for name in DISPLAY_FUNCTIONS:
            if not callable(getattr(author_utils, name, None)):
                raise AttributeError(f"Expected author visualization function: {name}")
            setattr(author_utils, name, ignore_display)
        adapter_context = (
            contextlib.nullcontext()
            if adapter is None
            else adapter.adapt(
                author_utils, occupancy_from_image(map_data), parameter_context
            )
        )
        started = time.perf_counter()
        with (
            adapter_context,
            observe_author_calls(
                author_utils,
                source_dir / "main_sunlight_3Dgrid.py",
                counters,
                raw_candidates_observable=adapter is None,
            ),
        ):
            namespace = runpy.run_path(
                str(source_dir / "main_sunlight_3Dgrid.py"), run_name="__main__"
            )
        elapsed = time.perf_counter() - started
        found = bool(namespace.get("paths_lengths", []))
        parameters = {
            name: namespace[name] for name in PARAMETER_NAMES if name in namespace
        }
        parameters["headless_replacements"] = ["pyvista.Plotter", *DISPLAY_FUNCTIONS]
        return {
            "status": "ok" if found else "no_path",
            "reported_success": found,
            "raw_path": np.asarray(namespace["path"]).tolist() if found else None,
            "postprocessed_path": (
                np.asarray(namespace["path1"]).tolist() if found else None
            ),
            "parameters": parameters,
            "node_count": len(namespace.get("Allset", [])),
            "counted_iterations": namespace.get("iter"),
            "counters": final_counters(namespace, counters),
            "termination_reason": author_termination(namespace, found),
            "author_raw_length": min(namespace["paths_lengths"]) if found else None,
            "author_postprocessed_length": namespace.get("L1") if found else None,
            "algorithm_seconds": namespace["time_end"] - namespace["time_start"],
            "worker_seconds": elapsed,
            "timing_scopes": {
                "algorithm_seconds": "author timer; excludes native postprocessing",
                "worker_seconds": (
                    "runpy execution including native postprocessing and observation; "
                    "not a common search-only benchmark timer"
                ),
            },
            "adapter_metadata": parameter_context,
            "exit_code": 0,
            "failure_reason": "" if found else "author_returned_no_path",
        }
    except Exception as error:
        traceback.print_exc()
        return recover_failed_execution(
            error,
            source_dir / "main_sunlight_3Dgrid.py",
            time.perf_counter() - context_started,
            parameter_context,
            counters,
        )
    finally:
        pv.read = previous_read
        pv.Plotter = previous_plotter
        random.setstate(python_random_state)
        np.random.set_state(numpy_random_state)
        sys.modules.pop("utils", None)
        if previous_utils is not None:
            sys.modules["utils"] = previous_utils
        sys.path[:] = previous_path
        sys.argv[:] = previous_argv
        os.chdir(previous_dir)


def recover_failed_execution(
    error: Exception,
    source_path: Path,
    elapsed: float,
    adapter_metadata: dict[str, Any],
    observed_counters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recover completed search evidence from the author's exception traceback.

    A postprocessor's intermediate ``path1`` is deliberately omitted after any
    exception. Candidate ``paths`` contain only paths whose construction finished;
    they can preserve search success even if later selection or smoothing failed.
    """
    import numpy as np

    namespace: dict[str, Any] | None = None
    trace = error.__traceback__
    while trace is not None:
        if Path(trace.tb_frame.f_code.co_filename).resolve() == source_path:
            namespace = dict(trace.tb_frame.f_globals)
        trace = trace.tb_next
    parameters = None
    raw_path = None
    raw_state = "not_captured"
    reported_success = False
    author_raw_length = None
    algorithm_seconds = None
    node_count = None
    counted_iterations = None
    if namespace is not None:
        parameters = {
            name: namespace[name] for name in PARAMETER_NAMES if name in namespace
        }
        parameters["headless_replacements"] = ["pyvista.Plotter", *DISPLAY_FUNCTIONS]
        completed_paths = namespace.get("paths", [])
        lengths = namespace.get("paths_lengths", [])
        completed_count = min(len(completed_paths), len(lengths))
        if completed_count:
            reported_success = True
            selected = min(range(completed_count), key=lambda index: lengths[index])
            author_raw_length = lengths[selected]
            selected_before_error = namespace.get(
                "min_index"
            ) == selected and isinstance(namespace.get("path"), np.ndarray)
            if selected_before_error:
                raw_path = np.asarray(namespace["path"]).tolist()
                raw_state = "selected_before_error"
            else:
                raw_path = np.asarray(
                    completed_paths[selected], dtype=np.float32
                ).tolist()
                raw_state = "selected_from_completed_candidates_after_error"
        if "time_start" in namespace and "time_end" in namespace:
            algorithm_seconds = namespace["time_end"] - namespace["time_start"]
        node_count = len(namespace["Allset"]) if "Allset" in namespace else None
        counted_iterations = namespace.get("iter")
    return {
        "status": "crash",
        "reported_success": reported_success,
        "raw_path": raw_path,
        "raw_path_state": raw_state,
        "postprocessed_path": None,
        "parameters": parameters,
        "parameters_state": (
            "captured_from_author_exception_frame"
            if namespace is not None
            else "not_captured_before_exception"
        ),
        "partial": True,
        "node_count": node_count,
        "counted_iterations": counted_iterations,
        "counters": final_counters(namespace, observed_counters or {}),
        "termination_reason": "error",
        "author_raw_length": author_raw_length,
        "author_postprocessed_length": None,
        "algorithm_seconds": algorithm_seconds,
        "worker_seconds": elapsed,
        "adapter_metadata": adapter_metadata,
        "exit_code": 1,
        "failure_reason": f"{type(error).__name__}: {error}",
    }


def occupancy_from_image(image: Any) -> Any:
    """Build diagnostic occupancy from the already-loaded image, without rereading."""
    import numpy as np

    from .map_reader import OccupancyMap

    shape = tuple(int(value) - 1 for value in image.dimensions)
    occupancy = np.asarray(image.cell_data["obstacle"], dtype=bool).reshape(
        shape, order="F"
    )
    return OccupancyMap(occupancy, tuple(image.bounds[::2]), tuple(image.spacing))


def json_default(value: Any) -> Any:
    """Convert NumPy scalar metadata without accepting unknown object types."""
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def send_result(stream: TextIO, payload: dict[str, Any]) -> None:
    """Flush one private protocol record, preserving Unicode diagnostic messages."""
    stream.write(json.dumps(payload, ensure_ascii=False, default=json_default) + "\n")
    stream.flush()


def main(argv: list[str] | None = None) -> int:
    """Serve sequential seed requests until the parent closes standard input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--map-path", type=Path, required=True)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--mode", default="author_headless")
    parser.add_argument("--adapter-path", type=Path)
    args = parser.parse_args(argv)
    source_dir = args.source_dir.resolve()
    map_path = args.map_path.resolve()
    local_dir = args.local_dir.resolve()
    local_dir.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1) as protocol:
        try:
            with local_output(local_dir / "worker_startup.log"):
                import pyvista as pv

                map_data = pv.read(map_path)
                adapter = load_adapter(args.adapter_path)
            send_result(protocol, {"event": "ready", "map_load_count": 1})
        except Exception as error:
            with (local_dir / "worker_startup.log").open(
                "a", encoding="utf-8"
            ) as error_log:
                traceback.print_exc(file=error_log)
            send_result(protocol, {"event": "startup_error", "error": str(error)})
            return 1
        for request in sys.stdin:
            seed = int(json.loads(request)["seed"])
            started = time.perf_counter()
            with local_output(local_dir / f"seed_{seed}.log"):
                try:
                    result = execute_author(
                        source_dir, map_path, map_data, seed, args.mode, adapter
                    )
                except Exception as error:
                    traceback.print_exc()
                    result = {
                        "status": "crash",
                        "reported_success": False,
                        "failure_reason": f"{type(error).__name__}: {error}",
                        "exit_code": 1,
                    }
            result.update(
                event="result", seed=seed, wall_seconds=time.perf_counter() - started
            )
            send_result(protocol, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
