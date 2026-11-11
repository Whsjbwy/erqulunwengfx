"""Static scientific figures from fixed tasks and actual certified histories."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .maps import load_map

LABELS = {
    "A1": "A1: 30deg / 252 rays",
    "A2": "A2: 45deg / 252 rays",
    "A3": "A3: 30deg / 360 rays",
    "A4": "A4: 45deg / 360 rays",
    "rrt_first": "RRT-Connect first",
    "rrt_restart": "RRT-Connect restart",
}


def plot_anytime(summaries: list[dict], output: Path) -> None:
    """Show coverage beside paired conditional gain and its joint denominator."""
    if not summaries:
        return
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    for comparison, side, method in (
        ("A2_vs_A1", "right", "A1"),
        ("A2_vs_A1", "left", "A2"),
        ("A4_vs_A3", "right", "A3"),
        ("A4_vs_A3", "left", "A4"),
        ("rrt_restart_vs_rrt_first", "right", "rrt_first"),
        ("rrt_restart_vs_rrt_first", "left", "rrt_restart"),
    ):
        rows = sorted(
            [r for r in summaries if r["comparison"] == comparison],
            key=lambda r: r["checkpoint_s"],
        )
        x = [r["checkpoint_s"] for r in rows]
        axes[0].plot(x, [r[side + "_rate"] for r in rows], "o-", label=LABELS[method])
    primary = [
        r
        for r in summaries
        if r["comparison"] == "A4_vs_rrt_restart" and r["length_gain"] is not None
    ]
    primary.sort(key=lambda r: r["checkpoint_s"])
    if primary:
        x = [r["checkpoint_s"] for r in primary]
        axes[1].plot(x, [100 * r["length_gain"] for r in primary], "o-", color="teal")
        axes[1].fill_between(
            x,
            [100 * r["length_gain_ci95"][0] for r in primary],
            [100 * r["length_gain_ci95"][1] for r in primary],
            alpha=0.2,
            color="teal",
        )
        for r in primary:
            axes[1].annotate(
                f"{r['joint_valid_pairs']}/{r['pairs']} pairs",
                (r["checkpoint_s"], 100 * r["length_gain"]),
                xytext=(0, 8),
                textcoords="offset points",
                fontsize=7,
                ha="center",
            )
    for axis in axes:
        axis.set_xscale("log")
        axis.set_xticks([0.1, 1, 5, 10, 30], ["0.1", "1", "5", "10", "30"])
        axis.set_xlabel("End-to-end budget (s), validation + shortcut included")
        axis.grid(alpha=0.2)
    axes[0].set(
        ylabel="Map-mean valid solution rate",
        ylim=(-0.03, 1.05),
        title="Held-out maps: 8 maps x 5 fixed seeds",
    )
    axes[0].legend(fontsize=7, loc="lower right")
    axes[1].axhline(0, color="gray", linewidth=0.8)
    axes[1].set(
        ylabel="A4 relative length reduction (%)",
        title="Common-valid tasks only; 95% hierarchical interval",
    )
    figure.savefig(output / "anytime_comparison.png", dpi=140)
    plt.close(figure)


def plot_angle_coverage(curves: list[dict], output: Path) -> None:
    """Keep every held-out family, including all-failure angle configurations."""
    groups = defaultdict(list)
    for row in curves:
        if (
            row["split"] == "holdout"
            and row["checkpoint_s"] == 30
            and row["method"].startswith("A")
        ):
            groups[(row["family"], row["method"], row["scene"])].append(
                int(row["valid"])
            )
    if not groups:
        return
    families = sorted({key[0] for key in groups})
    figure, axis = plt.subplots(figsize=(10, 4.5), layout="constrained")
    x = np.arange(len(families))
    for index, method in enumerate(("A1", "A2", "A3", "A4")):
        rates = []
        for family in families:
            maps = [
                np.mean(values)
                for (f, m, _), values in groups.items()
                if f == family and m == method
            ]
            rates.append(float(np.mean(maps)) if maps else np.nan)
        axis.bar(x + (index - 1.5) * 0.19, rates, width=0.18, label=LABELS[method])
    axis.set_xticks(x, families)
    axis.set(
        ylabel="Map-mean valid solution rate by 30s",
        ylim=(0, 1.08),
        title="Angle controls: all registered held-out families",
    )
    axis.legend(fontsize=8, loc="upper left", ncol=2)
    figure.savefig(output / "angle_coverage.png", dpi=140)
    plt.close(figure)


def plot_fixed_tasks(
    evidence: list[dict], output: Path, protocol: dict, maps: dict
) -> None:
    """Draw preselected seed-zero outcomes; never substitute witness paths."""
    methods = ("A1", "A4", "rrt_first", "rrt_restart")
    for scene_id in protocol["figure_tasks"]:
        chosen = {
            e["row"]["method"]: e
            for e in evidence
            if e["row"]["scene"] == scene_id and e["row"]["seed"] == 0
        }
        if not chosen:
            continue
        scene = load_map(scene_id, maps)
        occupied = np.argwhere(scene.grid.occupancy)
        occupied = occupied[:: max(1, math.ceil(len(occupied) / 2000))]
        coords = np.asarray(scene.grid.origin) + (occupied + 0.5) * np.asarray(
            scene.grid.spacing
        )
        figure = plt.figure(figsize=(11, 8), layout="constrained")
        for index, method in enumerate(methods):
            axis = figure.add_subplot(2, 2, index + 1, projection="3d")
            if len(coords):
                axis.scatter(*coords.T, s=2, alpha=0.22, color="slategray")
            axis.scatter(*scene.start, color="blue", s=24)
            axis.scatter(*scene.goal, color="black", marker="*", s=35)
            item = chosen.get(method)
            if item and item["history"]:
                event = item["history"][-1]
                path = np.asarray(item["paths"][event["path_id"]])
                axis.plot(*path.T, color="green", linewidth=1.7)
                caption = (
                    f"valid; first {item['row']['first_valid_time_s']:.3f}s; "
                    f"L={event['length']:.3f}"
                )
            else:
                caption = "no valid path by 30s" if item else "not run"
            axis.set_title(f"{LABELS[method]}\n{caption}", fontsize=9)
            axis.set(xlabel="x", ylabel="y", zlabel="z (map units)")
            axis.set_box_aspect(scene.grid.shape)
            for setter, low, high in zip(
                (axis.set_xlim, axis.set_ylim, axis.set_zlim),
                scene.grid.bounds[::2],
                scene.grid.bounds[1::2],
                strict=True,
            ):
                setter(low, high)
        figure.suptitle(
            f"{scene_id} seed0 / certified outputs / display voxels decimated",
            fontsize=10,
        )
        figure.savefig(output / f"{scene_id}_seed0_paths.png", dpi=130)
        plt.close(figure)
        figure, axis = plt.subplots(figsize=(9, 4.5), layout="constrained")
        for method in protocol["methods"]:
            item = chosen.get(method)
            if not item:
                continue
            history = item["history"]
            if history:
                axis.step(
                    [h["time_s"] for h in history] + [30],
                    [h["length"] for h in history] + [history[-1]["length"]],
                    where="post",
                    label=LABELS[method],
                )
            else:
                axis.plot([], [], label=LABELS[method] + ": no valid path")
        axis.set(
            xlim=(0, 30),
            xlabel="Actual certificate-completion time (s)",
            ylabel="Best strictly valid length",
            title=f"{scene_id} seed0: actual Anytime improvement history",
        )
        axis.legend(fontsize=7)
        axis.grid(alpha=0.2)
        figure.savefig(output / f"{scene_id}_seed0_anytime.png", dpi=140)
        plt.close(figure)


def plot_results(
    evidence: list[dict],
    curves: list[dict],
    summaries: list[dict],
    output: Path,
    protocol: dict,
    maps: dict,
) -> None:
    """Render the frozen illustrations after data aggregation, outside planning."""
    plot_anytime(summaries, output)
    plot_angle_coverage(curves, output)
    plot_fixed_tasks(evidence, output, protocol, maps)
