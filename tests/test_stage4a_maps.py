"""Verify every frozen new map without running a planning algorithm."""

import numpy as np
import pytest

from gsunlight_repro.collision_checker import validate_path
from gsunlight_repro.stage4a.maps import load_map, map_features, recipe, specifications


@pytest.mark.parametrize("spec", specifications(), ids=lambda s: s["id"])
def test_registered_geometry_and_witness_are_valid(spec) -> None:
    scene = load_map(spec["id"])
    assert scene.start != (2, 2, 3) and scene.goal != (57, 47, 35)
    assert not validate_path([scene.start, scene.goal], scene.grid).valid
    assert not scene.grid.occupancy.flags.writeable
    if spec["family"] != "sealed":
        assert validate_path(scene.witness_path, scene.grid).valid
    else:
        assert scene.reachability == "certified_unreachable"
    assert map_features(scene)["occupied_fraction"] > 0


def test_new_maps_are_reproducible_and_splits_are_frozen() -> None:
    specs = specifications()
    assert len([s for s in specs if s["split"] == "development"]) == 4
    assert len([s for s in specs if s["split"] == "holdout"]) == 8
    assert len({s["seed"] for s in specs}) == 13
    for spec in specs:
        assert recipe(spec) == recipe(spec)
    assert np.array_equal(load_map("T4").grid.occupancy, load_map("T4").grid.occupancy)


def test_unknown_maps_are_rejected_and_legacy_is_explicit() -> None:
    with pytest.raises(ValueError, match="Unregistered"):
        load_map("H1")
    assert load_map("S1").metadata["split"] == "legacy"
