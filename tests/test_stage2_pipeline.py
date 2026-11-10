"""Verify final safety verdicts, shared smoothing and isolated evidence handling."""

import csv
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gsunlight_repro.benchmark import assess_path, make_row
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.planning import Deadline, PlanningLimits, SearchCounters
from gsunlight_repro.postprocessing import shortcut_path


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_nonfinite_or_nonpositive_deadlines_rejected(seconds: float) -> None:
    with pytest.raises(ValueError):
        PlanningLimits(time_limit=seconds)
    with pytest.raises(ValueError):
        Deadline(seconds)


def test_absent_path_has_unknown_validity_not_false_collision() -> None:
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    verdict = assess_path(None, grid, (0.5, 0.5, 0.5), (2.5, 2.5, 2.5))
    assert verdict["valid"] is None
    assert verdict["length"] is None
    assert verdict["collision_segment_count"] is None


def test_reported_success_kept_when_path_hits_an_obstacle() -> None:
    cells = np.zeros((3, 3, 3), dtype=bool)
    cells[1, 1, 1] = True
    scenario = SimpleNamespace(
        scene_id="synthetic",
        map_seed=0,
        grid=OccupancyMap(cells),
        start=(0.5, 0.5, 0.5),
        goal=(2.5, 2.5, 2.5),
    )
    result = {
        "method": "synthetic",
        "seed": 0,
        "status": "ok",
        "reported_success": True,
        "termination_reason": "found",
        "raw_path": [scenario.start, scenario.goal],
        "search_seconds": 0.01,
        "counters": asdict(SearchCounters()),
    }
    row, evidence = make_row(result, scenario, "test", PlanningLimits(), 32, 0)
    assert row["reported_success"] is True
    assert row["strict_valid"] is False
    assert row["budget_valid_success"] is False
    assert row["common_post_valid"] is None
    assert "raw_path_invalid" in row["failure_categories"]
    assert evidence["common_postprocessed_path"] is None


def test_common_shortcut_retains_input_and_exact_endpoints() -> None:
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    path = np.array([[0.2, 0.3, 0.4], [1.5, 0.5, 0.5], [2.7, 2.6, 2.5]])
    original = path.copy()
    result = shortcut_path(path, grid)
    np.testing.assert_array_equal(path, original)
    assert result == [tuple(path[0]), tuple(path[-1])]


def test_common_shortcut_rejects_invalid_input() -> None:
    grid = OccupancyMap(np.ones((3, 3, 3), dtype=bool))
    with pytest.raises(ValueError, match="valid input"):
        shortcut_path([[0.5, 0.5, 0.5], [2.5, 2.5, 2.5]], grid)


def test_common_shortcut_rechecks_entire_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gsunlight_repro import postprocessing

    answers = iter([True, True, False])
    monkeypatch.setattr(
        postprocessing,
        "validate_path",
        lambda *args: SimpleNamespace(valid=next(answers)),
    )
    with pytest.raises(RuntimeError, match="final strict"):
        shortcut_path(
            [[0.5, 0.5, 0.5], [2.5, 2.5, 2.5]],
            OccupancyMap(np.zeros((3, 3, 3), dtype=bool)),
        )


def test_invalid_native_smoothing_does_not_corrupt_valid_raw() -> None:
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    scenario = SimpleNamespace(
        scene_id="synthetic",
        map_seed=0,
        grid=grid,
        start=(0.5, 0.5, 0.5),
        goal=(2.5, 2.5, 2.5),
    )
    result = {
        "method": "author_original",
        "seed": 0,
        "status": "ok",
        "reported_success": True,
        "raw_path": [scenario.start, scenario.goal],
        "postprocessed_path": [scenario.start, (99, 99, 99), scenario.goal],
        "search_seconds": 0.1,
        "termination_reason": "found",
    }
    row, _ = make_row(result, scenario, "test", PlanningLimits(), 32, 0)
    assert row["strict_valid"] is True
    assert row["native_post_valid"] is False
    assert row["common_post_valid"] is True


def test_real_endpoint_required_for_any_final_success() -> None:
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    result = assess_path(
        [[0.5, 0.5, 0.5], [1.5, 1.5, 1.5]], grid, (0.5, 0.5, 0.5), (2.5, 2.5, 2.5)
    )
    assert result["valid"] is False
    assert result["endpoints_match"] is False


def empty_scenario() -> SimpleNamespace:
    """Return a tiny synthetic problem, independently of experiment map files."""
    return SimpleNamespace(
        scene_id="synthetic",
        map_seed=0,
        grid=OccupancyMap(np.zeros((3, 3, 3), dtype=bool)),
        start=(0.5, 0.5, 0.5),
        goal=(2.5, 2.5, 2.5),
    )


@pytest.mark.parametrize(
    "points",
    [
        [[0, 0, 0], [1, 1]],
        [[0, 0, 0], ["bad", 1, 1]],
        "not-a-path",
    ],
)
def test_malformed_evidence_is_invalid_without_aborting_later_rows(
    points: object,
) -> None:
    """Malformed planner output must remain evidence, not terminate the whole batch."""
    scenario = empty_scenario()
    result = {
        "method": "synthetic",
        "seed": 0,
        "status": "ok",
        "reported_success": True,
        "search_seconds": 0.01,
        "raw_path": points,
    }
    row, evidence = make_row(result, scenario, "test", PlanningLimits(), 32, 0)
    assert row["strict_valid"] is False
    assert row["endpoints_match"] is False
    assert row["raw_path_length"] is None
    assert evidence["raw_path"] == points
    result["seed"] = 1
    result["raw_path"] = [scenario.start, scenario.goal]
    next_row, _ = make_row(result, scenario, "test", PlanningLimits(), 32, 0)
    assert next_row["strict_valid"] is True


@pytest.mark.parametrize("status", ["timeout", "crash", "error"])
def test_uncaptured_execution_is_unknown_instead_of_reported_failure(
    status: str,
) -> None:
    """A terminated process cannot establish that its algorithm never found a path."""
    result = {
        "method": "synthetic",
        "seed": 0,
        "status": status,
        "reported_success": False,
        "parameters": None,
        "version": "unobserved",
        "search_seconds": 1,
    }
    row, evidence = make_row(result, empty_scenario(), "test", PlanningLimits(), 32, 0)
    assert row["reported_success"] is None
    assert row["search_seconds"] is None
    assert row["version"] is None
    assert row["strict_valid"] is None
    assert row["exit_code"] is None
    assert row["budget_valid_success"] is False
    assert evidence["observation_state"] == "planning_result_not_captured"


def test_crash_preserves_valid_partial_path_without_counting_pipeline_success() -> None:
    """Keep a recovered raw path as evidence while explicitly recording the crash."""
    scenario = empty_scenario()
    result = {
        "method": "author_original",
        "seed": 0,
        "status": "crash",
        "reported_success": True,
        "parameters": {"max_num": 1},
        "raw_path": [scenario.start, scenario.goal],
        "search_seconds": 0.01,
        "failure_reason": "RuntimeError: synthetic native smoothing failed",
        "exit_code": 1,
        "counters": {"no_candidate_expansions": 4, "generated_candidates": 602},
    }
    row, evidence = make_row(result, scenario, "test", PlanningLimits(), 32, 0)
    assert row["reported_success"] is True
    assert row["strict_valid"] is True
    assert row["budget_valid_success"] is False
    assert row["exit_code"] == 1
    assert "synthetic native smoothing failed" in row["error"]
    assert "some_expansions_without_candidates" in row["failure_categories"]
    assert "no_candidates_generated" not in row["failure_categories"]
    assert "not established causal" in evidence["failure_category_note"]


def test_worker_startup_error_keeps_complete_traceback(tmp_path: Path) -> None:
    """A missing synthetic config produces a protocol error and a full local stack."""
    local_dir = tmp_path / "startup_failure"
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "gsunlight_repro.stage2_worker",
            "--map-config",
            str(tmp_path / "missing_maps.json"),
            "--experiment-config",
            str(tmp_path / "missing_experiment.json"),
            "--scene",
            "synthetic",
            "--method",
            "astar",
            "--local-dir",
            str(local_dir),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert process.returncode == 1
    message = json.loads(process.stdout)
    assert message["event"] == "startup_error"
    assert "FileNotFoundError" in message["error"]
    log = (local_dir / "startup.log").read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in log
    assert "missing_maps.json" in log


def test_worker_caught_planner_exception_has_logical_exit_one(tmp_path: Path) -> None:
    """A persistent worker can remain alive while one trial explicitly fails."""
    config = tmp_path / "experiment.json"
    config.write_text(
        json.dumps({"limits": {}, "method_parameters": {"astar": {}}}),
        encoding="utf-8",
    )
    code = (
        "import sys,types\n"
        "from types import SimpleNamespace\n"
        "from gsunlight_repro import stage2_worker\n"
        "scenes=types.ModuleType('gsunlight_repro.scenarios')\n"
        "scenes.load_scenario=lambda *args: SimpleNamespace("
        "grid=None,start=(0,0,0),goal=(1,1,1))\n"
        "sys.modules['gsunlight_repro.scenarios']=scenes\n"
        "planner=types.ModuleType('gsunlight_repro.astar')\n"
        "def fail(*args): raise RuntimeError('synthetic planner failed')\n"
        "planner.plan=fail\n"
        "sys.modules['gsunlight_repro.astar']=planner\n"
        "raise SystemExit(stage2_worker.main())\n"
    )
    local_dir = tmp_path / "planner_failure"
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            "--map-config",
            str(tmp_path / "unused.json"),
            "--experiment-config",
            str(config),
            "--scene",
            "synthetic",
            "--method",
            "astar",
            "--local-dir",
            str(local_dir),
        ],
        input=json.dumps({"seed": 0}) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert process.returncode == 0
    ready, result = [json.loads(line) for line in process.stdout.splitlines()]
    assert ready["event"] == "ready"
    assert result["status"] == "error"
    assert result["termination_reason"] == "error"
    assert result["exit_code"] == 1
    assert result["reported_success"] is None
    assert result["parameters"] is None
    assert "RuntimeError: synthetic planner failed" in result["error"]
    assert "Traceback" in (local_dir / "seed_0.log").read_text(encoding="utf-8")


def test_benchmark_startup_failure_records_actual_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not default a process startup failure to a successful exit code."""
    from gsunlight_repro import benchmark, scenarios

    class FailedWorker:
        def __init__(self, *args: object) -> None:
            self.process = None

        def start(self, timeout: float) -> None:
            self.process = SimpleNamespace(returncode=None)
            raise RuntimeError("original synthetic startup failure")

        def close(self) -> None:
            if self.process is not None:
                self.process.returncode = 1
                self.process = None

    monkeypatch.setattr(benchmark, "WorkerClient", FailedWorker)
    monkeypatch.setattr(benchmark, "environment_info", lambda: {})
    monkeypatch.setattr(scenarios, "load_scenarios", lambda path: [empty_scenario()])
    maps = tmp_path / "maps.json"
    maps.write_text("{}", encoding="utf-8")
    configuration = tmp_path / "experiment.json"
    configuration.write_text(
        json.dumps(
            {"limits": {}, "hard_timeout_seconds": 32, "startup_timeout_seconds": 30}
        ),
        encoding="utf-8",
    )
    output = tmp_path / "summary.csv"
    code = benchmark.main(
        [
            "--map-config",
            str(maps),
            "--experiment-config",
            str(configuration),
            "--methods",
            "astar",
            "--seeds",
            "0",
            "--run-id",
            "synthetic",
            "--local-dir",
            str(tmp_path / "private_records"),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    with output.open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["status"] == "error"
    assert row["exit_code"] == "1"
    assert row["reported_success"] == ""
    assert "original synthetic startup failure" in row["error"]


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("open_set_exhausted", "search_nodes_exhausted"),
        ("paper_iteration_limit", "search_budget_exhausted"),
    ],
)
def test_method_specific_termination_reasons_are_classified(
    reason: str, expected: str
) -> None:
    """Keep A* exhaustion and the paper counter limit distinct in diagnostics."""
    row, _ = make_row(
        {
            "method": "synthetic",
            "seed": 0,
            "status": "no_path",
            "termination_reason": reason,
            "reported_success": False,
        },
        empty_scenario(),
        "classification",
        PlanningLimits(),
        32,
        0,
    )
    assert expected in row["failure_categories"]
