"""Prospective geometry, paired uncertainty and continuous trace recertification."""

import copy

import numpy as np
import pytest

from gsunlight_repro.stage5a.maps import load_scene, read_config
from gsunlight_repro.stage5ae.analysis import paired_summary
from gsunlight_repro.stage5ae.audit import check_safety
from gsunlight_repro.stage5ae.maps import generate, validate_maps
from gsunlight_repro.stage5ae.tracking import simulate
from gsunlight_repro.stage5ar.p0 import empty_scene


def test_new_maps_have_new_geometry_and_reproducible_certificates() -> None:
    document = read_config("stage5ae_maps.json")
    vehicle = read_config("stage5a_protocol.json")
    audit = validate_maps(document, vehicle)
    assert audit["passed"] and audit["map_count"] == 12
    old = load_scene("H5_O1")
    for spec in document["maps"]:
        first, second = generate(spec, document), generate(spec, document)
        assert np.array_equal(first.grid.occupancy, second.grid.occupancy)
        assert first.start == second.start and first.goal == second.goal
        assert first.grid.shape != old.grid.shape
        assert first.start != old.start and first.goal != old.goal
    assert (
        sum(
            row["reachability"]["body"].startswith("certified_reachable")
            for row in audit["maps"]
        )
        == 12
    )
    assert (
        sum(
            row["reachability"]["margin"].startswith("certified_reachable")
            for row in audit["maps"]
        )
        == 11
    )


def test_map_paired_intervals_keep_losses_and_exclude_envelope_negatives() -> None:
    base = {
        "method": "rrt_star",
        "mode": "body",
        "factor": "controller_raw",
        "reachability": "certified_reachable_geometry_only",
        "first_success": False,
        "second_success": True,
    }
    rows = [base | {"scene": "A", "delta_success": 1}]
    rows += [
        base
        | {
            "scene": "B",
            "delta_success": -1,
            "first_success": True,
            "second_success": False,
        }
        for _ in range(3)
    ]
    rows += [
        base
        | {
            "scene": "negative",
            "delta_success": 1,
            "reachability": "certified_unreachable_aperture",
        }
    ]
    row = paired_summary(rows)[0]
    assert row["paired_tasks"] == 4 and row["known_feasible_maps"] == 2
    assert row["recovered"] == 1 and row["lost"] == 3
    assert row["end_to_end_delta"] == -0.5
    assert row["delta_ci95_low"] == -1 and row["delta_ci95_high"] == 1


def test_saved_sweeps_recertify_and_corrupt_speed_or_reason_fails() -> None:
    scene, vehicle = empty_scene(), read_config("stage5a_protocol.json")
    path = [scene.start, scene.goal]
    result = simulate(
        path, scene, vehicle, 0.0, {"id": "los_d2", "kind": "los3d", "lookahead_m": 2.0}
    )
    record = {
        "meta": {"mode": "body"},
        "summary": result.summary,
        "trace": result.trace,
    }
    assert check_safety(record, path, scene, vehicle) == len(result.trace)
    corrupt = copy.deepcopy(record)
    corrupt["trace"][0]["speed_m_s"] = 0.5
    with pytest.raises(ValueError, match="speed"):
        check_safety(corrupt, path, scene, vehicle)
    corrupt = copy.deepcopy(record)
    corrupt["trace"][-1]["physical_reason"] = "physical_obstacle"
    with pytest.raises(ValueError, match="recertify"):
        check_safety(corrupt, path, scene, vehicle)
