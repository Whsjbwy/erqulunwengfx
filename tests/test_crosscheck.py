"""Small synthetic maps exercise the independent VTK sample queries."""

import numpy as np
import pytest
import pyvista as pv

from gsunlight_repro.crosscheck import dense_vtk_check


def make_image(occupied: bool = False, spacing: float = 1.0) -> pv.ImageData:
    """Return a three-cell synthetic image with an optional middle obstacle."""
    image = pv.ImageData(dimensions=(4, 2, 2), spacing=(spacing, 1, 1))
    image.cell_data["obstacle"] = np.array([0, int(occupied), 0], dtype=float)
    return image


def test_empty_map_has_no_sampled_collisions() -> None:
    result = dense_vtk_check([(0.1, 0.5, 0.5), (2.9, 0.5, 0.5)], make_image())
    assert result["occupied_samples"] == 0
    assert result["interior_occupied_samples"] == 0
    assert result["outside_samples"] == 0
    assert result["queried_points"] >= 141


def test_vtk_hit_reports_interior_penetration_and_actual_cell_id() -> None:
    result = dense_vtk_check([(0.1, 0.5, 0.5), (2.9, 0.5, 0.5)], make_image(True))
    assert result["collision_segment_count"] == 1
    assert result["first_collision_cell_id"] == 1
    assert result["interior_occupied_samples"] > 0
    assert result["first_interior_cell_id"] == 1
    assert result["first_interior_face_distance"] > 0
    assert result["first_interior_min_fraction"] > 0
    point = result["first_interior_point"]
    assert 1 < point[0] < 2


def test_sampling_narrow_obstacle_with_explicitly_fine_spacing() -> None:
    result = dense_vtk_check(
        [(0.001, 0.5, 0.5), (0.029, 0.5, 0.5)],
        make_image(True, spacing=0.01),
        max_spacing=0.001,
    )
    assert result["interior_occupied_samples"] > 0
    assert result["first_interior_cell_id"] == 1


def test_endpoints_and_zero_length_are_queried() -> None:
    result = dense_vtk_check([(1.5, 0.5, 0.5), (1.5, 0.5, 0.5)], make_image(True))
    assert result["queried_points"] == 2
    assert result["occupied_samples"] == 2
    assert result["first_interior_point"] == [1.5, 0.5, 0.5]


def test_outside_samples_are_reported() -> None:
    result = dense_vtk_check([(-0.1, 0.5, 0.5), (0.5, 0.5, 0.5)], make_image())
    assert result["outside_samples"] > 0


@pytest.mark.parametrize("spacing", [0, -1, np.nan, np.inf])
def test_invalid_sample_spacing_is_rejected(spacing: float) -> None:
    with pytest.raises(ValueError, match="spacing"):
        dense_vtk_check([(0.1, 0.5, 0.5), (2.9, 0.5, 0.5)], make_image(), spacing)


def test_boundary_hit_is_not_counted_as_interior() -> None:
    result = dense_vtk_check([(1, 0, 0.5), (2, 0, 0.5)], make_image(True))
    assert result["interior_occupied_samples"] == 0
