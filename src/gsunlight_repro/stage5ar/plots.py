"""Fixed-case scientific figures, including unsuccessful execution conditions."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from ..stage5a.analysis import read_evidence, write_csv
from ..stage5a.maps import body_radius, load_scene
from .analysis import read_replays, waterfall
from .evidence import protect_output, read_manifest

LABELS = {
    "baseline": "基准",
    "C1_first_heading": "首段航向",
    "C2_speed_0p5": "航速0.5",
    "C3_lookahead_1p5": "前视1.5",
    "C3_lookahead_5": "前视5",
}
COLORS = {
    "baseline": "#c0392b",
    "C1_first_heading": "#e69f00",
    "C2_speed_0p5": "#0072b2",
    "C3_lookahead_1p5": "#009e73",
    "C3_lookahead_5": "#8b5baf",
}


def read_table(path: Path) -> list[dict]:
    """Load compact public CSV for scientific plotting."""
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def plot_waterfall(rows: list[dict], output: Path) -> None:
    """Display nested denominators without treating precheck as execution."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)
    keys = (
        "certified_reachable",
        "geometric_path",
        "nominal_precheck",
        "actually_tracked",
        "nominal_arrival",
        "strict_completion",
    )
    labels = (
        "已知可达",
        "规划几何有效",
        "执行前通过",
        "实际跟踪",
        "名义完成",
        "严格完成",
    )
    methods = ("rrt_connect", "rrt_star", "informed_rrt_star")
    for mode, ax in zip(("point", "body", "margin"), axes, strict=True):
        for index, method in enumerate(methods):
            row = next(
                row for row in rows if row["mode"] == mode and row["method"] == method
            )
            values = [row[key] for key in keys]
            x = np.arange(len(keys)) + (index - 1) * 0.25
            bars = ax.bar(x, values, width=0.24, label=method.replace("_", "-"))
            ax.bar_label(bars, fontsize=7, padding=2)
        ax.set(
            xticks=range(len(keys)),
            xticklabels=labels,
            ylabel="任务数",
            title=f"{mode}：每方法登记30任务",
            ylim=(0, 36),
        )
        ax.tick_params(axis="x", rotation=35)
        ax.grid(axis="y", alpha=0.2)
    axes[0].legend(fontsize=8)
    fig.suptitle(
        "5A历史逐层分账：margin每方法排除5个已认证包络负例；几何拒绝不算跟踪失败"
    )
    fig.savefig(output / "failure_waterfall.png", dpi=150)
    plt.close(fig)


def sphere(ax, center: np.ndarray, radius: float) -> None:
    """Show the nominal envelope at the baseline's first rejected interval end."""
    u, v = np.meshgrid(np.linspace(0, 2 * np.pi, 16), np.linspace(0, np.pi, 10))
    ax.plot_wireframe(
        center[0] + radius * np.cos(u) * np.sin(v),
        center[1] + radius * np.sin(u) * np.sin(v),
        center[2] + radius * np.cos(v),
        color="crimson",
        alpha=0.35,
        rstride=2,
        cstride=2,
        linewidth=0.5,
    )


def plot_locations(
    items: list[dict],
    records: list[dict],
    config: dict,
    manifest: list[dict],
    output: Path,
) -> None:
    """Use earliest failing pilot task on each map; never select on improvement."""
    sources = {item["row"]["job_id"]: item for item in items}
    replays = {
        (item["summary"]["job_id"], item["summary"]["condition_id"]): item
        for item in records
        if item["summary"]["variant"] == "selected"
    }
    fig = plt.figure(figsize=(17, 11))
    panels = []
    for index, scene_id in enumerate(
        ("H5_O1", "H5_O2", "H5_B1", "H5_B2", "H5_N1", "H5_N2")
    ):
        candidates = [
            row for row in manifest if row["is_selected"] and row["scene"] == scene_id
        ]
        failed = [
            row for row in candidates if row["historical_execution_success"] == "False"
        ]
        chosen = min(
            failed or candidates,
            key=lambda row: (
                float(row["historical_termination_time_s"]),
                row["job_id"],
            ),
        )
        item = sources[chosen["job_id"]]
        path = np.array(item["paths"][chosen["path_id"]])
        scene = load_scene(scene_id, config["maps"])
        ax = fig.add_subplot(2, 3, index + 1, projection="3d")
        occupancy = np.argwhere(scene.grid.occupancy)
        shown = (
            occupancy[:: max(1, len(occupancy) // 4000)] + 0.5
        ) * scene.grid.spacing
        ax.scatter(*shown.T, color="#555b65", alpha=0.36, s=3)
        if scene.heights is not None:
            xx, yy = np.meshgrid(
                (np.arange(scene.grid.shape[0]) + 0.5) * scene.grid.spacing[0],
                (np.arange(scene.grid.shape[1]) + 0.5) * scene.grid.spacing[1],
                indexing="ij",
            )
            ax.plot_surface(
                xx, yy, scene.heights, cmap="terrain", alpha=0.25, rstride=5, cstride=5
            )
            ax.plot_wireframe(
                xx,
                yy,
                scene.heights + 6,
                color="steelblue",
                alpha=0.18,
                rstride=15,
                cstride=15,
                linewidth=0.5,
            )
        ax.plot(*path.T, "k--", lw=1.5, label="规划折线")
        for condition, color in COLORS.items():
            execution = replays[(chosen["job_id"], condition)]
            summary, trace = execution["summary"], execution["trace"]
            points = np.array([scene.start, *[step["position"] for step in trace]])
            ax.plot(*points.T, color=color, lw=1.4, label=LABELS[condition])
            failure_time = summary.get("first_failure_time_s")
            if failure_time is not None and trace:
                event = min(trace, key=lambda step: abs(step["time_s"] - failure_time))
                ax.scatter(*event["position"], color=color, marker="x", s=35)
                if condition == "baseline":
                    sphere(
                        ax, np.array(event["position"]), body_radius(config["protocol"])
                    )
        ax.scatter(*scene.start, color="navy", marker="o", s=25)
        ax.scatter(*scene.goal, color="black", marker="*", s=50)
        ax.set(
            xlabel="x / m",
            ylabel="y / m",
            zlabel="z向上 / m",
            xlim=(0, 50),
            ylim=(0, 36),
            zlim=(0, 24),
            title=(
                f"{scene_id} / {chosen['method']}\n"
                f"{chosen['mode']} / seed{chosen['seed']}"
            ),
        )
        ax.set_box_aspect((50, 36, 24))
        ax.view_init(24, -65)
        panels.append(
            {
                "scene": scene_id,
                "job_id": chosen["job_id"],
                "path_id": chosen["path_id"],
                "selection": "earliest_historical_failure_in_frozen_pilot_on_map",
            }
        )
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=6, bbox_to_anchor=(0.5, 0.015))
    fig.suptitle(
        "固定失败样本：折线与实际积分曲线；×为首次拒绝步末位置，非精确碰撞点；红球为名义包络\n近底蓝网格为任务带顶界，显示障碍已稀疏化，数值认证使用完整地图"
    )
    fig.subplots_adjust(
        top=0.87, bottom=0.09, left=0.02, right=0.95, hspace=0.2, wspace=0.12
    )
    fig.savefig(
        output / "failure_locations.png", dpi=160, bbox_inches="tight", pad_inches=0.3
    )
    plt.close(fig)
    write_csv(output / "figure_manifest.csv", panels)


def plot_sensitivity(output: Path) -> None:
    """Show all six maps and every preregistered condition, including losses."""
    rows = read_table(output / "condition_summary.csv")
    scenes = ["H5_O1", "H5_O2", "H5_B1", "H5_B2", "H5_N1", "H5_N2"]
    conditions = list(LABELS)
    matrix = np.zeros((len(scenes), len(conditions)))
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    for i, scene in enumerate(scenes):
        for j, condition in enumerate(conditions):
            row = next(
                row
                for row in rows
                if row["scene"] == scene
                and row["condition_id"] == condition
                and row["mode"] == "ALL"
            )
            success, n = (
                int(row["strict_successes"]),
                int(row["frozen_planning_outputs"]),
            )
            matrix[i, j] = success / n
            ax.text(j, i, f"{success}/{n}", ha="center", va="center", color="black")
    image = ax.imshow(matrix, cmap="YlGnBu", vmin=0, vmax=1, alpha=0.65)
    ax.set(
        xticks=range(5),
        xticklabels=list(LABELS.values()),
        yticks=range(6),
        yticklabels=scenes,
        title=(
            "同路径单因素对照：严格完成数 / 该图全部合格规划输出\n"
            "每图是聚类单元，种子及方法重复不增加地图数"
        ),
    )
    fig.colorbar(image, ax=ax, label="条件成功比例")
    fig.savefig(output / "sensitivity_by_map.png", dpi=150)
    plt.close(fig)


def plot_shortcuts(output: Path) -> None:
    """Keep every true same-source pair on geometry and outcome panels."""
    rows = read_table(output / "shortcut_pairs.csv")
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for ax, key, label in zip(
        axes[:2],
        ("length_m", "max_corner_turn_deg"),
        ("路径长度 / m", "最大折线转角 / °"),
        strict=True,
    ):
        x, y = (
            [float(row["raw_" + key]) for row in rows],
            [float(row["shortcut_" + key]) for row in rows],
        )
        colors = [
            "#009e73"
            if row["delta_execution_success"] == "1"
            else "#c0392b"
            if row["delta_execution_success"] == "-1"
            else "gray"
            for row in rows
        ]
        ax.scatter(x, y, c=colors, s=16, alpha=0.65)
        limits = (min(min(x), min(y)), max(max(x), max(y)))
        ax.plot(limits, limits, "k--", alpha=0.4)
        ax.set(xlabel="同源原始：" + label, ylabel="固定shortcut：" + label)
        ax.grid(alpha=0.2)
    counts = Counter(row["class_transition"] for row in rows)
    labels, values = zip(*counts.most_common(7), strict=True)
    axes[2].barh(range(len(values)), values, color="#587c9b")
    axes[2].set(
        yticks=range(len(values)),
        yticklabels=[label.replace(" -> ", "\n→ ") for label in labels],
        xlabel="配对数",
        title="最多7类结果转换（完整见CSV）",
    )
    axes[2].tick_params(axis="y", labelsize=7)
    fig.suptitle("真正同源后处理：绿=恢复严格完成，红=丢失完成，灰=完成标记不变")
    fig.savefig(output / "shortcut_paired.png", dpi=150)
    plt.close(fig)


def plot_narrow_detail(
    items: list[dict], records: list[dict], config: dict, output: Path
) -> None:
    """Explain the first lexical N2 baseline success lost under slower speed.

    This is explicitly an outcome-selected explanatory figure after the full
    matrix, never a sampling rule or tuning input for the experiments.
    """
    groups = {}
    for item in records:
        row = item["summary"]
        if row["scene"] == "H5_N2" and row["variant"] == "selected":
            groups.setdefault(row["job_id"], {})[row["condition_id"]] = item
    candidates = [
        job
        for job, group in groups.items()
        if group["baseline"]["summary"]["execution_success"]
        and not group["C2_speed_0p5"]["summary"]["execution_success"]
    ]
    if not candidates:
        return
    job = min(candidates)
    source = next(item for item in items if item["row"]["job_id"] == job)
    path = np.array(source["paths"][source["row"]["selected_path_id"]])
    radius = body_radius(config["protocol"])
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for ax, low, high, label in (
        (axes[0, 0], 23.0, 25.5, "y / m"),
        (axes[0, 1], 5.5, 8.0, "z / m"),
    ):
        ax.add_patch(Rectangle((25, low - 2), 2, 4.5, color="gray", alpha=0.3))
        ax.add_patch(Rectangle((25, low), 2, high - low, color="white"))
        ax.add_patch(
            Rectangle(
                (25, low + radius),
                2,
                high - low - 2 * radius,
                color="#009e73",
                alpha=0.18,
            )
        )
        ax.axvline(25, color="gray", ls=":")
        ax.axvline(27, color="gray", ls=":")
        ax.set(
            xlim=(22, 30), ylim=(low - 0.7, high + 0.7), xlabel="x / m", ylabel=label
        )
        ax.grid(alpha=0.2)
    axes[0, 0].plot(path[:, 0], path[:, 1], "k--", label="规划折线")
    axes[0, 1].plot(path[:, 0], path[:, 2], "k--")
    for condition, color in COLORS.items():
        item = groups[job][condition]
        trace = item["trace"]
        points = np.array([step["position"] for step in trace])
        mask = (points[:, 0] >= 22) & (points[:, 0] <= 30)
        axes[0, 0].plot(
            points[:, 0], points[:, 1], color=color, label=LABELS[condition]
        )
        axes[0, 1].plot(points[:, 0], points[:, 2], color=color)
        axes[1, 0].plot(
            points[mask, 0],
            np.array([step["physical_clearance_lower_bound_m"] for step in trace])[
                mask
            ],
            color=color,
        )
        axes[1, 1].plot(
            points[mask, 0],
            np.array([step["cross_track_m"] for step in trace])[mask],
            color=color,
        )
        if not item["summary"]["execution_success"]:
            for ax, coordinate in ((axes[0, 0], 1), (axes[0, 1], 2)):
                ax.scatter(
                    points[-1, 0], points[-1, coordinate], color=color, marker="x", s=50
                )
    axes[0, 0].set_title("开口俯视：绿色仅为壁内名义球中心允许区间")
    axes[0, 1].set_title("开口侧视：仍使用完整3D圆角扫掠认证")
    axes[1, 0].axhline(0, color="black", ls="--", lw=1)
    axes[1, 0].set(
        xlabel="x / m",
        ylabel="名义间隙保守下界 / m",
        title="小误差也可耗尽局部安全间隙",
        xlim=(23.8, 27.5),
        ylim=(-0.03, 0.15),
    )
    axes[1, 1].set(
        xlabel="x / m",
        ylabel="到折线的最近距离 / m",
        title="误差大小不能替代逐点安全认证",
        xlim=(22, 30),
    )
    axes[1, 0].grid(alpha=0.2)
    axes[1, 1].grid(alpha=0.2)
    axes[0, 0].legend(fontsize=8, ncol=3)
    fig.suptitle("事后解释图：N2基准成功、降速失败任务中按job_id取首条\n" + job)
    fig.savefig(output / "narrow_failure_detail.png", dpi=150)
    plt.close(fig)
    (output / "narrow_detail_case.json").write_text(
        json.dumps(
            {
                "job_id": job,
                "path_id": source["row"]["selected_path_id"],
                "selection": "posthoc_first_N2_baseline_success_C2_failure",
                "used_for_tuning": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    """Plot deterministic scientific artifacts after P0-P3 accounting passes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ar"))
    args = parser.parse_args()
    args.output = protect_output(args.output)
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    config = json.loads(
        (args.local_dir / "configuration.json").read_text(encoding="utf-8")
    )["historical"]
    items = read_evidence(args.history)
    rows = waterfall(items)
    write_csv(args.output / "failure_waterfall.csv", rows)
    plot_waterfall(rows, args.output)
    records = read_replays(args.local_dir)
    plot_locations(
        items,
        records,
        config,
        read_manifest(args.output / "sampling_manifest.csv"),
        args.output,
    )
    plot_sensitivity(args.output)
    plot_shortcuts(args.output)
    plot_narrow_detail(items, records, config, args.output)


if __name__ == "__main__":
    main()
