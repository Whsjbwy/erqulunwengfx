"""Draw fixed-seed scientific figures from actual diagnostic evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from ..scenarios import load_scenario


def plot_incumbents(rows: list[dict], output: Path) -> None:
    """Show first solutions and later improvements without fabricated history."""
    selected = [r for r in rows if r["scene"] == "S3" and r["phase"] == "s3"]
    if selected:
        figure, axis = plt.subplots(figsize=(9, 5), layout="constrained")
        for row in selected:
            history = row.get("incumbent_history", [])
            if history:
                axis.step(
                    [x["time_s"] for x in history] + [row["search_seconds"]],
                    [x["length"] for x in history] + [history[-1]["length"]],
                    where="post",
                    label=f"{row['method']} seed{row['seed']}",
                    alpha=0.75,
                )
        axis.set(
            xlabel="Actual observed search time (s)",
            ylabel="Strict valid incumbent length (map units)",
            title="S3: first solution and subsequent strict improvements",
        )
        axis.legend(fontsize=7, ncol=2)
        figure.savefig(output / "S3_incumbent_history.png", dpi=130)
        plt.close(figure)


def plot_sensitivity(summaries: list[dict], output: Path) -> None:
    """Plot each single factor independently on the fixed development cases."""
    for phase in ("capacity", "size"):
        relevant = [r for r in summaries if r["phase"] == phase]
        if not relevant:
            continue
        factor = "grid_capacity" if phase == "capacity" else "grid_side_length"
        figure, axis = plt.subplots(figsize=(8, 4), layout="constrained")
        for scene in ("S1", "S2", "S3"):
            data = sorted(
                [r for r in relevant if r["scene"] == scene],
                key=lambda r: json.loads(r["parameters"])[factor],
            )
            axis.plot(
                [json.loads(r["parameters"])[factor] for r in data],
                [r["valid_by_budget"] / r["runs"] for r in data],
                "o-",
                label=scene,
            )
        axis.set(
            xlabel=factor,
            ylabel="At least one strictly valid solution by budget",
            ylim=(-0.05, 1.05),
            title=f"Single-factor {phase}; predeclared seeds 0,1,2",
        )
        axis.legend()
        figure.savefig(output / f"{phase}_sensitivity.png", dpi=130)
        plt.close(figure)


def plot_paths(evidence: list[dict], root: Path, output: Path) -> None:
    """Draw actual seed-zero results and expanded nodes on failed searches."""
    # Fixed seed0 baseline path illustrations, never replace failure with witness.
    for scene_id in ("S1", "S2", "S3", "H1", "H2"):
        chosen = [
            item
            for item in evidence
            if item["job"]["scene"] == scene_id
            and item["job"]["seed"] == 0
            and not item["job"]["stop_first"]
            and item["job"]["measurement"] == "observed"
            and item["job"]["parameters"]
            in ({"grid_capacity": 1, "grid_side_length": 5}, {})
            and item["job"]["method"] in ("safety_reference", "rrt_connect")
        ]
        if not chosen:
            continue
        scenario = load_scenario(Path(chosen[0]["job"]["map_config"]), scene_id)
        figure = plt.figure(figsize=(10, 4), layout="constrained")
        voxels = np.argwhere(scenario.grid.occupancy)
        voxels = voxels[:: max(1, math.ceil(len(voxels) / 1500))]
        coords = (
            np.asarray(scenario.grid.origin) + (voxels + 0.5) * scenario.grid.spacing
        )
        for index, method in enumerate(("safety_reference", "rrt_connect")):
            axis = figure.add_subplot(1, 2, index + 1, projection="3d")
            matches = [item for item in chosen if item["job"]["method"] == method]
            item = matches[0] if matches else None
            if len(coords):
                axis.scatter(*coords.T, s=2, alpha=0.3, color="slategray")
            axis.scatter(*scenario.start, color="blue", s=25)
            axis.scatter(*scenario.goal, color="black", marker="*")
            path = item.get("result", {}).get("raw_path") if item else None
            if path:
                axis.plot(
                    *np.asarray(path).T,
                    color="green" if item["row"]["strict_valid"] else "red",
                )
            elif item:
                event_file = root / item["job"]["job_id"] / "events.jsonl"
                if event_file.exists():
                    expanded = [
                        event["point"]
                        for line in event_file.read_text(encoding="utf-8").splitlines()
                        if (event := json.loads(line))["event"] == "expanded"
                    ]
                    if expanded:
                        axis.scatter(
                            *np.asarray(expanded).T,
                            s=8,
                            color="darkorange",
                            label="Actual expanded nodes; no path",
                        )
                        axis.legend(fontsize=6)
            axis.set_title(
                f"{scene_id} / {method}\n"
                f"{item['row']['status'] if item else 'not run'} / seed0",
                fontsize=9,
            )
            for setter, low, high in zip(
                (axis.set_xlim, axis.set_ylim, axis.set_zlim),
                scenario.grid.bounds[::2],
                scenario.grid.bounds[1::2],
                strict=True,
            ):
                setter(low, high)
            axis.set(xlabel="x", ylabel="y", zlabel="z (map)")
        figure.savefig(output / f"{scene_id}_seed0_paths.png", dpi=120)
        plt.close(figure)
