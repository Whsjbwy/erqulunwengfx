"""Verify deadline, certification, common shortcut and exact cache semantics."""

import json
from pathlib import Path

import numpy as np
import pytest

from gsunlight_repro import paper_planner, sampling
from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.planning import BudgetExceeded, Deadline, SearchCounters
from gsunlight_repro.postprocessing import shortcut_path
from gsunlight_repro.scenarios import Scenario
from gsunlight_repro.stage4a.anytime import attempt_seed, plan
from gsunlight_repro.stage4a.budget import Budget
from gsunlight_repro.stage4a.incumbent import Incumbent
from gsunlight_repro.stage4a.measurement import Measurement
from gsunlight_repro.stage4a.path_metrics import clearance_lower_bound, turn_count


@pytest.fixture
def empty_scene() -> Scenario:
    grid = OccupancyMap(np.zeros((5, 5, 5), dtype=bool))
    grid.occupancy.setflags(write=False)
    return Scenario(
        "unit",
        grid,
        (0.5, 0.5, 0.5),
        (4.5, 4.5, 4.5),
        0,
        "synthetic test",
        None,
        "test",
    )


def test_first_event_includes_validation_and_no_early_checkpoint(empty_scene) -> None:
    now = [0.0]
    budget = Budget(1, lambda: now[0])

    def checker(path, grid):
        now[0] += 0.2
        return validate_path(path, grid)

    incumbent = Incumbent(
        empty_scene.grid, empty_scene.start, empty_scene.goal, budget, checker
    )
    incumbent.accept([empty_scene.start, empty_scene.goal], process=False)
    rows = incumbent.checkpoints([0.1, 0.2, 1])
    assert rows[0]["valid"] is False and rows[0]["best_length"] is None
    assert rows[1]["valid"] and incumbent.raw_history[0]["time_s"] == 0.2


def test_late_certification_cannot_be_backfilled(empty_scene) -> None:
    now = [0.0]
    budget = Budget(1, lambda: now[0])

    def checker(path, grid):
        now[0] = 1.01
        return validate_path(path, grid)

    incumbent = Incumbent(
        empty_scene.grid, empty_scene.start, empty_scene.goal, budget, checker
    )
    with pytest.raises(BudgetExceeded):
        incumbent.accept([empty_scene.start, empty_scene.goal])
    assert not incumbent.history
    assert incumbent.checkpoints([1])[0]["best_length"] is None


def test_interrupted_shortcut_keeps_only_previously_verified_raw(empty_scene) -> None:
    now = [0.0]

    def checker(path, grid):
        now[0] += 0.4
        return validate_path(path, grid)

    incumbent = Incumbent(
        empty_scene.grid,
        empty_scene.start,
        empty_scene.goal,
        Budget(1, lambda: now[0]),
        checker,
    )
    with pytest.raises(BudgetExceeded):
        incumbent.accept([empty_scene.start, empty_scene.goal])
    assert incumbent.post_interrupted == 1
    assert len(incumbent.history) == 1 and incumbent.history[0]["kind"] == "raw"
    assert incumbent.history[0]["time_s"] == 0.4


def test_common_shortcut_matches_frozen_greedy_order(empty_scene) -> None:
    path = [empty_scene.start, (1.5, 3.5, 2.5), empty_scene.goal]
    incumbent = Incumbent(
        empty_scene.grid, empty_scene.start, empty_scene.goal, Budget(10), validate_path
    )
    incumbent.accept(path)
    assert incumbent.best_path == shortcut_path(path, empty_scene.grid)
    assert len(path) == 3
    assert len(incumbent.paths) == 2
    incumbent.accept(path)
    assert len(incumbent.paths) == 2


def test_invalid_complete_path_is_an_explicit_error(empty_scene) -> None:
    incumbent = Incumbent(
        empty_scene.grid, empty_scene.start, empty_scene.goal, Budget(10), validate_path
    )
    with pytest.raises(RuntimeError, match="independent"):
        incumbent.accept([empty_scene.start, (6, 6, 6), empty_scene.goal])
    assert not incumbent.history


@pytest.mark.parametrize("spacing", [(1, 1, 1), (0.5, 2, 3)])
def test_exact_ray_cache_preserves_random_obstacle_geometry_and_counts(spacing) -> None:
    rng = np.random.default_rng(4401)
    occupancy = rng.random((8, 7, 6)) < 0.08
    occupancy[0, 0, 0] = False
    grid = OccupancyMap(occupancy, (-2, 1, 3), spacing)
    grid.occupancy.setflags(write=False)
    point = tuple(np.asarray(grid.origin) + np.asarray(spacing) * 0.5)
    directions = [
        (1, 0, 0),
        (1, 1, 1),
        (0, 1, 0),
        *map(tuple, rng.uniform(0.1, 1, (12, 3))),
    ]
    baseline = [
        sampling.ray_free_length(point, d, grid, 0.5, Deadline(10), SearchCounters())
        for d in directions
    ]
    measurement = Measurement(grid, cache_size=20)
    counters = SearchCounters()
    original = sampling.ray_free_length
    with measurement.installed():
        first = [
            sampling.ray_free_length(point, d, grid, 0.5, Deadline(10), counters)
            for d in directions
        ]
        calls = measurement.oracle_calls
        second = [
            sampling.ray_free_length(point, d, grid, 0.5, Deadline(10), counters)
            for d in directions
        ]
    assert first == second == baseline
    assert measurement.oracle_calls == calls
    assert measurement.cache_hits == len(directions)
    assert counters.sampled_nodes == 2 * len(directions)
    assert sampling.ray_free_length is original


def test_cache_rejects_mutable_or_different_maps(empty_scene) -> None:
    with pytest.raises(ValueError, match="read-only"):
        Measurement(OccupancyMap(np.zeros((2, 2, 2), dtype=bool)), 2)
    measurement = Measurement(empty_scene.grid, 1)
    with pytest.raises(ValueError, match="map instances"):
        measurement.ray(
            (0.5, 0.5, 0.5),
            (1, 0, 0),
            OccupancyMap(np.zeros((2, 2, 2), dtype=bool)),
            1,
            Deadline(10),
            SearchCounters(),
        )


def test_cache_size_is_bounded_and_patches_restore_on_exception(empty_scene) -> None:
    original = sampling.ray_free_length
    measurement = Measurement(empty_scene.grid, 1)
    with pytest.raises(RuntimeError, match="injected"), measurement.installed():
        for direction in ((1, 0, 0), (0, 1, 0)):
            sampling.ray_free_length(
                empty_scene.start,
                direction,
                empty_scene.grid,
                1,
                Deadline(10),
                SearchCounters(),
            )
        raise RuntimeError("injected")
    assert len(measurement.cache) == 1
    assert sampling.ray_free_length is original


@pytest.mark.parametrize("method", ["A1", "A2", "A3", "A4", "rrt_first", "rrt_restart"])
def test_anytime_accepts_only_valid_paths_and_restores_backends(
    empty_scene, method
) -> None:
    protocol = json.loads(Path("configs/stage4a_protocol.json").read_text())
    original = paper_planner._reconstruct
    result = plan(empty_scene, method, 0, protocol, seconds=0.05)
    assert result["strict_valid"]
    assert result["first_valid_time_s"] <= 0.05
    assert all(validate_path(path, empty_scene.grid).valid for path in result["paths"])
    assert (
        result["shortcut_s"] + result["external_validation_s"]
        <= result["actual_total_s"]
    )
    assert paper_planner._reconstruct is original
    if method == "rrt_first":
        assert result["attempts"] == 1


def test_restart_streams_are_deterministic_and_not_selected_by_results() -> None:
    assert attempt_seed(3, 0) == 3
    streams = [attempt_seed(3, i) for i in range(20)]
    assert len(set(streams)) == 20
    assert streams == [attempt_seed(3, i) for i in range(20)]


def test_angle_controls_have_expected_theoretical_work() -> None:
    protocol = json.loads(Path("configs/stage4a_protocol.json").read_text())
    for angle in protocol["angles"].values():
        theta = list(
            sampling.angle_values(
                angle["half_cone_degrees"], angle["theta_step_degrees"], inclusive=True
            )
        )
        assert 36 * len(theta) == angle["theory_rays"]
        assert theta[-1] == angle["half_cone_degrees"]


def test_turns_skip_repeated_points_and_margin_is_only_a_lower_bound() -> None:
    cells = np.zeros((6, 6, 6), dtype=bool)
    cells[2, 2, 2] = True
    grid = OccupancyMap(cells)
    path = [(0.5, 2.5, 4), (5.5, 2.5, 4)]
    assert validate_path(path, grid).valid
    assert 0 <= clearance_lower_bound(path, grid) <= 1
    assert turn_count([(0, 0, 0), (1, 0, 0), (1, 0, 0), (1, 1, 0)]) == 1
