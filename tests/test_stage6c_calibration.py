"""Meaningful roster and source/state-space fairness constraints."""

import pytest

from gsunlight_repro.stage5a.maps import read_config
from gsunlight_repro.stage6c.calibration import manifest, validate_events


def test_only_one_sst_radius_changes_between_first_solution_conditions() -> None:
    config = read_config("stage6c_protocol.json")["c2"]["conditions"]
    default, radius, anytime = config[1:]
    assert {k for k in default if default[k] != radius[k]} == {"id", "selection_radius"}
    assert {k for k in radius if radius[k] != anytime[k]} == {"id", "mode"}


def test_fixed_full_roster_has_unique_positive_seeds_and_no_holdout() -> None:
    jobs = manifest(read_config("stage6c_protocol.json"))
    assert len(jobs) == len({j["job_id"] for j in jobs}) == 72
    assert {j["seed"] for j in jobs} == {1, 2, 3}
    assert {j["scenario"] for j in jobs} == {
        "straight",
        "left_arc",
        "right_arc",
        "climb",
        "dive",
        "combined",
    }
    assert len({j["condition"] for j in jobs[:4]}) == 4
    assert all(j["scenario"] == "straight" and j["seed"] == 1 for j in jobs[:4])


def test_float_plateau_is_valid_but_an_extra_interval_is_not() -> None:
    plateau = [
        {"certificate_intervals": 1152, "cost": value}
        for value in (115.20000000000002, 115.2)
    ]
    assert validate_events(plateau) == [115.20000000000002, 115.2]
    with pytest.raises(ValueError):
        validate_events(plateau + [{"certificate_intervals": 1153, "cost": 115.3}])
