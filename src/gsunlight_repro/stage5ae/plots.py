"""Fixed-case scientific plots and correctly labelled horizontal references."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..map_reader import OccupancyMap
from ..metrics import path_length
from ..stage5a.analysis import write_csv
from ..stage5a.maps import Scene, body_radius
from ..stage5ar.plots import read_table, sphere
from ..stage5ar.runner import shortcut
from .curves import fillet
from .maps import generate
from .storage import Records, public_output

METHODS = ("rrt_connect", "rrt_star", "informed_rrt_star")
COLORS = {"legacy": "#0072b2", "los_d2": "#d55e00", "los_d4": "#009e73"}
LABELS = {"legacy": "旧控制", "los_d2": "LOS Δ=2", "los_d4": "LOS Δ=4"}


def development(output: Path) -> None:
    """Show every old map and both recovered and lost paired outcomes."""
    rows = read_table(output / "development_map_summary.csv")
    maps = sorted({row["scene"] for row in rows})
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), constrained_layout=True)
    for ax, processing in zip(axes, ("selected", "raw", "shortcut"), strict=True):
        controllers = (
            ("legacy", "los_d2", "los_d4")
            if processing == "selected"
            else ("legacy", "los_d2")
        )
        for index, controller in enumerate(controllers):
            group = [
                next(
                    row
                    for row in rows
                    if row["scene"] == scene
                    and row["processing"] == processing
                    and row["controller"] == controller
                )
                for scene in maps
            ]
            x = np.arange(len(maps)) + (index - (len(controllers) - 1) / 2) * 0.24
            values = [int(row["strict_successes"]) / int(row["paths"]) for row in group]
            bars = ax.bar(
                x,
                values,
                width=0.23,
                color=COLORS[controller],
                label=LABELS[controller],
            )
            ax.bar_label(
                bars,
                labels=[f"{row['strict_successes']}/{row['paths']}" for row in group],
                fontsize=7,
                rotation=90,
                padding=3,
            )
        ax.set(
            title=processing,
            xticks=range(len(maps)),
            xticklabels=maps,
            ylim=(0, 1.2),
            ylabel="条件严格执行成功率",
        )
        ax.tick_params(axis="x", rotation=45)
        ax.grid(axis="y", alpha=0.2)
        ax.legend(fontsize=8)
    fig.suptitle("旧6图仅作开发诊断；三种控制器参数选择仅使用 selected 路径")
    fig.savefig(output / "development_controls.png", dpi=150)
    plt.close(fig)


def rates(output: Path) -> None:
    """Plot three distinct denominators and whole-map bootstrap intervals."""
    rows = read_table(output / "cluster_summary.csv")
    fig, axes = plt.subplots(2, 3, figsize=(16, 9), constrained_layout=True)
    for row_index, mode in enumerate(("body", "margin")):
        for column, metric in enumerate(("geometry", "conditional", "end_to_end")):
            ax = axes[row_index, column]
            for index, (processing, controller) in enumerate(
                (
                    ("raw", "legacy"),
                    ("raw", "los_d2"),
                    ("shortcut", "legacy"),
                    ("shortcut", "los_d2"),
                )
            ):
                group = [
                    next(
                        row
                        for row in rows
                        if row["mode"] == mode
                        and row["method"] == method
                        and row["processing"] == processing
                        and row["controller"] == controller
                    )
                    for method in METHODS
                ]
                x = np.arange(3) + (index - 1.5) * 0.18
                values = [
                    float(row[metric + "_ratio"]) if row[metric + "_ratio"] else np.nan
                    for row in group
                ]
                low = [
                    float(row[metric + "_ci95_low"])
                    if row[metric + "_ci95_low"]
                    else np.nan
                    for row in group
                ]
                high = [
                    float(row[metric + "_ci95_high"])
                    if row[metric + "_ci95_high"]
                    else np.nan
                    for row in group
                ]
                ax.errorbar(
                    x,
                    values,
                    yerr=[
                        np.maximum(0, np.array(values) - low),
                        np.maximum(0, np.array(high) - values),
                    ],
                    marker="o" if processing == "raw" else "s",
                    linestyle="none",
                    capsize=3,
                    color=COLORS[controller],
                    label=f"{processing}/{LABELS[controller]}",
                )
            ax.set(
                title=f"{mode} / {metric}",
                xticks=range(3),
                xticklabels=("RRT-Connect", "RRT*", "Informed-RRT*"),
                ylim=(-0.04, 1.08),
                ylabel="成功率与地图聚类95%区间",
            )
            ax.grid(axis="y", alpha=0.25)
    axes[0, 0].legend(fontsize=8, loc="lower left")
    fig.suptitle(
        "新12图：几何/已知可达；严格执行/合格路径；完整任务/已知可达（排除包络负例）"
    )
    fig.savefig(output / "independent_rates.png", dpi=150)
    plt.close(fig)


def background(ax, scene: Scene) -> None:
    """Subsample occupancy for display only; all certification uses full voxels."""
    occupied = np.argwhere(scene.grid.occupancy)
    shown = (
        occupied[:: max(1, math.ceil(len(occupied) / 3500))] + 0.5
    ) * scene.grid.spacing
    if len(shown):
        ax.scatter(*shown.T, color="#59626b", alpha=0.35, s=3)
    if scene.heights is not None:
        xx, yy = np.meshgrid(
            (np.arange(scene.grid.shape[0]) + 0.5) * scene.grid.spacing[0],
            (np.arange(scene.grid.shape[1]) + 0.5) * scene.grid.spacing[1],
            indexing="ij",
        )
        ax.plot_surface(
            xx, yy, scene.heights, cmap="terrain", alpha=0.3, rstride=6, cstride=6
        )
        ax.plot_wireframe(
            xx,
            yy,
            scene.heights + 6,
            color="#56b4e9",
            alpha=0.3,
            rstride=12,
            cstride=12,
            linewidth=0.4,
        )
    extent = np.array(scene.grid.shape) * scene.grid.spacing
    ax.set(
        xlim=(0, extent[0]),
        ylim=(0, extent[1]),
        zlim=(0, extent[2]),
        xlabel="x / m",
        ylabel="y / m",
        zlabel="z / m",
    )
    ax.set_box_aspect(extent)
    ax.view_init(elev=33, azim=-65)
    ax.scatter(*scene.start, color="green", marker="o", s=25)
    ax.scatter(*scene.goal, color="black", marker="*", s=65)


def trajectories(local: Path, old: Path, output: Path) -> None:
    """Use predeclared first map, seed0, body for every algorithm, no selection."""
    configuration = json.loads(
        (local / "configuration.json").read_text(encoding="utf-8")
    )
    records = Records(local, old)
    manifest = []
    for scene_id, label in (
        ("E_O1", "ordinary"),
        ("E_N1", "narrow"),
        ("E_B1", "nearbed"),
    ):
        spec = next(
            spec for spec in configuration["maps"]["maps"] if spec["id"] == scene_id
        )
        scene = generate(spec, configuration["maps"])
        fig = plt.figure(figsize=(16, 14))
        for index, method in enumerate(METHODS):
            job = f"independent_{scene_id}_{method}_body_seed0"
            planning = json.loads(
                (local / "planning" / (job + ".json")).read_text(encoding="utf-8")
            )
            post = (
                json.loads(
                    (local / "planning" / (job + ".processing.json")).read_text(
                        encoding="utf-8"
                    )
                )
                if planning["raw"] is not None
                else None
            )
            for column, processing in enumerate(("raw", "shortcut")):
                ax = fig.add_subplot(3, 2, 2 * index + column + 1, projection="3d")
                background(ax, scene)
                if planning["raw"] is None:
                    ax.set_title(f"{method} / {processing}：无几何输出，未执行")
                    continue
                path = np.array(
                    planning["raw"] if processing == "raw" else post["shortcut"]
                )
                ax.plot(
                    *path.T,
                    color="black",
                    linestyle="--",
                    linewidth=1.1,
                    label="认证参考路径",
                )
                statuses = []
                for controller in ("legacy", "los_d2"):
                    case = f"{job}--{processing}--{controller}"
                    record = records.read(case)
                    summary = record["summary"]
                    positions = np.array(
                        [scene.start, *[step["position"] for step in record["trace"]]]
                    )
                    ax.plot(
                        *positions.T,
                        color=COLORS[controller],
                        linewidth=1.5,
                        label=LABELS[controller],
                    )
                    if not summary["execution_success"] and summary.get(
                        "first_failure_position"
                    ):
                        location = np.array(summary["first_failure_position"])
                        ax.scatter(
                            *location, color=COLORS[controller], marker="x", s=40
                        )
                        if controller == "legacy":
                            sphere(ax, location, body_radius(configuration["vehicle"]))
                    statuses.append(f"{LABELS[controller]}: {summary['primary_class']}")
                    manifest.append(
                        {
                            "figure": label + "_tracks.png",
                            "case_id": case,
                            "success": summary["execution_success"],
                            "reason": summary["primary_class"],
                        }
                    )
                ax.set_title(
                    f"{method} / {processing}\n" + "；".join(statuses), fontsize=9
                )
                ax.legend(fontsize=8, loc="upper left")
        fig.suptitle(
            f"{scene_id}，seed0，body；×为首个失败区间终点；点云仅显示稀疏化",
            fontsize=13,
        )
        fig.subplots_adjust(
            left=0.02, right=0.95, bottom=0.04, top=0.92, hspace=0.16, wspace=0.02
        )
        fig.savefig(output / (label + "_tracks.png"), dpi=140)
        plt.close(fig)
    write_csv(output / "figure_manifest.csv", manifest)


def horizontal(local: Path, output: Path, vehicle: dict) -> None:
    """Separate each input's metrics from shared curved-reference metadata."""
    with gzip.open(
        local / "horizontal_reference.json.gz", "rt", encoding="utf-8"
    ) as stream:
        records = json.load(stream)
    scene = Scene(
        {"family": "analytic"},
        OccupancyMap(np.zeros((70, 70, 30), dtype=bool)),
        None,
        (10.0, 10.0, 10.0),
        (45.0, 45.0, 10.0),
        None,
    )
    raw = [scene.start, (45.0, 10.0, 10.0), scene.goal]
    geometry = scene.geometry(body_radius(vehicle))
    shortened, _ = shortcut(raw, scene, body_radius(vehicle))
    curved = fillet(raw, geometry, 1 / math.radians(10))
    paths = {"raw": raw, "shortcut": shortened, "fillet": curved["display_points"]}
    rows = []
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    for ax, processing in zip(axes, ("raw", "shortcut", "fillet"), strict=True):
        path = np.array(paths[processing])
        ax.plot(*path[:, :2].T, "k--", label="输入参考路径")
        for record in (row for row in records if row["processing"] == processing):
            if record["curve_reference"]["length_m"] != curved["length_m"]:
                raise ValueError("Horizontal reference reconstruction changed")
            controller, summary = record["controller"], record["summary"]
            positions = np.array(
                [scene.start, *[step["position"] for step in record["trace"]]]
            )
            outcome = "成功" if summary["execution_success"] else "失败"
            ax.plot(
                *positions[:, :2].T,
                color=COLORS[controller],
                label=f"{LABELS[controller]}: {outcome}",
            )
            if not summary["execution_success"]:
                ax.scatter(
                    *positions[-1, :2], color=COLORS[controller], marker="x", s=40
                )
            enclosure = (
                curved["maximum_chord_enclosure_m"] if processing == "fillet" else 0.0
            )
            gap = min(
                geometry.clearance(a, b, mission=True) - enclosure
                for a, b in zip(path[:-1], path[1:], strict=True)
            )
            rows.append(
                {
                    "processing": processing,
                    "controller": controller,
                    **summary,
                    "input_path_length_m": curved["length_m"]
                    if processing == "fillet"
                    else path_length(path),
                    "input_max_pitch_deg": 0.0,
                    "input_max_curvature_m_inv": None
                    if processing == "raw"
                    else curved["max_curvature_m_inv"]
                    if processing == "fillet"
                    else 0.0,
                    "input_max_yaw_rate_rad_s_at_v1": None
                    if processing == "raw"
                    else curved["max_yaw_rate_rad_s_at_v1"]
                    if processing == "fillet"
                    else 0.0,
                    "input_continuous_geometry_valid": curved["valid"]
                    if processing == "fillet"
                    else geometry.path(path).valid,
                    "input_path_clearance_lower_bound_capped_m": gap,
                    "input_status": curved["status"]
                    if processing == "fillet"
                    else "certified_polyline",
                    "processing_cost_recorded": False,
                    **{
                        "curve_reference_" + key: value
                        for key, value in record["curve_reference"].items()
                    },
                }
            )
        ax.set(
            title=processing + "（仅水平参考）",
            xlabel="x / m",
            ylabel="y / m",
            xlim=(7, 52),
            ylim=(6, 49),
            aspect="equal",
        )
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)
    fig.suptitle(
        "同一固定急角：原路径失败，shortcut与标准圆弧参考成功；不代表通用三维能力"
    )
    fig.savefig(
        output / "horizontal_reference.png",
        dpi=150,
        bbox_inches="tight",
        pad_inches=0.15,
    )
    plt.close(fig)
    write_csv(output / "horizontal_reference.csv", rows)


def main() -> None:
    """Render real traces and derived statistics after the full matrix completes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ae"))
    args = parser.parse_args()
    if not (args.local_dir / "formal_completed.json").exists():
        raise ValueError("Do not plot incomplete independent records")
    output = public_output(args.output)
    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 10,
        }
    )
    vehicle = json.loads(
        (args.local_dir / "configuration.json").read_text(encoding="utf-8")
    )["vehicle"]
    development(output)
    rates(output)
    trajectories(args.local_dir, args.old_evidence, output)
    horizontal(args.local_dir, output, vehicle)


if __name__ == "__main__":
    main()
