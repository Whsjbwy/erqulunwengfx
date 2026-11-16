"""Development-map structure, positive seeds and hidden-witness protocol."""

from __future__ import annotations

import numpy as np
import pytest

from gsunlight_repro.stage5a.maps import read_config
from gsunlight_repro.stage6d.maps import box_slices, build_scenarios, roster


def test_six_registered_obstacle_maps_have_three_families_and_fixed_poses() -> None:
    cases = build_scenarios()
    assert len(cases) == 6
    assert len({case.scene.specification["family"] for case in cases}) == 3
    for case in cases:
        assert np.any(case.scene.grid.occupancy)
        assert not np.all(case.scene.grid.occupancy)
        assert case.initial.speed == 1
        assert case.initial.position == case.scene.start
        assert case.witness_controls
        assert len(case.scene.goal) == 3


def test_map_generation_is_reproducible_without_random_seed_search() -> None:
    first, second = build_scenarios(), build_scenarios()
    assert all(
        np.array_equal(a.scene.grid.occupancy, b.scene.grid.occupancy)
        and a.scene.goal == b.scene.goal
        for a, b in zip(first, second, strict=True)
    )


def test_all54_tasks_and_three_pilots_are_fixed() -> None:
    tasks = roster(read_config("stage6d_protocol.json"))
    assert len(tasks) == len({task["job_id"] for task in tasks}) == 54
    assert {task["seed"] for task in tasks} == {1, 2, 3}
    assert all(task["scenario"] == "wide_1" and task["seed"] == 1 for task in tasks[:3])
    assert len({task["id"] for task in tasks[:3]}) == 3
    assert all("controls" not in task for task in tasks)


@pytest.mark.parametrize("box", [[1, 0, 0, 1, 0, 1], [0.1, 1, 0, 1, 0, 1]])
def test_invalid_map_coordinates_are_not_silently_rounded(box: list[float]) -> None:
    with pytest.raises(ValueError):
        box_slices(box, [0.5] * 3)
