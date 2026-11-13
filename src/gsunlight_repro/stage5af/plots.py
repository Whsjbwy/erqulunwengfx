"""Fixed-case trajectory figures and denominator-aware scientific summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..stage5a.analysis import write_csv
from ..stage5ae.maps import generate as old_map
from ..stage5ae.plots import background
from ..stage5ae.runtime import experiment_lock
from ..stage5ar.plots import read_table
from .analysis import CONTROLLERS
from .maps import generate
from .storage import Records, public_output

COLORS = {"legacy": "#0072b2", "los_d2": "#d55e00", "los_terminal_v1": "#009e73"}
LABELS = {"legacy": "原控制", "los_d2": "冻结LOS", "los_terminal_v1": "终点修正LOS"}
METHODS = ("rrt_connect", "rrt_star", "informed_rrt_star")
STATUS = {
    "success": "成功",
    "tracking_error_limit": "误差超限",
    "swept_safety_reject": "扫掠拒绝",
    "margin_only_failure": "余量失守",
    "mission_band_reject": "任务带拒绝",
    "goal_not_reached": "未到达",
}


def draw_trace(ax, record: dict, start, controller: str) -> None:
    """Display actual full-resolution samples, marking the first rejected interval."""
    points = np.array([start, *[r["position"] for r in record["trace"]]])
    ax.plot(
        *points.T, color=COLORS[controller], label=LABELS[controller], linewidth=1.4
    )
    failure = record["summary"].get("first_failure_position")
    if failure is not None:
        ax.scatter(*failure, marker="x", color=COLORS[controller], s=35)


def independent_tracks(local: Path, old: Path, ar: Path, output: Path) -> list[dict]:
    """Use first registered map/seed0/body for every method, never best cases."""
    cfg = json.loads((local / "configuration.json").read_text(encoding="utf-8"))
    records = Records(local, old, ar)
    manifest = []
    for identity, label in (
        ("F_O1", "ordinary"),
        ("F_N1", "narrow"),
        ("F_B1", "nearbed"),
    ):
        spec = next(s for s in cfg["maps"]["maps"] if s["id"] == identity)
        scene = generate(spec, cfg["maps"])
        fig = plt.figure(figsize=(16, 14))
        for i, method in enumerate(METHODS):
            job = f"independent_{identity}_{method}_body_seed0"
            plan = json.loads(
                (local / "planning" / (job + ".json")).read_text(encoding="utf-8")
            )
            post = (
                json.loads(
                    (local / "planning" / (job + ".processing.json")).read_text(
                        encoding="utf-8"
                    )
                )
                if plan["raw"] is not None
                else None
            )
            for j, processing in enumerate(("raw", "shortcut")):
                ax = fig.add_subplot(3, 2, 2 * i + j + 1, projection="3d")
                background(ax, scene)
                if post is None:
                    ax.set_title(f"{method}/{processing}：无路径，未执行")
                    manifest.append(
                        {
                            "figure": label + "_tracks.png",
                            "job_id": job,
                            "processing": processing,
                            "was_run": False,
                        }
                    )
                    continue
                path = np.array(
                    plan["raw"] if processing == "raw" else post["shortcut"]
                )
                ax.plot(*path.T, "k--", linewidth=1.0, label="参考路径")
                statuses = []
                for controller in CONTROLLERS:
                    case = f"{job}--{processing}--{controller}"
                    record = records.read(case)
                    draw_trace(ax, record, scene.start, controller)
                    primary = record["summary"]["primary_class"]
                    statuses.append(
                        f"{LABELS[controller]}:{STATUS.get(primary, primary)}"
                    )
                    manifest.append(
                        {
                            "figure": label + "_tracks.png",
                            "case_id": case,
                            "job_id": job,
                            "processing": processing,
                            "was_run": True,
                            "primary_class": primary,
                        }
                    )
                ax.set_title(
                    f"{method}/{processing}\n" + "；".join(statuses), fontsize=9
                )
                ax.legend(fontsize=7, loc="upper left")
        fig.suptitle(
            f"{identity}，seed0，body；×为首次失败候选末位置；背景仅显示稀疏化"
        )
        fig.subplots_adjust(
            left=0.02, right=0.95, bottom=0.04, top=0.92, hspace=0.18, wspace=0.02
        )
        fig.savefig(output / (label + "_tracks.png"), dpi=140)
        plt.close(fig)
    return manifest


def terminal_examples(local: Path, old: Path, ar: Path, output: Path) -> list[dict]:
    """Fix first3 historical terminal-error IDs per O1/O3, independent of repair."""
    candidates = read_table(output / "terminal54_paired.csv")
    cfg = json.loads((old / "configuration.json").read_text(encoding="utf-8"))
    records = Records(local, old, ar)
    manifest = []
    fig = plt.figure(figsize=(16, 12))
    selected = [
        row
        for scene in ("E_O1", "E_O3")
        for row in sorted(
            (r for r in candidates if r["scene"] == scene), key=lambda r: r["case_id"]
        )[:3]
    ]
    for i, row in enumerate(selected):
        previous = records.old.read(row["case_id"])
        corrected = records.read(row["corrected_case_id"])
        meta = previous["meta"]
        job = meta["job_id"]
        spec = next(s for s in cfg["maps"]["maps"] if s["id"] == row["scene"])
        scene = old_map(spec, cfg["maps"])
        source = json.loads(
            (old / "planning" / (job + ".json")).read_text(encoding="utf-8")
        )
        path = (
            source["raw"]
            if meta["processing"] == "raw"
            else json.loads(
                (old / "planning" / (job + ".processing.json")).read_text(
                    encoding="utf-8"
                )
            )["shortcut"]
        )
        ax = fig.add_subplot(2, 3, i + 1, projection="3d")
        background(ax, scene)
        ax.plot(*np.array(path).T, "k--", linewidth=1.0, label="参考路径")
        draw_trace(ax, previous, scene.start, "los_d2")
        draw_trace(ax, corrected, scene.start, "los_terminal_v1")
        goal = scene.goal
        ax.set(
            xlim=(goal[0] - 9, goal[0] + 5),
            ylim=(goal[1] - 7, goal[1] + 7),
            zlim=(max(0, goal[2] - 5), goal[2] + 5),
        )
        ax.set_box_aspect((14, 14, 10))
        primary = corrected["summary"]["primary_class"]
        ax.set_title(
            f"{row['scene']} {meta['method']}\n"
            f"{meta['mode']}/{meta['processing']}/seed{meta['seed']}："
            f"修正{STATUS.get(primary, primary)}",
            fontsize=9,
        )
        ax.legend(fontsize=7)
        manifest.append(
            {
                "figure": "development_terminal.png",
                "old_case_id": row["case_id"],
                "corrected_case_id": row["corrected_case_id"],
                "selection": "first3 historical IDs per O1/O3",
                "corrected_class": primary,
            }
        )
    fig.suptitle("既有终端误差例的终点邻域；由旧失败ID固定取样，未按恢复结果挑选")
    fig.subplots_adjust(
        left=0.02, right=0.95, bottom=0.04, top=0.9, hspace=0.25, wspace=0.02
    )
    fig.savefig(output / "development_terminal.png", dpi=140)
    plt.close(fig)
    return manifest


def rates(output: Path) -> None:
    """Show three separate denominator rates and exploratory map intervals."""
    rows = read_table(output / "cluster_summary.csv")
    fig, axes = plt.subplots(2, 3, figsize=(17, 10), constrained_layout=True)
    for i, mode in enumerate(("body", "margin")):
        for j, metric in enumerate(("geometry", "conditional", "end_to_end")):
            ax = axes[i, j]
            variants = (
                [("raw", "legacy")]
                if metric == "geometry"
                else [(p, c) for p in ("raw", "shortcut") for c in CONTROLLERS]
            )
            for k, (processing, controller) in enumerate(variants):
                group = [
                    next(
                        r
                        for r in rows
                        if r["method"] == m
                        and r["mode"] == mode
                        and r["processing"] == processing
                        and r["controller"] == controller
                    )
                    for m in METHODS
                ]
                value = np.array(
                    [
                        float(r[metric + "_rate"]) if r[metric + "_rate"] else np.nan
                        for r in group
                    ]
                )
                low = np.array(
                    [
                        float(r[metric + "_ci95_low"])
                        if r[metric + "_ci95_low"]
                        else np.nan
                        for r in group
                    ]
                )
                high = np.array(
                    [
                        float(r[metric + "_ci95_high"])
                        if r[metric + "_ci95_high"]
                        else np.nan
                        for r in group
                    ]
                )
                x = np.arange(3) + (k - (len(variants) - 1) / 2) * 0.12
                ax.errorbar(
                    x,
                    value,
                    yerr=[np.maximum(0, value - low), np.maximum(0, high - value)],
                    marker="o" if processing == "raw" else "s",
                    linestyle="none",
                    capsize=2,
                    color=COLORS[controller],
                    label=f"{processing}/{LABELS[controller]}",
                )
            ax.set(
                title=f"{mode}/{metric}",
                xticks=range(3),
                xticklabels=("RRT-Connect", "RRT*", "Informed-RRT*"),
                ylim=(-0.04, 1.07),
                ylabel="成功率与地图聚类95%区间",
            )
            ax.grid(axis="y", alpha=0.25)
    axes[0, 1].legend(fontsize=7, loc="best")
    fig.suptitle("新12图：几何/已知几何可达；严格执行/合格路径；完整任务/已知可达")
    fig.savefig(
        output / "independent_rates.png", dpi=150, bbox_inches="tight", pad_inches=0.15
    )
    plt.close(fig)


def development(output: Path) -> None:
    """Keep all old maps; no-path maps are undefined, never zero execution rates."""
    rows = read_table(output / "development_map_summary.csv")
    scenes = sorted({r["scene"] for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), constrained_layout=True)
    for ax, processing in zip(axes, ("raw", "shortcut"), strict=True):
        for k, controller in enumerate(CONTROLLERS):
            group = [
                [
                    r
                    for r in rows
                    if r["scene"] == s
                    and r["processing"] == processing
                    and r["controller"] == controller
                ]
                for s in scenes
            ]
            successes = [sum(int(r["execution_successes"]) for r in g) for g in group]
            eligible = [sum(int(r["execution_eligible"]) for r in g) for g in group]
            value = [
                s / e if e else np.nan for s, e in zip(successes, eligible, strict=True)
            ]
            bars = ax.bar(
                np.arange(len(scenes)) + (k - 1) * 0.25,
                value,
                width=0.24,
                color=COLORS[controller],
                label=LABELS[controller],
            )
            ax.bar_label(
                bars,
                labels=[
                    f"{s}/{e}" if e else ""
                    for s, e in zip(successes, eligible, strict=True)
                ],
                rotation=90,
                fontsize=7,
                padding=3,
            )
            for i, count in enumerate(eligible):
                if not count:
                    ax.text(
                        i + (k - 1) * 0.25,
                        0.02,
                        "未运行",
                        ha="center",
                        rotation=90,
                        fontsize=7,
                    )
        ax.set(
            title=processing,
            xticks=range(len(scenes)),
            xticklabels=scenes,
            ylim=(0, 1.25),
            ylabel="条件严格执行成功率",
        )
        ax.tick_params(axis="x", rotation=60)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle("旧E_*仅开发回归集，固定306任务；原参考引用，修正新增612条件")
    fig.savefig(
        output / "development_controls.png",
        dpi=150,
        bbox_inches="tight",
        pad_inches=0.15,
    )
    plt.close(fig)


def main() -> None:
    """Render only completed real data while holding the evidence directory lock."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--ar-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5af"))
    args = parser.parse_args()
    if not (args.local_dir / "formal_completed.json").exists():
        raise ValueError("Complete all216 tasks before plotting")
    output = public_output(args.output)
    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 10,
        }
    )
    with experiment_lock(args.local_dir):
        development(output)
        rates(output)
        manifest = terminal_examples(
            args.local_dir, args.old_evidence, args.ar_evidence, output
        )
        manifest += independent_tracks(
            args.local_dir, args.old_evidence, args.ar_evidence, output
        )
        write_csv(output / "figure_manifest.csv", manifest)


if __name__ == "__main__":
    main()
