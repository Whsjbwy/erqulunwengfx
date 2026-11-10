"""Frozen map recipes require real geometric reachability evidence."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.scenarios import generate_scenario, load_scenario, load_scenarios

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "stage2_maps.json"


def small_config() -> dict:
    """Return a small, independently authored empty map recipe."""
    return {
        "shape": [8, 7, 6],
        "origin": [0, 0, 0],
        "spacing": [1, 1, 1],
        "start": [1, 1, 1],
        "goal": [7, 6, 5],
        "scene_id": "small",
        "kind": "empty",
        "map_seed": 0,
        "description": "Synthetic test",
        "reachability": "certified_reachable",
        "witness_path": [[1, 1, 1], [7, 6, 5]],
    }


def test_frozen_suite_has_valid_endpoints_and_predeclared_witnesses() -> None:
    scenarios = load_scenarios(CONFIG)
    assert [scene.scene_id for scene in scenarios] == ["S0", "S1", "S2", "S3", "S4"]
    for scene in scenarios:
        assert scene.grid.shape == (100, 80, 80)
        assert scene.start == (2, 2, 2)
        assert scene.goal == (95, 75, 75)
        assert validate_path([scene.start, scene.start], scene.grid).valid
        assert validate_path([scene.goal, scene.goal], scene.grid).valid
        if scene.witness_path is not None:
            assert validate_path(scene.witness_path, scene.grid).valid
    assert not np.any(scenarios[0].grid.occupancy)
    for scene in scenarios[1:]:
        assert not validate_path([scene.start, scene.goal], scene.grid).valid


def test_frozen_recipes_repeat_without_stochastic_map_selection() -> None:
    first = load_scenario(CONFIG, "S3")
    second = load_scenario(CONFIG, "S3")
    np.testing.assert_array_equal(first.grid.occupancy, second.grid.occupancy)
    assert first.metadata["world_z_offset"] == -80
    assert first.metadata["generation"] == "deterministic_recipe_no_stochastic_draws"


def test_full_axis_barrier_is_a_complete_no_path_certificate() -> None:
    scene = load_scenario(CONFIG, "S4")
    assert scene.reachability == "certified_unreachable"
    assert scene.witness_path is None
    assert scene.start[0] < 48 < 52 < scene.goal[0]
    assert np.all(scene.grid.occupancy[48:52, :, :])


def test_reachable_config_cannot_hide_an_invalid_witness() -> None:
    config = small_config()
    config["boxes"] = [{"lower": [3, 0, 0], "upper": [4, 7, 6]}]
    with pytest.raises(ValueError, match="witness"):
        generate_scenario(config)


def test_empty_witness_is_rejected_with_a_clear_error() -> None:
    config = small_config()
    config["witness_path"] = []
    with pytest.raises(ValueError, match="witness"):
        generate_scenario(config)


def test_endpoint_obstacle_is_rejected_instead_of_cleared() -> None:
    config = small_config()
    config["boxes"] = [{"lower": [0, 0, 0], "upper": [2, 2, 2]}]
    with pytest.raises(ValueError, match="start"):
        generate_scenario(config)


def test_false_unreachable_certificate_is_rejected() -> None:
    config = small_config()
    config.update(
        reachability="certified_unreachable",
        witness_path=None,
        certificate={"kind": "full_axis_barrier", "axis": 0, "lower": 3, "upper": 4},
    )
    with pytest.raises(ValueError, match="gap"):
        generate_scenario(config)


def test_explicit_recipe_is_not_mutated_by_generation() -> None:
    config = small_config()
    before = copy.deepcopy(config)
    generate_scenario(config)
    assert config == before


def test_unknown_scene_and_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown scene"):
        load_scenario(CONFIG, "missing")
    config = small_config()
    document = {"schema_version": 1, "profile": {}, "scenarios": [config, config]}
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_scenarios(path)
