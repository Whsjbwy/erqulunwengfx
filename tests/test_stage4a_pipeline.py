"""Verify frozen specifications, matrix membership and measurement controls."""

import json
from pathlib import Path

import numpy as np
import pytest

from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.scenarios import Scenario
from gsunlight_repro.stage4a.anytime import plan
from gsunlight_repro.stage4a.budget import Budget
from gsunlight_repro.stage4a.engineering import fixed_work
from gsunlight_repro.stage4a.runner import VERSION, Runner
from gsunlight_repro.stage4a.runtime import cpu_busy_fraction


def test_phases_use_exactly_the_registered_unique_tasks(tmp_path, monkeypatch) -> None:
    runner = Runner(tmp_path / "private", tmp_path / "public")
    tasks = []

    def record(scene, method, seed):
        tasks.append((scene, method, seed))
        return {}

    monkeypatch.setattr(runner, "run", record)
    for phase in ("pilot", "development", "holdout", "negative"):
        runner.phase(phase)
    assert len(tasks) == 426
    assert len(set(tasks)) == 402
    holdout = {
        (scene, method, seed) for scene, method, seed in tasks if scene.startswith("T")
    }
    assert len(holdout) == 8 * 6 * 5
    assert not any(scene in ("H1", "H2") for scene, _, _ in tasks)
    assert tasks[:4] == [("S1", method, 0) for method in ("A1", "A2", "A3", "A4")]


def test_cached_trial_requires_identical_job_and_is_not_overwritten(tmp_path) -> None:
    runner = Runner(tmp_path / "private", tmp_path / "public")
    folder = runner.local / "D1_A1_seed0"
    folder.mkdir()
    job = {
        "job_id": folder.name,
        "scene": "D1",
        "method": "A1",
        "seed": 0,
        "version": VERSION,
    }
    target = folder / "result.json"
    target.write_text(json.dumps({"job": job, "row": {"marker": "retained"}}))
    original = target.read_bytes()
    assert runner.run("D1", "A1", 0) == {"marker": "retained"}
    assert target.read_bytes() == original
    job["version"] = "different"
    target.write_text(json.dumps({"job": job, "row": {}}))
    with pytest.raises(ValueError, match="specification"):
        runner.run("D1", "A1", 0)


def test_incomplete_trial_and_changed_configuration_are_explicit(tmp_path) -> None:
    runner = Runner(tmp_path / "private", tmp_path / "public")
    (runner.local / "D1_A1_seed0").mkdir()
    with pytest.raises(FileExistsError, match="Incomplete"):
        runner.run("D1", "A1", 0)
    config = runner.local / "configuration.json"
    document = json.loads(config.read_text())
    document["protocol"]["total_budget_s"] = 31
    config.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="configuration"):
        Runner(runner.local, runner.output)


def test_fixed_work_observer_and_cache_preserve_backend_state(monkeypatch) -> None:
    from gsunlight_repro.stage4a import engineering

    grid = OccupancyMap(np.zeros((5, 5, 5), dtype=bool))
    grid.occupancy.setflags(write=False)
    scene = Scenario(
        "unit", grid, (0.5, 0.5, 0.5), (4.5, 4.5, 4.5), 0, "unit", None, "test"
    )
    monkeypatch.setattr(engineering, "load_map", lambda _: scene)
    protocol = json.loads(Path("configs/stage4a_protocol.json").read_text())
    cases = [
        fixed_work("unit", mode, protocol, trace=True)
        for mode in ("bare", "light", "cache")
    ]
    for case in cases[1:]:
        for field in (
            "raw_path",
            "status",
            "termination_reason",
            "parameters",
            "counters",
        ):
            assert case["result"][field] == cases[0]["result"][field]
        assert case["expanded_sequence"] == cases[0]["expanded_sequence"]


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf")])
def test_invalid_budget_is_rejected(seconds) -> None:
    with pytest.raises(ValueError):
        Budget(seconds)


def test_no_attempt_budget_has_no_fabricated_solution() -> None:
    grid = OccupancyMap(np.zeros((2, 2, 2), dtype=bool))
    scene = Scenario(
        "unit", grid, (0.5, 0.5, 0.5), (1.5, 1.5, 1.5), 0, "unit", None, "test"
    )
    protocol = json.loads(Path("configs/stage4a_protocol.json").read_text())
    result = plan(scene, "A1", 0, protocol, seconds=1e-12)
    assert result["attempts"] == 0
    assert result["best_length"] is result["first_valid_time_s"] is None
    assert all(not row["valid"] for row in result["checkpoints"])


def test_system_load_is_not_confused_with_worker_cpu() -> None:
    assert (
        cpu_busy_fraction(
            {"cpu_ticks": [100, 200, 300]}, {"cpu_ticks": [150, 400, 500]}
        )
        == 0.875
    )
    assert cpu_busy_fraction({"cpu_ticks": None}, {"cpu_ticks": None}) is None
