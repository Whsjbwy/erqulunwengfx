"""Reference algorithms, independent safety, sampling and tree invariants."""

import math
from collections import Counter

import numpy as np
import pytest

from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.metrics import path_length
from gsunlight_repro.planning import PlanningLimits
from gsunlight_repro.rrt_connect import plan as legacy_connect
from gsunlight_repro.stage4a.budget import Budget
from gsunlight_repro.stage5a.geometry import Geometry
from gsunlight_repro.stage5a.maps import Scene, load_scene, read_config
from gsunlight_repro.stage5a.planners import Options, connect_once, plan
from gsunlight_repro.stage5a.sampling import InformedSampler, neighbor_radius
from gsunlight_repro.stage5a.solutions import Solutions
from gsunlight_repro.stage5a.tree import Tree


def detour() -> Scene:
    """Small strictly reachable map with a nontrivial route around a wall."""
    values = np.zeros((10, 10, 10), dtype=bool)
    values[5, :7, :] = True
    return Scene(
        {"family": "test"}, OccupancyMap(values), None, (2, 2, 4), (8, 2, 4), None
    )


def test_rewire_propagates_cost_to_all_descendants_and_preserves_snapshots() -> None:
    tree = Tree((0, 0, 0), 20)
    a = tree.add((0, 5, 0), 0)
    b = tree.add((5, 5, 0), a)
    c = tree.add((6, 5, 0), b)
    d = tree.add((7, 5, 0), c)
    shorter = tree.add((4, 0, 0), 0)
    before = tree.path(d)
    assert tree.reparent(b, shorter) == 3
    assert tree.path(d) != before
    assert before == [(0, 0, 0), (0, 5, 0), (5, 5, 0), (6, 5, 0), (7, 5, 0)]
    for index in range(len(tree)):
        assert tree.costs[index] == pytest.approx(path_length(tree.path(index)))
    with pytest.raises(ValueError, match="cycle"):
        tree.reparent(shorter, d)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_first_connect_attempt_matches_frozen_reference(seed: int) -> None:
    scene = detour()
    expected = legacy_connect(
        scene.grid,
        scene.start,
        scene.goal,
        seed,
        PlanningLimits(time_limit=5),
        {"step_size": 1.5},
    )
    counters = Counter()
    actual = connect_once(
        scene.geometry(0),
        scene.start,
        scene.goal,
        np.random.default_rng(seed),
        Budget(5),
        Options(step=1.5),
        counters,
    )
    assert np.asarray(actual) == pytest.approx(np.asarray(expected.raw_path), abs=1e-12)
    assert counters["expanded_nodes"] == expected.counters.expanded_nodes
    assert counters["inserted_nodes"] == expected.counters.sampled_nodes
    assert scene.geometry(0).path(actual).valid


@pytest.mark.parametrize("method", ["rrt_connect", "rrt_star", "informed_rrt_star"])
def test_empty_direct_lower_bound_and_wrong_endpoints(method: str) -> None:
    protocol = read_config("stage5a_protocol.json")
    scene = load_scene("F5_EMPTY")
    result = plan(scene, method, 0, "margin", protocol, seconds=1)
    assert result["strict_geometry_valid"]
    assert result["termination_reason"] == "euclidean_lower_bound"
    assert result["best_length"] == pytest.approx(math.dist(scene.start, scene.goal))
    scene.start = (-1, 2, 2)
    invalid = plan(scene, method, 0, "point", protocol, seconds=1)
    assert invalid["termination_reason"] == "invalid_start"
    assert not invalid["reported_success"]


@pytest.mark.parametrize("method", ["rrt_star", "informed_rrt_star"])
@pytest.mark.parametrize("seed", [0, 1])
def test_star_reproducibility_strict_paths_and_nonincreasing_history(
    method: str, seed: int
) -> None:
    scene = detour()
    protocol = read_config("stage5a_protocol.json")
    options = Options(step=2, max_iterations=400, max_nodes=1000)
    first = plan(scene, method, seed, "point", protocol, seconds=10, options=options)
    second = plan(scene, method, seed, "point", protocol, seconds=10, options=options)
    assert first["strict_geometry_valid"]
    assert first["paths"] == second["paths"]
    assert first["counters"] == second["counters"]
    assert first["termination_reason"] == "iteration_budget"
    for path in first["paths"]:
        assert scene.geometry(0).path(path).valid
        assert path[0] == scene.start and path[-1] == scene.goal
    for history in (first["history"], first["raw_history"]):
        assert all(
            b["length"] < a["length"]
            for a, b in zip(history[:-1], history[1:], strict=True)
        )
        for event in history:
            assert event["length"] == pytest.approx(
                path_length(first["paths"][event["path_id"]])
            )
    assert first["counters"].get("rewires", 0) > 0


@pytest.mark.parametrize("method", ["rrt_star", "informed_rrt_star"])
def test_node_limits_and_timeout_do_not_claim_map_infeasibility(method: str) -> None:
    scene, protocol = detour(), read_config("stage5a_protocol.json")
    node = plan(
        scene, method, 0, "point", protocol, seconds=2, options=Options(max_nodes=2)
    )
    assert node["termination_reason"] == "node_budget"
    expired = plan(scene, method, 0, "point", protocol, seconds=1e-12)
    assert expired["termination_reason"] == "time_budget"
    assert expired["first_valid_time_s"] is None


@pytest.mark.parametrize("method", ["rrt_connect", "rrt_star", "informed_rrt_star"])
def test_sealed_map_has_no_false_success(method: str) -> None:
    result = plan(
        load_scene("F5_SEALED"),
        method,
        0,
        "body",
        read_config("stage5a_protocol.json"),
        seconds=0.02,
    )
    assert not result["strict_geometry_valid"]
    assert result["best_length"] is None
    assert result["termination_reason"] == "time_budget"


@pytest.mark.parametrize(
    "start,goal",
    [
        ((0, 0, 0), (4, 3, 2)),
        ((0, 0, 0), (-4, 0, 0)),
        ((0, 0, 0), (0, 0, 4)),
        ((2, 2, 2), (2, 2, 2)),
    ],
)
def test_informed_focal_geometry_rotation_and_uniform_ball(
    start: tuple, goal: tuple
) -> None:
    sampler = InformedSampler(start, goal)
    assert sampler.rotation.T @ sampler.rotation == pytest.approx(np.eye(3), abs=1e-12)
    assert np.linalg.det(sampler.rotation) == pytest.approx(1)
    rng = np.random.default_rng(5601)
    best = sampler.minimum + 4
    points = np.array([sampler.sample(rng, best) for _ in range(1500)])
    assert np.all(
        np.linalg.norm(points - start, axis=1) + np.linalg.norm(points - goal, axis=1)
        <= best + 1e-10
    )
    minor = math.sqrt(best**2 - sampler.minimum**2) / 2
    normalized = (points - sampler.center) @ sampler.rotation / [best / 2, minor, minor]
    assert np.mean(np.linalg.norm(normalized, axis=1) ** 3) == pytest.approx(
        0.5, abs=0.035
    )
    degenerate = sampler.sample(rng, sampler.minimum)
    assert (
        math.dist(start, degenerate) + math.dist(degenerate, goal)
        <= sampler.minimum + 1e-10
    )


def test_informed_bad_bound_and_documented_neighbor_radius() -> None:
    with pytest.raises(ValueError):
        InformedSampler((0, 0, 0), (2, 0, 0)).sample(np.random.default_rng(0), 1)
    assert neighbor_radius(2, 5, 100) <= 5
    assert neighbor_radius(1000000, 5, 100) < neighbor_radius(1000, 5, 100)
    with pytest.raises(ValueError):
        Options(step=0)


def test_deadline_during_certification_does_not_backfill_solution() -> None:
    class Clock:
        value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = Clock()
    grid = OccupancyMap(np.zeros((10, 10, 10), dtype=bool))

    class Delayed(Geometry):
        def path(self, path: object) -> object:
            result = super().path(path)
            clock.value = 2
            return result

    solution = Solutions(Delayed(grid, 0), (1, 1, 1), (8, 8, 8), Budget(1, clock))
    with pytest.raises(RuntimeError, match="time_budget"):
        solution.accept([(1, 1, 1), (8, 8, 8)])
    assert not solution.history and not solution.raw_history
