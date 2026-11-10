"""Verify isolated safety hooks and restricted local diagnostic copies."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from gsunlight_repro.diagnostics import adapt
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.metrics import path_length


@pytest.fixture
def occupied_grid() -> OccupancyMap:
    """Provide one closed obstacle with free space on all sides."""
    occupancy = np.zeros((4, 4, 4), dtype=bool)
    occupancy[1, 1, 1] = True
    return OccupancyMap(occupancy)


def synthetic_utils(
    candidates: NDArray[np.float32] | None = None,
    processed: NDArray[np.float64] | None = None,
) -> ModuleType:
    """Create independently written callables matching the adapter protocol."""
    module = ModuleType("synthetic_utils")

    def findtangent(*args: Any, **kwargs: Any) -> NDArray[np.float32]:
        """Return synthetic candidate coordinates and their added costs."""
        if candidates is None:
            return np.empty((0, 4), dtype=np.float32)
        return candidates.copy()

    def findcross(*args: Any, **kwargs: Any) -> tuple[int, float]:
        """Model an unsafe checker which always declares success."""
        return 0, 0.0

    def backendprocess(
        path: NDArray[np.float64], *args: Any, **kwargs: Any
    ) -> tuple[float, NDArray[np.float64]]:
        """Return a synthetic smoothing outcome without modifying input."""
        result = np.asarray(path).copy() if processed is None else processed.copy()
        return -1.0, result

    module.findtangent = findtangent
    module.findcross = findcross
    module.backendprocess = backendprocess
    return module


def test_rejects_colliding_parent_candidate_edges(occupied_grid: OccupancyMap) -> None:
    """Keep the safe candidate while rejecting a segment through the obstacle."""
    candidates = np.array(
        [[2.5, 1.5, 1.5, 2.0], [0.5, 3.5, 1.5, 2.0]], dtype=np.float32
    )
    utils = synthetic_utils(candidates)
    parameters: dict[str, Any] = {}
    with adapt(utils, occupied_grid, parameters):
        accepted = utils.findtangent([0.5, 1.5, 1.5], [3.5, 1.5, 1.5])
    np.testing.assert_array_equal(accepted, candidates[1:])
    assert parameters["diagnostic_counts"]["rejected_edges"] == 1
    assert parameters["diagnostic_counts"]["direct_goal_candidates"] == 0


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ([0.5, 1.5, 1.5], [3.5, 1.5, 1.5]),
        ([0.5, 1.5, 1.5], [1.1, 1.5, 1.5]),
        ([1.5, 1.5, 1.5], [1.5, 1.5, 1.5]),
        ([0.5, 0.5, 0.5], [-0.1, 0.5, 0.5]),
    ],
)
def test_strict_links_check_interiors_endpoints_and_bounds(
    occupied_grid: OccupancyMap, first: list[float], second: list[float]
) -> None:
    """A large sampling step cannot hide a collision, bad endpoint or zero link."""
    utils = synthetic_utils()
    with adapt(utils, occupied_grid, {}):
        flag, length = utils.findcross(first, second, object(), 100)
    assert flag == 1
    assert length == pytest.approx(np.linalg.norm(np.asarray(second) - first))


def test_visible_goal_emits_a_recorded_zero_cost_candidate(
    occupied_grid: OccupancyMap,
) -> None:
    """Preserve the repeated sun point used to represent a direct goal link."""
    utils = synthetic_utils()
    parameters: dict[str, Any] = {}
    sun = [0.5, 0.5, 0.5]
    with adapt(utils, occupied_grid, parameters):
        candidate = utils.findtangent(sun, [3.5, 0.5, 0.5])
        flag, length = utils.findcross(sun, sun, object(), 100)
    np.testing.assert_array_equal(candidate, np.array([[*sun, 0]], dtype=np.float32))
    assert candidate.dtype == np.float32
    assert flag == 0 and length == 0
    assert parameters["diagnostic_counts"]["direct_goal_candidates"] == 1
    assert len(parameters["safety_changes"]) == 4


def test_smoothing_rolls_back_when_the_complete_path_is_invalid(
    occupied_grid: OccupancyMap,
) -> None:
    """Reject a smoothing shortcut even if its endpoints remain free."""
    original = np.array(
        [[0.5, 1.5, 1.5], [0.5, 3.5, 1.5], [3.5, 3.5, 1.5], [3.5, 1.5, 1.5]]
    )
    shortcut = original[[0, -1]]
    utils = synthetic_utils(processed=shortcut)
    parameters: dict[str, Any] = {}
    with adapt(utils, occupied_grid, parameters):
        length, smoothed = utils.backendprocess(original, 1, object())
    np.testing.assert_array_equal(smoothed, original)
    assert length == path_length(original)
    assert parameters["diagnostic_counts"]["smoothing_rollbacks"] == 1


def test_smoothing_rejects_an_already_invalid_input(
    occupied_grid: OccupancyMap,
) -> None:
    """Never describe an invalid incoming path as a successful rollback."""
    utils = synthetic_utils()
    with adapt(utils, occupied_grid, {}), pytest.raises(ValueError, match="invalid"):
        utils.backendprocess(np.array([[0.5, 1.5, 1.5], [3.5, 1.5, 1.5]]), 1, None)


def test_smoothing_rollback_survives_in_place_backend_changes(
    occupied_grid: OccupancyMap,
) -> None:
    """Preserve both the rollback evidence and caller input after mutation."""
    original = np.array(
        [[0.5, 1.5, 1.5], [0.5, 3.5, 1.5], [3.5, 3.5, 1.5], [3.5, 1.5, 1.5]]
    )
    expected = original.copy()
    utils = synthetic_utils()

    def mutating_backend(
        path: NDArray[np.float64], step: float, map_data: Any
    ) -> tuple[float, NDArray[np.float64]]:
        """Move a valid waypoint into the occupied voxel in place."""
        path[1] = [1.5, 1.5, 1.5]
        return -1.0, path

    utils.backendprocess = mutating_backend
    parameters: dict[str, Any] = {}
    with adapt(utils, occupied_grid, parameters):
        length, smoothed = utils.backendprocess(original, 1, object())
    np.testing.assert_array_equal(smoothed, expected)
    np.testing.assert_array_equal(original, expected)
    assert length == path_length(expected)
    assert parameters["diagnostic_counts"]["smoothing_rollbacks"] == 1


def test_context_restores_all_functions_after_an_exception(
    occupied_grid: OccupancyMap,
) -> None:
    """An interrupted diagnosis must not leave modified functions in the module."""
    utils = synthetic_utils()
    originals = (utils.findtangent, utils.findcross, utils.backendprocess)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with adapt(utils, occupied_grid, {}):
            assert utils.findtangent is not originals[0]
            assert utils.findcross is not originals[1]
            assert utils.backendprocess is not originals[2]
            raise RuntimeError("synthetic failure")
    assert (utils.findtangent, utils.findcross, utils.backendprocess) == originals


@pytest.fixture
def prepare_module() -> ModuleType:
    """Load the source-preparation script without invoking its command line."""
    script = (
        Path(__file__).resolve().parents[1] / "scripts/prepare_diagnostic_source.py"
    )
    spec = importlib.util.spec_from_file_location("prepare_diagnostic_source", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_synthetic_source(path: Path) -> tuple[bytes, bytes]:
    """Write tiny independent inputs plus files that must never be copied."""
    path.mkdir()
    main = (
        b"# synthetic fixture\r\nmax_num = 1  # capacity only\r\n"
        b"other = 1\r\ndef nested():\r\n    max_num = 1\r\n    return max_num\r\n"
    )
    utils = b"# independent synthetic utility\r\ndef helper():\r\n    return 1\r\n"
    (path / "main_sunlight_3Dgrid.py").write_bytes(main)
    (path / "utils.py").write_bytes(utils)
    for name in ("map.vti", "paper.pdf", "source.zip"):
        (path / name).write_bytes(b"excluded synthetic material")
    return main, utils


@pytest.mark.parametrize("capacity", [1, 3, 5])
def test_prepare_copies_only_source_and_changes_one_capacity_value(
    tmp_path: Path, prepare_module: ModuleType, capacity: int
) -> None:
    """Keep all other bytes, nested values and excluded files untouched."""
    source = tmp_path / "source"
    main, utils = create_synthetic_source(source)
    destination = tmp_path / "diagnostic"
    result = prepare_module.prepare_source(source, destination, capacity)
    assert result == destination.resolve()
    assert sorted(path.name for path in destination.iterdir()) == [
        "main_sunlight_3Dgrid.py",
        "utils.py",
    ]
    expected = main.replace(b"max_num = 1", f"max_num = {capacity}".encode(), 1)
    assert (destination / "main_sunlight_3Dgrid.py").read_bytes() == expected
    assert (destination / "utils.py").read_bytes() == utils
    assert (source / "main_sunlight_3Dgrid.py").read_bytes() == main


def test_prepare_never_overwrites_an_existing_directory(
    tmp_path: Path, prepare_module: ModuleType
) -> None:
    """An existing diagnostic directory must remain exactly as it was."""
    source = tmp_path / "source"
    create_synthetic_source(source)
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises((FileExistsError, ValueError)):
        prepare_module.prepare_source(source, destination, 3)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert list(destination.iterdir()) == [marker]


@pytest.mark.parametrize("boundary", ["source", "repository"])
def test_prepare_rejects_author_or_repository_subdirectories(
    tmp_path: Path,
    prepare_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    """Do not write restricted source copies inside either protected tree."""
    source = tmp_path / "source"
    create_synthetic_source(source)
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(prepare_module, "REPOSITORY_ROOT", repository)
    destination = (source if boundary == "source" else repository) / "copy"
    with pytest.raises(ValueError):
        prepare_module.prepare_source(source, destination, 3)
    assert not destination.exists()


@pytest.mark.parametrize("capacity", [0, 2, 10])
def test_prepare_rejects_unsupported_capacities(
    tmp_path: Path, prepare_module: ModuleType, capacity: int
) -> None:
    """Keep the implemented diagnostic comparison limited to its declared values."""
    source = tmp_path / "source"
    create_synthetic_source(source)
    destination = tmp_path / "diagnostic"
    with pytest.raises(ValueError):
        prepare_module.prepare_source(source, destination, capacity)
    assert not destination.exists()
