"""Paired recovery/loss, missing outcomes and immutable global identities."""

import json

import pytest

from gsunlight_repro.stage5af.analysis import (
    CONTROLLERS,
    interval,
    paired,
    planning_rows,
)


def conditions() -> list[dict]:
    """Synthetic export fixture, never included in scientific result counts."""
    rows = []
    for processing in ("raw", "shortcut"):
        for controller in CONTROLLERS:
            success = (processing == "raw") == (controller == "los_terminal_v1")
            rows.append(
                {
                    "job_id": "a",
                    "case_id": f"a--{processing}--{controller}",
                    "scene": "A",
                    "family": "ordinary",
                    "method": "rrt_star",
                    "mode": "body",
                    "phase": "development",
                    "reachability": "certified_reachable_geometry_only",
                    "processing": processing,
                    "controller": controller,
                    "execution_success": success,
                    "primary_class": "success" if success else "tracking_error_limit",
                    "max_tracking_error_m": None,
                }
            )
    return rows


def test_pairing_keeps_recovered_and_regressed_conditions() -> None:
    rows = paired(conditions())
    assert next(r for r in rows if r["factor"] == "terminal_raw")["delta_success"] == 1
    assert (
        next(r for r in rows if r["factor"] == "terminal_shortcut")["delta_success"]
        == -1
    )
    assert not any(r["error_improved"] for r in rows)
    with pytest.raises(ValueError, match="Missing"):
        paired(conditions()[:-1])
    with pytest.raises(ValueError, match="Duplicate"):
        paired(conditions() + conditions()[:1])


def test_cluster_interval_preserves_undefined_and_signed_differences() -> None:
    assert interval([0, 0], [0, 0]) == (None, None)
    assert interval([1, -3], [1, 3]) == (-1.0, 1.0)


def test_raw_registry_index_cannot_override_global_path_identity(tmp_path) -> None:
    value = {
        "job_id": "case",
        "scene": "A",
        "family": "ordinary",
        "method": "rrt_star",
        "mode": "body",
        "seed": 0,
        "reachability": "certified_reachable",
        "raw": [[0, 0, 0], [1, 0, 0]],
        "search": {"raw_path_id": 17},
    }
    (tmp_path / "case.json").write_text(json.dumps(value), encoding="utf-8")
    row = planning_rows(tmp_path, "independent")[0]
    assert row["raw_path_id"] == "case::raw" and row["raw_registry_path_id"] == 17
