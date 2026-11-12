"""Manifest completeness, deterministic selection and same-source shortcuts."""

import copy

import pytest

from gsunlight_repro.stage5ar.evidence import (
    freeze_manifest,
    protect_output,
    read_manifest,
    select_pilot,
)
from gsunlight_repro.stage5ar.p0 import empty_scene
from gsunlight_repro.stage5ar.replay import classify, compare_frozen, initial_state
from gsunlight_repro.stage5ar.runner import shortcut


def records() -> list[dict]:
    """Synthetic selection fixture only, never used as research evidence."""
    return [
        {
            "job_id": f"case_{i}",
            "family": "ordinary",
            "scene": "O1" if i < 5 else "O2",
            "historical_termination_time_s": float(i + 1),
            "primary_class": "tracking_error_limit" if i % 2 else "swept_safety_reject",
            "in_expansion": True,
            "is_selected": False,
            "selection_reason": "",
            "path_id": 0,
            "is_selected_path": True,
            "is_raw_best": False,
        }
        for i in range(10)
    ]


def test_sampling_is_rule_based_with_both_scenes_and_earliest_latest() -> None:
    first = select_pilot(records(), 6)
    reverse = select_pilot(list(reversed(records())), 6)
    chosen = {row["job_id"] for row in first if row["is_selected"]}
    assert chosen == {row["job_id"] for row in reverse if row["is_selected"]}
    assert len(chosen) == 6
    assert {"case_0", "case_1", "case_9"} <= chosen
    assert {row["scene"] for row in first if row["is_selected"]} == {"O1", "O2"}


def test_manifest_cannot_be_overwritten_or_have_duplicate_paths(tmp_path) -> None:
    path = tmp_path / "sampling_manifest.csv"
    rows = records()
    freeze_manifest(path, rows)
    assert len(read_manifest(path)) == 10
    with pytest.raises(FileExistsError, match="frozen"):
        freeze_manifest(path, rows)
    other = tmp_path / "duplicate.csv"
    freeze_manifest(other, rows + [rows[0]])
    with pytest.raises(ValueError, match="Duplicate"):
        read_manifest(other)


def test_shortcut_is_exact_same_source_vertex_subsequence() -> None:
    scene = empty_scene()
    raw = [scene.start, (20, 10, 8), (30, 10, 8), scene.goal]
    before = copy.deepcopy(raw)
    derived, indices = shortcut(raw, scene, 1.02)
    assert derived == [scene.start, scene.goal]
    assert derived == [raw[index] for index in indices]
    assert indices == [0, 3]
    assert raw == before


def test_initial_yaw_change_does_not_change_task_and_has_clear_units() -> None:
    scene = empty_scene()
    path = [scene.start, (8, 25, 8), scene.goal]
    condition = {"initial_yaw": "first_segment", "speed_m_s": 0.5}
    state = initial_state(path, scene, condition)
    assert state.yaw == pytest.approx(1.5707963267948966)
    assert state.pitch == 0 and state.speed == 0.5
    assert scene.goal == (38, 8, 8)
    with pytest.raises(ValueError, match="undefined"):
        initial_state([scene.start, (8, 8, 20)], scene, condition)


@pytest.mark.parametrize(
    "reason,expected",
    [
        (
            "geometry_rejected_before_tracking_physical_obstacle",
            "geometry_precheck_reject",
        ),
        ("physical_sweep_rejected_workspace_boundary", "swept_safety_reject"),
        ("mission_band_sweep_rejected", "mission_band_reject"),
        ("goal_reached_required_margin_violated", "margin_only_failure"),
        ("execution_resource_timeout", "resource_timeout"),
        ("simulation_timeout", "goal_not_reached"),
    ],
)
def test_exclusive_failure_categories(reason: str, expected: str) -> None:
    assert classify(reason) == expected


def test_unknown_classification_and_changed_baseline_raise() -> None:
    with pytest.raises(ValueError, match="Unclassified"):
        classify("unknown")
    with pytest.raises(ValueError, match="mismatch"):
        compare_frozen({"eligible": False}, {"eligible": True})


def test_historical_repository_output_is_protected() -> None:
    from pathlib import Path

    with pytest.raises(ValueError, match="historical"):
        protect_output(Path("results/stage5a"))
    assert protect_output(Path("results/stage5ar")).name == "stage5ar"
