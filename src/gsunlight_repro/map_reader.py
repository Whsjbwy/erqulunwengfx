"""Read binary VTK cell occupancy in x-fastest (Fortran) order."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

Point = tuple[float, float, float]
Voxel = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class OccupancyMap:
    """Axis-aligned closed voxel boxes in map-coordinate units.

    ``occupancy[i, j, k]`` is true for an obstacle. ``origin`` is the
    minimum physical corner, not a cell center; spacing is strictly positive.
    Invalid dimensions or coordinates raise ``ValueError``.
    """

    occupancy: NDArray[np.bool_]
    origin: Point = (0.0, 0.0, 0.0)
    spacing: Point = (1.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        values = np.asarray(self.occupancy)
        if values.ndim != 3 or any(size == 0 for size in values.shape):
            raise ValueError("Occupancy must be a nonempty three-dimensional array")
        if values.dtype != np.bool_:
            raise ValueError("Occupancy array must have Boolean dtype")
        origin = np.asarray(self.origin, dtype=float)
        spacing = np.asarray(self.spacing, dtype=float)
        if origin.shape != (3,) or not np.all(np.isfinite(origin)):
            raise ValueError("Origin must contain three finite coordinates")
        if spacing.shape != (3,) or not np.all(np.isfinite(spacing)):
            raise ValueError("Spacing must contain three finite values")
        if np.any(spacing <= 0):
            raise ValueError("Spacing must be positive")
        object.__setattr__(self, "occupancy", values)
        object.__setattr__(self, "origin", tuple(float(v) for v in origin))
        object.__setattr__(self, "spacing", tuple(float(v) for v in spacing))

    @property
    def shape(self) -> Voxel:
        """Return the number of cells along the physical x, y and z axes."""
        return tuple(int(size) for size in self.occupancy.shape)

    @property
    def bounds(self) -> tuple[float, float, float, float, float, float]:
        """Return closed physical bounds as xmin, xmax, ymin, ymax, zmin, zmax."""
        return tuple(
            bound
            for index, count in enumerate(self.shape)
            for bound in (
                self.origin[index],
                self.origin[index] + count * self.spacing[index],
            )
        )


def read_map(path: Path) -> OccupancyMap:
    """Read an axis-aligned VTI with binary ``cell_data['obstacle']``.

    VTK cell ID is ``i + nx * (j + ny * k)``. Nonzero extents are translated
    into the physical minimum corner. Missing files raise ``FileNotFoundError``;
    unsupported geometry or nonbinary data raise ``ValueError``.
    """
    import pyvista as pv

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    image = pv.read(path)
    if not isinstance(image, pv.ImageData):
        raise ValueError("Map must be VTK ImageData")
    dimensions = tuple(int(size) for size in image.dimensions)
    if any(size < 2 for size in dimensions):
        raise ValueError("Map must contain three-dimensional cells")
    if not np.allclose(image.direction_matrix, np.eye(3), rtol=0, atol=1e-12):
        raise ValueError("Rotated image directions are unsupported")
    spacing = tuple(float(value) for value in image.spacing)
    if not np.all(np.isfinite(spacing)) or any(value <= 0 for value in spacing):
        raise ValueError("Map spacing must be finite and positive")
    if "obstacle" not in image.cell_data:
        raise ValueError("Map must have cell_data['obstacle']")
    values = np.asarray(image.cell_data["obstacle"])
    shape = tuple(size - 1 for size in dimensions)
    if values.ndim != 1 or values.size != int(np.prod(shape)):
        raise ValueError("Obstacle must have exactly one scalar per cell")
    if not np.all(np.isfinite(values)) or not np.all((values == 0) | (values == 1)):
        raise ValueError("Obstacle values must be binary zero or one")
    extent = image.extent
    origin = tuple(
        float(image.origin[axis] + extent[2 * axis] * spacing[axis])
        for axis in range(3)
    )
    occupancy = values.astype(bool).reshape(shape, order="F")
    return OccupancyMap(occupancy=occupancy, origin=origin, spacing=spacing)
