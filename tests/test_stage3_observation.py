"""Verify genuine first-solution events and restoration of frozen controllers."""

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from gsunlight_repro import paper_planner, safety_planner
from gsunlight_repro.grid_candidates import CandidateNode
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.planning import PlanningLimits
from gsunlight_repro.scenarios import load_scenarios
from gsunlight_repro.stage3.experiment import Experiment, memory_usage
from gsunlight_repro.stage3.observation import FirstValidFound, Observation


@pytest.mark.parametrize("planner", [paper_planner.plan, safety_planner.plan])
@pytest.mark.parametrize("occupied", [False, True])
def test_fixed_work_outputs_and_counters_unchanged(planner, occupied: bool) -> None:
    cells = np.zeros((8, 8, 8), dtype=bool)
    if occupied:
        cells[3:5, 2:6, 2:6] = True
    grid = OccupancyMap(cells)
    start, goal = (0.5, 0.5, 0.5), (7.5, 7.5, 7.5)
    options = {
        "n_max": 2,
        "distance_step": 1,
        "length_threshold": 1,
        "phi_step_degrees": 90,
        "theta_step_degrees": 15,
    }
    original_globals = (
        paper_planner.Deadline,
        paper_planner.GridCandidates,
        paper_planner._reconstruct,
    )
    expected = planner(grid, start, goal, 2, PlanningLimits(10), options)
    observation = Observation(grid, start, goal, options)
    with observation.installed():
        actual = planner(grid, start, goal, 2, PlanningLimits(10), options)
    for field in ("raw_path", "status", "termination_reason", "parameters"):
        assert getattr(actual, field) == getattr(expected, field)
    assert asdict(actual.counters) == asdict(expected.counters)
    assert (
        paper_planner.Deadline,
        paper_planner.GridCandidates,
        paper_planner._reconstruct,
    ) == original_globals


def test_first_time_is_measured_when_full_valid_path_appears() -> None:
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    obs = Observation(grid, (0.5, 0.5, 0.5), (2.5, 2.5, 2.5), {})
    with obs.installed():
        result = safety_planner.plan(grid, obs.start, obs.goal, 0, PlanningLimits(10))
    metrics = obs.metrics(result, 10)
    assert 0 < metrics["time_to_first_valid_path_s"] < result.search_seconds
    assert metrics["first_valid_path_length"] == pytest.approx(np.sqrt(12))
    assert metrics["first_valid_expanded_nodes"] == 1
    assert metrics["valid_solution_found_by_30s"]


def test_no_path_has_no_fabricated_first_time() -> None:
    cells = np.zeros((3, 3, 3), dtype=bool)
    cells[1, :, :] = True
    obs = Observation(OccupancyMap(cells), (0.5, 0.5, 0.5), (2.5, 2.5, 2.5), {})
    with obs.installed():
        result = safety_planner.plan(
            obs.grid, obs.start, obs.goal, 0, PlanningLimits(10), {"n_max": 0}
        )
    assert obs.metrics(result, 10)["time_to_first_valid_path_s"] is None
    assert not obs.metrics(result, 10)["valid_solution_found_by_budget"]


def test_first_policy_is_distinct_and_restores_controller() -> None:
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    original = paper_planner._reconstruct
    obs = Observation(grid, (0.5, 0.5, 0.5), (2.5, 2.5, 2.5), {}, stop_first=True)
    with pytest.raises(FirstValidFound), obs.installed():
        safety_planner.plan(grid, obs.start, obs.goal, 0, PlanningLimits(10))
    result = obs.first_result("safety_reference", PlanningLimits(10))
    assert result.version == "stage3-stop-first-v1"
    assert result.termination_reason == "first_valid_policy"
    assert paper_planner._reconstruct is original


def test_incumbent_history_preserves_first_and_strict_improvements() -> None:
    grid = OccupancyMap(np.zeros((4, 4, 4), dtype=bool))
    obs = Observation(grid, (0.5, 0.5, 0.5), (2.5, 0.5, 0.5), {})
    nodes = [
        CandidateNode(0, obs.start, 0, None),
        CandidateNode(1, (0.5, 2.5, 0.5), 2, 0),
        CandidateNode(2, (1.5, 0.5, 0.5), 1, 0),
    ]
    with obs.installed():
        paper_planner.Deadline(10)
        paper_planner._reconstruct(nodes, nodes[1], obs.goal)
        paper_planner._reconstruct(nodes, nodes[2], obs.goal)
        paper_planner._reconstruct(nodes, nodes[1], obs.goal)
    assert len(obs.history) == 2
    assert obs.history[0]["length"] > obs.history[1]["length"]
    assert obs.best_length == 2


def test_event_limit_is_explicit_and_random_calls_are_not_added(tmp_path: Path) -> None:
    grid = OccupancyMap(np.zeros((3, 3, 3), dtype=bool))
    obs = Observation(
        grid,
        (0.5, 0.5, 0.5),
        (2.5, 2.5, 2.5),
        {},
        tmp_path / "events.jsonl",
        event_limit=1,
    )
    with obs.installed():
        safety_planner.plan(grid, obs.start, obs.goal, 0, PlanningLimits(10))
    assert obs.event_count == 1 and obs.dropped_events >= 2
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 1


def test_holdout_maps_have_independent_valid_witnesses() -> None:
    maps = load_scenarios(Path("configs/stage3_holdout_maps.json"))
    assert [m.scene_id for m in maps] == ["H1", "H2"]
    assert all(m.grid.shape == (60, 50, 40) for m in maps)
    assert all(m.start != (2, 2, 2) for m in maps)


@pytest.mark.parametrize(
    "phase,parameter,values",
    [
        ("capacity", "grid_capacity", {1, 3, 5, 10}),
        ("size", "grid_side_length", {3, 5, 8}),
    ],
)
def test_sweeps_change_one_factor_only(
    tmp_path: Path, monkeypatch, phase, parameter, values
) -> None:
    exp = Experiment(tmp_path / "private", tmp_path / "tables")
    calls = []

    def fake(*args, **kwargs):
        calls.append(kwargs["parameters"])
        return {"job_id": len(calls)}

    monkeypatch.setattr(exp, "run", fake)
    exp.phase(phase)
    assert {c[parameter] for c in calls} == values
    other = "grid_side_length" if parameter == "grid_capacity" else "grid_capacity"
    assert {c[other] for c in calls} == ({5} if other == "grid_side_length" else {1})


def test_windows_memory_counter_is_not_a_persistent_worker_peak() -> None:
    result = memory_usage()
    if result["rss_bytes"] is not None:
        assert result["process_peak_rss_bytes"] >= result["rss_bytes"] > 0


def test_existing_incomplete_trial_is_not_silently_overwritten(tmp_path: Path) -> None:
    exp = Experiment(tmp_path / "private", tmp_path / "tables")
    exp.run(
        "test", "S0", parameters={"grid_capacity": 1, "grid_side_length": 5}, seconds=5
    )
    result = next(exp.root.glob("*/result.json"))
    first = json.loads(result.read_text())
    repeated = exp.run(
        "another_phase",
        "S0",
        parameters={"grid_capacity": 1, "grid_side_length": 5},
        seconds=5,
    )
    assert repeated == first["row"]
