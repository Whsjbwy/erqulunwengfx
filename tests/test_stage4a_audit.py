"""Detect invalid archived geometry and retrospective checkpoint backfilling."""

import json

import pytest

from gsunlight_repro.metrics import path_length
from gsunlight_repro.stage4a.audit import audit
from gsunlight_repro.stage4a.maps import load_map
from gsunlight_repro.stage4a.runner import Runner


def evidence(tmp_path):
    runner = Runner(tmp_path / "private", tmp_path / "public")
    scene = load_map("D1")
    path = scene.witness_path
    length = path_length(path)
    event = {"time_s": 0.2, "length": length, "path_id": 0, "kind": "raw"}
    item = {
        "row": {
            "job_id": "D1_A1_seed0",
            "scene": "D1",
            "method": "A1",
            "seed": 0,
            "total_budget_s": 30,
            "strict_valid": True,
            "first_valid_time_s": 0.2,
        },
        "paths": [path],
        "history": [event],
        "raw_history": [event],
        "checkpoints": [
            {
                "checkpoint_s": 0.1,
                "valid": False,
                "best_length": None,
                "raw_best_length": None,
            },
            {
                "checkpoint_s": 30,
                "valid": True,
                "best_length": length,
                "raw_best_length": length,
            },
        ],
    }
    folder = runner.local / "D1_A1_seed0"
    folder.mkdir()
    source = folder / "result.json"
    source.write_text(json.dumps(item))
    return runner, source, item


def test_audit_validates_coordinates_and_preserves_original_evidence(tmp_path) -> None:
    runner, source, _ = evidence(tmp_path)
    original = source.read_bytes()
    result = audit(runner.local)
    assert result["independent_trials"] == 1 and result["invalid_paths"] == 0
    assert result["distinct_map_polylines_checked"] == 1
    assert source.read_bytes() == original
    with pytest.raises(ValueError, match="complete"):
        audit(runner.local, expected_trials=402)


@pytest.mark.parametrize("corruption", ["late", "invalid", "backfilled"])
def test_audit_rejects_bad_certificates(tmp_path, corruption) -> None:
    runner, source, item = evidence(tmp_path)
    if corruption == "late":
        item["history"][0]["time_s"] = 30.1
    elif corruption == "invalid":
        scene = load_map("D1")
        item["paths"][0] = [scene.start, scene.goal]
    else:
        item["checkpoints"][0].update(
            valid=True, best_length=item["history"][0]["length"]
        )
    source.write_text(json.dumps(item))
    with pytest.raises(ValueError):
        audit(runner.local)
