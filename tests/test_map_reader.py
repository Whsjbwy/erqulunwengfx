"""Synthetic VTI fixtures verify geometry and VTK's x-fastest cell indexing."""

from pathlib import Path

import numpy as np
import pytest
import pyvista as pv

from gsunlight_repro.map_reader import OccupancyMap, read_map


def test_read_map_preserves_vtk_cell_order_and_geometry(tmp_path: Path) -> None:
    shape = (2, 3, 4)
    expected = np.zeros(shape, dtype=bool)
    expected[1, 0, 0] = True
    expected[0, 2, 1] = True
    expected[1, 1, 3] = True
    image = pv.ImageData(dimensions=(3, 4, 5), origin=(10, -6, 2), spacing=(2, 3, 4))
    image.cell_data["obstacle"] = expected.flatten(order="F").astype(float)
    path = tmp_path / "synthetic.vti"
    image.save(path)
    grid = read_map(path)
    np.testing.assert_array_equal(grid.occupancy, expected)
    assert grid.shape == shape
    assert grid.origin == (10, -6, 2)
    assert grid.spacing == (2, 3, 4)
    assert grid.bounds == (10, 14, -6, 3, 2, 18)
    for index in np.ndindex(shape):
        cell_id = index[0] + shape[0] * (index[1] + shape[1] * index[2])
        assert bool(image.cell_data["obstacle"][cell_id]) == grid.occupancy[index]
        cell_bounds = image.GetCell(cell_id).GetBounds()
        expected_bounds = tuple(
            edge
            for axis in range(3)
            for edge in (
                grid.origin[axis] + index[axis] * grid.spacing[axis],
                grid.origin[axis] + (index[axis] + 1) * grid.spacing[axis],
            )
        )
        assert cell_bounds == pytest.approx(expected_bounds)


def test_nonzero_vtk_extent_uses_physical_minimum_corner(tmp_path: Path) -> None:
    image = pv.ImageData(origin=(7, -10, 2), spacing=(2, 3, 4))
    image.extent = (3, 5, -2, 1, 4, 8)
    image.cell_data["obstacle"] = np.zeros(image.n_cells)
    path = tmp_path / "offset.vti"
    image.save(path)
    grid = read_map(path)
    assert grid.origin == (13, -16, 18)
    assert grid.shape == (2, 3, 4)
    assert grid.bounds == pytest.approx(image.bounds)


def test_missing_file_is_explicit(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        read_map(tmp_path / "missing.vti")


@pytest.mark.parametrize("value", [2, -1, np.nan, np.inf])
def test_nonbinary_map_is_rejected(tmp_path: Path, value: float) -> None:
    image = pv.ImageData(dimensions=(3, 3, 3))
    values = np.zeros(image.n_cells)
    values[0] = value
    image.cell_data["obstacle"] = values
    path = tmp_path / "nonbinary.vti"
    image.save(path)
    with pytest.raises(ValueError, match="binary"):
        read_map(path)


def test_missing_cell_field_is_rejected(tmp_path: Path) -> None:
    image = pv.ImageData(dimensions=(3, 3, 3))
    image.point_data["obstacle"] = np.zeros(image.n_points)
    path = tmp_path / "points_only.vti"
    image.save(path)
    with pytest.raises(ValueError, match="cell_data"):
        read_map(path)


def test_rotated_map_is_rejected(tmp_path: Path) -> None:
    image = pv.ImageData(dimensions=(3, 3, 3))
    image.direction_matrix = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    image.cell_data["obstacle"] = np.zeros(image.n_cells)
    path = tmp_path / "rotated.vti"
    image.save(path)
    with pytest.raises(ValueError, match="Rotated"):
        read_map(path)


def test_nonvolume_map_is_rejected(tmp_path: Path) -> None:
    image = pv.ImageData(dimensions=(3, 3, 1))
    image.cell_data["obstacle"] = np.zeros(image.n_cells)
    path = tmp_path / "plane.vti"
    image.save(path)
    with pytest.raises(ValueError, match="three-dimensional"):
        read_map(path)


def test_nonpositive_spacing_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = pv.ImageData(dimensions=(3, 3, 3))
    image.cell_data["obstacle"] = np.zeros(image.n_cells)
    image.SetSpacing(-1, 1, 1)
    path = tmp_path / "spacing.vti"
    path.touch()
    monkeypatch.setattr(pv, "read", lambda _: image)
    with pytest.raises(ValueError, match="spacing"):
        read_map(path)


def test_multicomponent_cell_field_is_rejected(tmp_path: Path) -> None:
    image = pv.ImageData(dimensions=(3, 3, 3))
    image.cell_data["obstacle"] = np.zeros((image.n_cells, 2))
    path = tmp_path / "multicomponent.vti"
    image.save(path)
    with pytest.raises(ValueError, match="one scalar"):
        read_map(path)


@pytest.mark.parametrize(
    ("occupancy", "origin", "spacing"),
    [
        (np.zeros((2, 2)), (0, 0, 0), (1, 1, 1)),
        (np.zeros((2, 2, 2)), (0, 0, 0), (1, 1, 1)),
        (np.zeros((2, 2, 2), dtype=bool), (0, 0), (1, 1, 1)),
        (np.zeros((2, 2, 2), dtype=bool), (0, 0, np.nan), (1, 1, 1)),
        (np.zeros((2, 2, 2), dtype=bool), (0, 0, 0), (1, 0, 1)),
    ],
)
def test_invalid_map_geometry_is_rejected(
    occupancy: np.ndarray, origin: tuple, spacing: tuple
) -> None:
    with pytest.raises(ValueError):
        OccupancyMap(occupancy, origin, spacing)
