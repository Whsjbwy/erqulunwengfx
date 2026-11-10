"""Corroborate path collisions by dense independent VTK cell queries.

Sampling can miss thin penetrations and face/edge/corner contact. These results
are supporting evidence, never a replacement for continuous strict validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyvista as pv
from numpy.typing import ArrayLike

LOGGER = logging.getLogger(__name__)


def dense_vtk_check(
    points: ArrayLike, image: pv.ImageData, max_spacing: float = 0.02
) -> dict[str, Any]:
    """Query endpoint-inclusive samples using VTK's containing-cell lookup.

    Coordinates and ``max_spacing`` use physical map units. Return query counts,
    collision evidence and penetration distances to voxel faces. Invalid paths,
    spacing or unsupported nonbinary/rotated image maps raise ``ValueError``.
    A negative VTK cell ID records an out-of-domain sample. Zero sampled hits
    cannot establish strict geometric validity.
    """
    path = np.asarray(points, dtype=float)
    if path.ndim != 2 or path.shape[1:] != (3,) or len(path) < 2:
        raise ValueError("Path must contain at least two coordinate triples")
    if not np.all(np.isfinite(path)):
        raise ValueError("Path coordinates must be finite")
    if not np.isfinite(max_spacing) or max_spacing <= 0:
        raise ValueError("Maximum sample spacing must be finite and positive")
    if not isinstance(image, pv.ImageData):
        raise ValueError("Cross-check requires VTK ImageData")
    if not np.allclose(image.direction_matrix, np.eye(3), rtol=0, atol=1e-12):
        raise ValueError("Face-distance evidence requires an axis-aligned image")
    spacing = np.asarray(image.spacing, dtype=float)
    if not np.all(np.isfinite(spacing)) or np.any(spacing <= 0):
        raise ValueError("Image spacing must be finite and positive")
    if "obstacle" not in image.cell_data:
        raise ValueError("Missing cell_data['obstacle']")
    occupancy = np.asarray(image.cell_data["obstacle"])
    if occupancy.shape != (image.n_cells,) or not np.all(
        (occupancy == 0) | (occupancy == 1)
    ):
        raise ValueError("Obstacle field must contain one binary scalar per cell")
    result: dict[str, Any] = {
        "max_spacing": max_spacing,
        "queried_points": 0,
        "occupied_samples": 0,
        "interior_occupied_samples": 0,
        "outside_samples": 0,
        "collision_segment_count": 0,
        "first_collision_segment": None,
        "first_collision_cell_id": None,
        "first_collision_point": None,
        "first_collision_face_distance": None,
        "first_collision_min_fraction": None,
        "first_interior_segment": None,
        "first_interior_cell_id": None,
        "first_interior_point": None,
        "first_interior_face_distance": None,
        "first_interior_min_fraction": None,
    }
    for segment, (start, end) in enumerate(zip(path, path[1:], strict=False)):
        intervals = max(1, int(np.ceil(np.linalg.norm(end - start) / max_spacing)))
        samples = np.linspace(start, end, intervals + 1)
        # This is an actual VTK query. Scalar lookup uses the returned VTK cell
        # IDs directly, independently of the strict checker's array reshaping.
        cell_ids = np.asarray(image.find_containing_cell(samples), dtype=np.int64)
        inside = cell_ids >= 0
        occupied = np.zeros(len(samples), dtype=bool)
        occupied[inside] = occupancy[cell_ids[inside]] == 1
        fractions = np.remainder((samples - np.asarray(image.origin)) / spacing, 1.0)
        face_fractions = np.minimum(fractions, 1.0 - fractions)
        min_fractions = face_fractions.min(axis=1)
        face_distances = (face_fractions * spacing).min(axis=1)
        # Strictly positive distances distinguish interior penetration from a
        # containing-cell implementation's choice on a shared voxel boundary.
        interior = occupied & (min_fractions > 1e-8)
        result["queried_points"] += len(samples)
        result["occupied_samples"] += int(occupied.sum())
        result["interior_occupied_samples"] += int(interior.sum())
        result["outside_samples"] += int((~inside).sum())
        result["collision_segment_count"] += int(np.any(occupied))
        for prefix, mask in (("collision", occupied), ("interior", interior)):
            segment_key = f"first_{prefix}_segment"
            if result[segment_key] is not None or not np.any(mask):
                continue
            first = int(np.flatnonzero(mask)[0])
            result[segment_key] = segment
            result[f"first_{prefix}_cell_id"] = int(cell_ids[first])
            result[f"first_{prefix}_point"] = samples[first].tolist()
            result[f"first_{prefix}_face_distance"] = float(face_distances[first])
            result[f"first_{prefix}_min_fraction"] = float(min_fractions[first])
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Read the map once and corroborate each locally recorded path into CSV."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map-path", type=Path, required=True)
    parser.add_argument("--paths-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-spacing", type=float, default=0.02)
    args = parser.parse_args(argv)
    if not np.isfinite(args.max_spacing) or args.max_spacing <= 0:
        parser.error("--max-spacing must be finite and positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    image = pv.read(args.map_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = None
    with (
        args.paths_file.open(encoding="utf-8") as paths,
        args.output.open("w", encoding="utf-8", newline="") as output,
    ):
        for line_number, line in enumerate(paths, start=1):
            record = json.loads(line)
            for stage, key in (
                ("raw", "raw_path"),
                ("postprocessed", "postprocessed_path"),
            ):
                points = record.get(key)
                if points is None:
                    LOGGER.info(
                        "Skipping absent %s path at line %d", stage, line_number
                    )
                    continue
                result = dense_vtk_check(points, image, args.max_spacing)
                row = {
                    "mode": record["mode"],
                    "seed": record["seed"],
                    "stage": stage,
                    **result,
                }
                for key_name in ("first_collision_point", "first_interior_point"):
                    if row[key_name] is not None:
                        row[key_name] = json.dumps(row[key_name])
                if writer is None:
                    writer = csv.DictWriter(output, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                LOGGER.info(
                    "seed=%s stage=%s interior_hits=%d queries=%d",
                    record["seed"],
                    stage,
                    result["interior_occupied_samples"],
                    result["queried_points"],
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
