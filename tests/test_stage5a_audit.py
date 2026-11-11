"""Reject inconsistent certification/execution evidence without editing it."""

import copy

import pytest

from gsunlight_repro.metrics import path_length
from gsunlight_repro.stage5a.audit import check_record, expected_identities
from gsunlight_repro.stage5a.maps import body_radius, load_scene, read_config
from gsunlight_repro.stage5a.tracking import track


def example() -> tuple[dict, object, dict]:
    """Construct a genuinely simulated tiny record using synthetic geometry."""
    protocol = read_config("stage5a_protocol.json")
    scene = load_scene("F5_EMPTY")
    path = [scene.start, scene.goal]
    event = {"path_id": 0, "time_s": 0.1, "length": path_length(path), "kind": "raw"}
    execution = track(path, scene, protocol, 0)
    item = {
        "row": {
            "radius_m": body_radius(protocol),
            "geometry_mode": "body",
            "time_budget_s": 3,
            "strict_geometry_valid": True,
            "first_valid_time_s": 0.1,
            "raw_path_id": 0,
            "selected_path_id": 0,
            "actual_total_s": 1,
            "validation_s": 0.1,
            "shortcut_s": 0.1,
            "search_and_bookkeeping_s": 0.8,
            "execution_success": execution["execution_success"],
        },
        "paths": [path],
        "history": [event],
        "raw_history": [dict(event)],
        "checkpoints": [
            {"checkpoint_s": 1, "valid": True, "best_length": event["length"]}
        ],
        "executions": {"0": execution},
    }
    return item, scene, protocol


def test_real_small_record_passes_additional_safety_audit() -> None:
    item, scene, protocol = example()
    result = check_record(item, scene, protocol)
    assert result["path_entries"] == result["accepted_executions"] == 1


@pytest.mark.parametrize("corruption", ["path", "late", "checkpoint", "radius"])
def test_inconsistent_evidence_is_rejected(corruption: str) -> None:
    original, scene, protocol = example()
    item = copy.deepcopy(original)
    if corruption == "path":
        item["paths"][0][-1] = (1000, 1000, 1000)
    elif corruption == "late":
        item["history"][0]["time_s"] = 4
    elif corruption == "radius":
        item["row"]["radius_m"] = 0
    else:
        item["checkpoints"][0]["valid"] = False
    with pytest.raises(ValueError):
        check_record(item, scene, protocol)


def test_full_matrix_keeps_all_seeds_and_scale_negative_cases() -> None:
    config = {
        "protocol": read_config("stage5a_protocol.json"),
        "maps": read_config("stage5a_maps.json"),
    }
    expected = expected_identities(
        config, {"steps_m": {"rrt_connect": 5, "rrt_star": 5, "informed_rrt_star": 5}}
    )
    assert len(expected) == 450
    assert "holdout_H5_N2_rrt_star_margin_seed4_step5" in expected
