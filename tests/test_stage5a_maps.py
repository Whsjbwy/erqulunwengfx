"""Scale-specific witness and infeasibility checks before actual search."""

import numpy as np
import pytest

from gsunlight_repro.stage5a.maps import body_radius, load_scene, read_config

MAPS = read_config("stage5a_maps.json")["maps"]


@pytest.mark.parametrize("spec", MAPS, ids=[item["id"] for item in MAPS])
def test_reachability_is_rechecked_for_each_body_scale(spec: dict) -> None:
    scene = load_scene(spec["id"])
    body = body_radius(read_config("stage5a_protocol.json"))
    for radius in (0, body, body + 0.25):
        verdict = scene.reachability(radius)
        if spec["family"] == "sealed":
            assert "full_barrier" in verdict
        elif spec.get("opening_m", 100) <= 2 * radius:
            assert "unreachable_aperture" in verdict
        else:
            assert verdict == "certified_reachable_geometry_only"
        assert scene.geometry(radius).segment(scene.start, scene.start).valid
        assert scene.geometry(radius).segment(scene.goal, scene.goal).valid
    assert not scene.grid.occupancy.flags.writeable


def test_seeded_maps_repeat_and_near_bed_has_no_free_top_escape() -> None:
    first, second = load_scene("H5_B2"), load_scene("H5_B2")
    assert np.array_equal(first.grid.occupancy, second.grid.occupancy)
    assert np.array_equal(first.ceiling.occupancy, second.ceiling.occupancy)
    assert (
        first.geometry(0).segment((3.5, 3.5, 20), (46.5, 32.5, 20)).reason
        == "mission_ceiling"
    )
    assert first.specification["seed"] == 5204


@pytest.mark.parametrize("family", ["O", "B", "N"])
def test_two_heldout_maps_have_distinct_voxel_geometry(family: str) -> None:
    first, second = load_scene(f"H5_{family}1"), load_scene(f"H5_{family}2")
    assert not np.array_equal(first.grid.occupancy, second.grid.occupancy)
