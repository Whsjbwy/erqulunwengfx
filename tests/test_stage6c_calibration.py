"""Meaningful roster and source/state-space fairness constraints."""

from pathlib import Path

import pytest

from gsunlight_repro.stage5a.maps import ROOT, read_config
from gsunlight_repro.stage6b import runner as frozen_runner
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


def test_ci_fixture_output_honors_frozen_runner_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the real output guard with both workflow producer and consumer."""
    lines = (
        (ROOT / ".github/workflows/stage6c-windows.yml")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    producer = next(line for line in lines if "stage6b.runner accept" in line)
    consumer = next(
        line for line in lines if "python scripts/stage6c_ci_evidence.py" in line
    )
    relative = producer.split("--output ", 1)[1].strip()
    assert consumer.split("--frozen-output ", 1)[1].strip() == relative
    root = tmp_path / "repository"
    monkeypatch.setattr(frozen_runner, "ROOT", root)
    args = (tmp_path / "runner.exe", tmp_path / "build", tmp_path / "raw")
    accepted = frozen_runner.Runner(*args, root / relative)
    assert accepted.output.is_relative_to(root / "results/stage6b")
    with pytest.raises(ValueError, match="historical result directories"):
        frozen_runner.Runner(*args, root / "results/stage6c/ci-frozen")
