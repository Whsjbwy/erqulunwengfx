"""Small, explicit metrics for the author's zero-radius polyline outputs."""

from __future__ import annotations

import logging
import os
import platform
from importlib import metadata
from typing import Any

import numpy as np
from numpy.typing import ArrayLike

LOGGER = logging.getLogger(__name__)


def path_length(points: ArrayLike) -> float:
    """Return Euclidean polyline length in map units; reject invalid coordinates."""
    vertices = np.asarray(points, dtype=float)
    if vertices.ndim != 2 or vertices.shape[1] != 3:
        raise ValueError("A path must have shape (N, 3).")
    if not np.isfinite(vertices).all():
        raise ValueError("Path coordinates must be finite.")
    return float(np.linalg.norm(np.diff(vertices, axis=0), axis=1).sum())


def endpoints_match(points: ArrayLike, start: Any, goal: Any) -> bool:
    """Require the stated start and goal at either orientation, within 1e-6 units."""
    vertices = np.asarray(points, dtype=float)
    endpoints = np.asarray([start, goal], dtype=float)
    if (
        vertices.ndim != 2
        or vertices.shape[1:] != (3,)
        or len(vertices) < 2
        or endpoints.shape != (2, 3)
        or not np.isfinite(vertices).all()
        or not np.isfinite(endpoints).all()
    ):
        return False
    actual = vertices[[0, -1]]
    return bool(
        np.allclose(actual, endpoints, atol=1e-6, rtol=0)
        or np.allclose(actual[::-1], endpoints, atol=1e-6, rtol=0)
    )


def environment_info() -> dict[str, Any]:
    """Return local software and CPU descriptions without private environment data."""
    versions = {}
    for name in (
        "numpy",
        "pyvista",
        "vtk",
        "opencv-python",
        "pillow",
        "pytest",
        "ruff",
    ):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not-installed"
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": processor_name(),
        "logical_cpu_count": os.cpu_count(),
        "packages": versions,
    }


def processor_name() -> str:
    """Read a CPU name, using Windows' read-only registry when platform is empty."""
    name = platform.processor().strip()
    if name or platform.system() != "Windows":
        return name
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            access=winreg.KEY_READ,
        ) as processor_key:
            value, _ = winreg.QueryValueEx(processor_key, "ProcessorNameString")
        return str(value).strip()
    except OSError as error:
        LOGGER.warning("Cannot read Windows CPU description: %s", error)
        return "unavailable"
