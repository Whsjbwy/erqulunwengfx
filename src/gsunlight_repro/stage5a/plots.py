"""Fixed-task scientific figures from actual geometry and execution evidence."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .maps import body_radius, load_scene

LABELS = {
    "rrt_connect": "RRT-Connect restart",
    "rrt_star": "RRT*",
    "informed_rrt_star": "Informed-RRT*",
}
COLORS = {
    "rrt_connect": "#3366aa",
    "rrt_star": "#cc7722",
    "informed_rrt_star": "#228855",
}


def plot_coverage(evidence: list[dict], protocol: dict, output: Path) -> None:
    """Plot only held-out tasks, with model-unreachable cases kept separate."""
    held = [item for item in evidence if item["row"]["phase"] == "holdout"]
    if not held:
        return
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for mode, axis in zip(protocol["geometry_modes"], axes, strict=True):
        for method in protocol["methods"]:
            tasks = [
                item
                for item in held
                if item["row"]["method"] == method
                and item["row"]["geometry_mode"] == mode
                and item["row"]["reachability"].startswith("certified_reachable")
            ]
            if not tasks:
                continue
            rates = []
            for cutoff in protocol["checkpoints_s"]:
                per_map: dict[str, list[bool]] = defaultdict(list)
                for task in tasks:
                    per_map[task["row"]["scene"]].append(
                        any(event["time_s"] <= cutoff for event in task["history"])
                    )
                rates.append(mean(mean(values) for values in per_map.values()))
            axis.plot(
                protocol["checkpoints_s"],
                rates,
                "o-",
                color=COLORS[method],
                label=LABELS[method],
            )
        axis.set(
            xlabel="Global planning budget (s)",
            ylabel="Map-mean geometric coverage",
            title=mode + " / certified reachable envelope tasks",
            ylim=(-0.03, 1.03),
            xticks=protocol["checkpoints_s"],
        )
        axis.grid(alpha=0.2)
    axes[-1].legend(fontsize=9, loc="lower right")
    fig.suptitle("Planning Anytime: validation + shortcut charged; execution separate")
    fig.savefig(output / "planning_anytime.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for mode, axis in zip(protocol["geometry_modes"], axes, strict=True):
        for index, method in enumerate(protocol["methods"]):
            tasks = [
                item["row"]
                for item in held
                if item["row"]["method"] == method
                and item["row"]["geometry_mode"] == mode
                and item["row"]["reachability"].startswith("certified_reachable")
            ]
            if not tasks:
                continue
            rates = []
            for key in (
                "strict_geometry_valid",
                "nominal_body_valid",
                "execution_success",
            ):
                by_map: dict[str, list[bool]] = defaultdict(list)
                for row in tasks:
                    by_map[row["scene"]].append(row[key] is True)
                rates.append(mean(mean(values) for values in by_map.values()))
            axis.bar(
                np.arange(3) + (index - 1) * 0.24,
                rates,
                width=0.23,
                color=COLORS[method],
                label=LABELS[method],
            )
        axis.set(
            xticks=range(3),
            xticklabels=["planned scale", "nominal body", "execution"],
            ylabel="Map-mean task delivery rate",
            title=mode,
            ylim=(0, 1.08),
        )
        axis.grid(axis="y", alpha=0.2)
    axes[-1].legend(fontsize=9)
    fig.suptitle(
        "Separate stages; no-path tasks retained; model-unreachable cases excluded"
    )
    fig.savefig(output / "geometry_to_execution.png", dpi=150)
    plt.close(fig)


def plot_fixed_paths(
    evidence: list[dict], protocol: dict, maps: dict, output: Path
) -> None:
    """Use all preregistered figure tasks at seed0/body, including failures."""
    selected = {
        (item["row"]["scene"], item["row"]["method"]): item
        for item in evidence
        if item["row"]["phase"] == "holdout"
        and item["row"]["seed"] == protocol["figure_seed"]
        and item["row"]["geometry_mode"] == "body"
    }
    for scene_id in protocol["figures"]:
        if not any((scene_id, method) in selected for method in protocol["methods"]):
            continue
        scene = load_scene(scene_id, maps)
        fig = plt.figure(figsize=(15, 5.3), constrained_layout=True)
        occupancy = np.argwhere(scene.grid.occupancy)
        stride = max(1, len(occupancy) // 6000)
        shown = (occupancy[::stride] + 0.5) * scene.grid.spacing
        for index, method in enumerate(protocol["methods"]):
            axis = fig.add_subplot(1, 3, index + 1, projection="3d")
            if len(shown):
                axis.scatter(*shown.T, color="gray", alpha=0.12, s=1)
            if scene.heights is not None:
                xx, yy = np.meshgrid(
                    (np.arange(scene.grid.shape[0]) + 0.5) * scene.grid.spacing[0],
                    (np.arange(scene.grid.shape[1]) + 0.5) * scene.grid.spacing[1],
                    indexing="ij",
                )
                axis.plot_surface(
                    xx,
                    yy,
                    scene.heights,
                    cmap="terrain",
                    alpha=0.35,
                    rstride=4,
                    cstride=4,
                )
                axis.plot_wireframe(
                    xx,
                    yy,
                    scene.heights + 6,
                    color="steelblue",
                    alpha=0.1,
                    rstride=12,
                    cstride=12,
                )
            item = selected.get((scene_id, method))
            text = "not completed"
            if item:
                row = item["row"]
                path_id = row["selected_path_id"]
                if path_id is not None:
                    path = np.asarray(item["paths"][path_id])
                    axis.plot(*path.T, "g--", label="certified envelope path")
                    execution = item["executions"][str(path_id)]
                    if execution["trajectory"]:
                        trajectory = np.asarray(execution["trajectory"])
                        axis.plot(
                            *trajectory[:, 1:4].T,
                            color="tab:blue"
                            if execution["execution_success"]
                            else "crimson",
                            label="actual simulated track",
                        )
                        center = trajectory[-1, 1:4]
                        u, v = np.meshgrid(
                            np.linspace(0, 2 * np.pi, 20), np.linspace(0, np.pi, 12)
                        )
                        radius = body_radius(protocol)
                        axis.plot_surface(
                            center[0] + radius * np.cos(u) * np.sin(v),
                            center[1] + radius * np.sin(u) * np.sin(v),
                            center[2] + radius * np.cos(v),
                            color="tab:blue"
                            if execution["execution_success"]
                            else "crimson",
                            alpha=0.3,
                        )
                    text = (
                        f"L={row['best_length']:.2f}m; "
                        f"execute={execution['execution_success']}"
                    )
                    text += "\n" + execution["failure_reason"].replace(
                        "physical_sweep_rejected_physical_obstacle",
                        "physical swept body rejected",
                    )
                else:
                    text = "no geometric path / " + row["termination_reason"]
            axis.scatter(*scene.start, color="blue", s=25)
            axis.scatter(*scene.goal, color="black", marker="*", s=45)
            bounds = scene.grid.bounds
            axis.set(
                xlabel="x (m)",
                ylabel="y (m)",
                zlabel="z up (m)",
                xlim=bounds[:2],
                ylim=bounds[2:4],
                zlim=bounds[4:6],
                title=LABELS[method] + "\n" + text,
            )
            axis.view_init(elev=25, azim=-65)
            axis.set_box_aspect(np.array(scene.grid.shape) * scene.grid.spacing)
        fig.suptitle(
            scene_id + " / seed0 / body planning / display voxels and tracks decimated"
        )
        fig.savefig(output / (scene_id + "_body_seed0.png"), dpi=150)
        plt.close(fig)


def plot_results(evidence: list[dict], config: dict, output: Path) -> None:
    """Create deterministic scientific figures without picking successful seeds."""
    plot_coverage(evidence, config["protocol"], output)
    plot_fixed_paths(evidence, config["protocol"], config["maps"], output)
