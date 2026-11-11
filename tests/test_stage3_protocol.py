"""Check budget escalation, conditional scans and development-only selection."""

import io
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from gsunlight_repro.stage3.analysis import (
    completion_metrics,
    path_departure_angles,
    summarize_phases,
)
from gsunlight_repro.stage3.experiment import Experiment, terminate_worker


@pytest.mark.parametrize("time_limited", [False, True])
def test_astar_changes_one_budget_and_stops_at_valid_result(
    tmp_path: Path, monkeypatch, time_limited: bool
) -> None:
    experiment = Experiment(tmp_path / "private", tmp_path / "tables")
    calls = []

    def run(phase, scene, method, **options):
        calls.append((scene, options.get("nodes"), options.get("seconds", 30)))
        success = (
            options.get("seconds", 30) == 60 if time_limited else len(calls) % 2 == 0
        )
        return {
            "strict_valid": success,
            "termination_reason": "ok"
            if success
            else "time_budget"
            if time_limited
            else "node_budget",
        }

    monkeypatch.setattr(experiment, "run", run)
    experiment.phase("astar")
    expected = (
        [(100000, 30), (100000, 60)] if time_limited else [(100000, 30), (200000, 30)]
    )
    assert calls == [
        (scene, nodes, seconds) for scene in ("S1", "S2") for nodes, seconds in expected
    ]


@pytest.mark.parametrize("s1_success", [False, True])
def test_sampling_scan_requires_failure_of_every_s1_setting(
    tmp_path: Path, monkeypatch, s1_success: bool
) -> None:
    experiment = Experiment(tmp_path / "private", tmp_path / "tables")
    for phase in ("capacity", "size"):
        experiment.table(
            phase, [{"scene": "S1", "valid_solution_found_by_budget": s1_success}]
        )
    settings = []

    def run(*args, **options):
        settings.append(options["parameters"])
        return {"trial": len(settings)}

    monkeypatch.setattr(experiment, "run", run)
    experiment.phase("sampling")
    assert len(settings) == (0 if s1_success else 18)
    assert all(
        not ({"distance_step", "half_cone_degrees"} <= p.keys()) for p in settings
    )


def test_holdout_uses_frozen_development_choice_for_both_maps(
    tmp_path: Path, monkeypatch
) -> None:
    experiment = Experiment(tmp_path / "private", tmp_path / "tables")
    base = {"grid_capacity": 1, "grid_side_length": 5}
    selected = {**base, "grid_capacity": 3}
    rows = [
        {
            "scene": scene,
            "seed": seed,
            "parameters": options,
            "valid_solution_found_by_budget": options == selected,
        }
        for options in (base, selected)
        for scene in ("S1", "S2", "S3")
        for seed in range(3)
    ]
    experiment.table("capacity", rows)
    experiment.table("size", [row for row in rows if row["parameters"] == base])
    calls = []

    def run(phase, scene, *args, **options):
        calls.append((scene, options.get("parameters")))
        return {"trial": len(calls), "strict_valid": False}

    monkeypatch.setattr(experiment, "run", run)
    experiment.phase("holdout")
    frozen = json.loads((experiment.output / "holdout_selection.json").read_text())
    assert frozen["selected"] == selected
    for scene in ("H1", "H2"):
        assert [p for s, p in calls if s == scene] == [base] * 3 + [selected] * 3 + [
            None
        ] * 3


@pytest.mark.parametrize("status,expected", [("timeout", False), ("ok", True)])
def test_legacy_completion_keeps_timeout_incumbent_distinct(status, expected) -> None:
    row = {
        "status": status,
        "strict_valid": True,
        "reported_success": True,
        "search_seconds": 29,
        "time_budget_s": 30,
        "time_to_first_valid_path_s": 1,
    }
    assert completion_metrics(row) == {
        "budget_valid_success": expected,
        "first_event_observed": True,
    }


def test_unknown_first_time_and_missing_budget_are_not_filled_with_zero() -> None:
    assert completion_metrics({"status": "hard_timeout"}) == {
        "budget_valid_success": None,
        "first_event_observed": False,
    }


def test_summary_keeps_unknown_first_event_denominator(tmp_path: Path) -> None:
    experiment = Experiment(tmp_path / "private", tmp_path / "tables")
    experiment.table(
        "profile",
        [
            {
                "job_id": "control",
                "scene": "S3",
                "method": "safety_reference",
                "measurement": "unobserved",
                "parameters": {},
                "status": "ok",
                "termination_reason": "paper_iteration_limit",
                "strict_valid": True,
                "reported_success": True,
                "search_seconds": 1,
                "time_budget_s": 30,
            }
        ],
    )
    summary = summarize_phases(experiment.output)[0]
    assert summary["valid_by_budget"] is None
    assert summary["valid_by_budget_known_runs"] == 0
    assert summary["budget_valid_success"] == 1


def test_duplicate_reference_views_are_not_independent_samples(tmp_path: Path) -> None:
    experiment = Experiment(tmp_path / "private", tmp_path / "tables")
    row = {
        "job_id": "reference",
        "scene": "S1",
        "method": "safety_reference",
        "status": "no_path",
        "termination_reason": "open_exhausted",
        "valid_solution_found_by_budget": False,
    }
    experiment.table("sampling", [row, row])
    summary = summarize_phases(experiment.output)[0]
    assert summary["runs"] == 1
    assert summary["design_view_rows"] == 2
    assert summary["valid_by_budget_known_runs"] == 1


def test_timeout_guard_targets_only_the_owned_worker_tree(monkeypatch) -> None:
    process = Mock(spec=subprocess.Popen)
    process.pid = 12345
    process.poll.return_value = None
    process.wait.return_value = -1
    command = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(subprocess, "run", command)
    assert terminate_worker(process, io.StringIO()) == -1
    if os.name == "nt":
        assert command.call_args.args[0] == ["taskkill", "/PID", "12345", "/T", "/F"]
    else:
        process.kill.assert_called_once()


def test_timeout_guard_does_not_stop_an_already_finished_worker() -> None:
    process = Mock(spec=subprocess.Popen)
    process.poll.return_value = 0
    assert terminate_worker(process, io.StringIO()) == 0
    process.kill.assert_not_called()
    process.wait.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree API")
def test_failed_tree_termination_is_an_explicit_error(monkeypatch) -> None:
    process = Mock(spec=subprocess.Popen)
    process.pid = 12345
    process.poll.return_value = None
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1)
    )
    with pytest.raises(RuntimeError, match="worker tree"):
        terminate_worker(process, io.StringIO())


def test_departure_angles_distinguish_turning_and_zero_length_edges() -> None:
    angles = path_departure_angles([(0, 0, 0), (0, 1, 0), (0, 1, 0), (1, 0, 0)])
    assert angles == pytest.approx([90, 0])
    assert path_departure_angles([]) == []
    assert path_departure_angles([(0, 0, 0)]) == []
    assert path_departure_angles([(0, 0, 0), (-1, 0, 0), (1, 0, 0)]) == [180, 0]
