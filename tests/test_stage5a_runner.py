"""Trial preservation and prospective staging guards without long experiments."""

import json
from pathlib import Path

import pytest

from gsunlight_repro.stage5a.runner import Runner


def test_configuration_is_immutable_and_partial_trial_is_not_overwritten(
    tmp_path: Path,
) -> None:
    runner = Runner(tmp_path / "local", tmp_path / "public")
    directory = runner.local / "pilot_F5_EMPTY_rrt_star_body_seed0_step5"
    directory.mkdir()
    with pytest.raises(FileExistsError, match="Incomplete"):
        runner.run("F5_EMPTY", "rrt_star", 0, "body", phase="pilot", seconds=3, step=5)
    assert list(directory.iterdir()) == []
    configuration = runner.local / "configuration.json"
    modified = json.loads(configuration.read_text(encoding="utf-8"))
    modified["protocol"]["total_budget_s"] = 999
    configuration.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen"):
        Runner(runner.local, runner.output)


def test_development_cannot_start_before_complete_pilot(tmp_path: Path) -> None:
    runner = Runner(tmp_path / "local", tmp_path / "public")
    with pytest.raises(ValueError, match="functional"):
        runner.phase("development")


def test_exact_completed_job_is_reused_without_new_process(tmp_path: Path) -> None:
    runner = Runner(tmp_path / "local", tmp_path / "public")
    identity = "pilot_F5_EMPTY_rrt_star_body_seed0_step5"
    job = {
        "job_id": identity,
        "scene": "F5_EMPTY",
        "method": "rrt_star",
        "seed": 0,
        "geometry_mode": "body",
        "phase": "pilot",
        "seconds": 3,
        "step_m": 5,
        "version": runner.protocol["version"],
    }
    directory = runner.local / identity
    directory.mkdir()
    (directory / "result.json").write_text(
        json.dumps({"job": job, "row": {"sentinel": "original"}}), encoding="utf-8"
    )
    assert runner.run(
        "F5_EMPTY", "rrt_star", 0, "body", phase="pilot", seconds=3, step=5
    ) == {"sentinel": "original"}
    with pytest.raises(ValueError, match="differs"):
        runner.run("F5_EMPTY", "rrt_star", 0, "body", phase="pilot", seconds=2, step=5)
