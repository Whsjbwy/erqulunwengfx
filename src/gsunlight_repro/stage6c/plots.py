"""Scientific PNGs showing every C1 pair and every C2 registered condition."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PIL import Image

from ..stage5a.analysis import write_csv
from ..stage6b.scenarios import analytic_scenarios
from .common import (
    PUBLIC,
    boolean,
    read_csv,
    read_json,
    saved_record,
    scenarios,
    write_json,
)

CONDITIONS = (
    "rrt_first",
    "sst_default_first",
    "sst_radius2_first",
    "sst_radius2_anytime",
)
LABELS = ("RRT first", "SST default first", "SST radius2 first", "SST radius2 anytime")
COLORS = ("#009e73", "#0072b2", "#e69f00", "#cc79a7")


def figure(size: tuple[float, float]) -> Figure:
    """Use the noninteractive Agg canvas without opening desktop windows."""
    result = Figure(figsize=size)
    FigureCanvasAgg(result)
    return result


def points(initial: tuple, trace: list[dict[str, Any]]) -> np.ndarray:
    """Use all saved samples without introducing new trajectory integration."""
    return np.asarray([initial] + [row["position"] for row in trace])


def contract_trajectories(source: Path, local: Path, output: Path) -> list[dict]:
    """Display all21 cases, so no success-based illustration selection occurs."""
    rows = read_csv(output / "c1_paired.csv")
    cases = scenarios()
    fig = figure((17.0, 23.0))
    manifest = []
    for index, row in enumerate(rows):
        case = cases[row["scenario"]]
        old = saved_record(source / "search" / row["job_id"])
        with gzip.open(
            local / "c1" / row["job_id"] / "record.json.gz", "rt", encoding="utf-8"
        ) as stream:
            new = json.load(stream)
        axis = fig.add_subplot(7, 3, index + 1, projection="3d")
        for trace, color, label in (
            (old["native_replay_trace"], "#0072b2", "native"),
            (old["los_trace"], "#e69f00", "dense LOS"),
            (new["los_trace"], "#cc79a7", "tail2 LOS"),
        ):
            values = points(case.initial.position, trace)
            axis.plot(*values.T, color=color, lw=0.8, alpha=0.85, label=label)
        occupied = np.argwhere(case.scene.grid.occupancy)
        if len(occupied):
            stride = max(1, int(np.ceil(len(occupied) / 700)))
            display = occupied[::stride]
            centers = (
                np.asarray(case.scene.grid.origin)
                + (display + 0.5) * case.scene.grid.spacing
            )
            axis.scatter(*centers.T, s=1, color="0.6", alpha=0.15)
        axis.scatter(*case.initial.position, color="black", s=9)
        axis.scatter(*case.scene.goal, color="red", marker="*", s=17)
        for trace, success, color in (
            (old["los_trace"], boolean(row["baseline_los_success"]), "#e69f00"),
            (new["los_trace"], boolean(row["adapted_los_success"]), "#cc79a7"),
        ):
            if trace and not success:
                axis.scatter(*trace[-1]["position"], color=color, marker="x", s=18)
        axis.set_title(row["job_id"] + "\n" + row["paired_outcome"], fontsize=8)
        axis.set_xlabel("x (m)", fontsize=7, labelpad=-3)
        axis.set_ylabel("y (m)", fontsize=7, labelpad=-3)
        axis.set_zlabel("z (m)", fontsize=7, labelpad=-3)
        axis.tick_params(labelsize=6, pad=0)
        axis.view_init(elev=25, azim=-60)
        manifest.append(
            {
                "figure": "c1_all_trajectories.png",
                "job_id": row["job_id"],
                "role": "all21_pairs_no_selection",
            }
        )
    handles, labels = fig.axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 0.976))
    fig.suptitle(
        "C1: all21 paired trajectories; native controls unchanged", fontsize=14, y=0.993
    )
    fig.text(
        0.5,
        0.012,
        "Gray: sampled occupied voxel centers for display. "
        "Cross: final failed candidate.\nPanel scales vary; "
        "continuous interval certificates establish safety.",
        ha="center",
        fontsize=9,
    )
    fig.subplots_adjust(
        left=0.02, right=0.97, bottom=0.05, top=0.93, hspace=0.48, wspace=0.10
    )
    fig.savefig(output / "c1_all_trajectories.png", dpi=135)
    fig.clear()
    return manifest


def outcomes(output: Path) -> list[dict]:
    """Show the full72-cell denominator and explicit missing-clock failure."""
    rows = read_csv(output / "planning_runs.csv")
    index = {(r["scenario"], r["condition"], int(r["native_seed"])): r for r in rows}
    cases = read_json(output / "c2_manifest.json")
    names = list(dict.fromkeys(r["scenario"] for r in cases))
    values = np.zeros((6, 12))
    text = {}
    palette = ["#d9d9d9", "#e69f00", "#0072b2", "#d55e00"]
    from matplotlib.colors import ListedColormap

    fig = figure((13, 6))
    axis = fig.subplots()
    for i, name in enumerate(names):
        for j, condition in enumerate(CONDITIONS):
            for seed in (1, 2, 3):
                row = index[name, condition, seed]
                column = j * 3 + seed - 1
                state = (
                    3
                    if not row["best_independent_certificate_finish_s"]
                    else 2
                    if boolean(row["los_strict_success"])
                    else 1
                    if boolean(row["model_feasible"])
                    else 0
                )
                values[i, column] = state
                text[i, column] = ("A", "M / fail", "M / S", "clock lost")[state]
    axis.imshow(values, cmap=ListedColormap(palette), vmin=0, vmax=3, aspect="auto")
    for (i, j), value in text.items():
        axis.text(
            j,
            i,
            value,
            ha="center",
            va="center",
            color="white" if values[i, j] >= 2 else "black",
            fontsize=8,
        )
    axis.set_yticks(range(6), names)
    axis.set_xticks(
        range(12),
        [f"{label}\nseed{s}" for label in LABELS for s in (1, 2, 3)],
        rotation=40,
        ha="right",
        fontsize=8,
    )
    axis.set_title("C2: all72 registered development searches", pad=16)
    fig.text(
        0.5,
        0.015,
        "A: approximate failure; M: strict native feasible; "
        "S: strict LOS success. Clock-loss pilot retained as failure.\n"
        "Six tasks share one empty map; these are development results.",
        ha="center",
        fontsize=9,
    )
    fig.subplots_adjust(bottom=0.27, left=0.09, right=0.99, top=0.88)
    fig.savefig(output / "c2_all_outcomes.png", dpi=150)
    fig.clear()
    return [
        {
            "figure": "c2_all_outcomes.png",
            "job_id": r["job_id"],
            "role": "all72_conditions",
        }
        for r in rows
    ]


def cost_curves(local: Path, output: Path) -> list[dict]:
    """Show all18 anytime groups and all first-solution comparator events."""
    names = [case.id for case in analytic_scenarios() if case.expected_reason == "ok"]
    fig = figure((14, 15))
    axes = fig.subplots(6, 3)
    manifest = []
    for i, case in enumerate(names):
        for j, seed in enumerate((1, 2, 3)):
            axis = axes[i, j]
            for condition, color, label in zip(CONDITIONS, COLORS, LABELS, strict=True):
                identity = f"{case}--{condition}--seed{seed}"
                raw = read_json(local / "search" / identity / "output.json")
                events = raw["improvement_events"]
                if events:
                    x = [r["native_certificate_finish_s"] for r in events]
                    y = [r["cost"] for r in events]
                    if condition.endswith("anytime"):
                        axis.step(
                            x + [max(8.0, x[-1])],
                            y + [y[-1]],
                            where="post",
                            color=color,
                            lw=1.5,
                            label=label,
                        )
                    else:
                        axis.plot(
                            x[0],
                            y[0],
                            marker="o",
                            ms=4,
                            color=color,
                            ls="none",
                            label=label,
                        )
                if condition.endswith("anytime") and not events:
                    axis.text(
                        0.5,
                        0.1,
                        "Anytime: approximate",
                        transform=axis.transAxes,
                        ha="center",
                        fontsize=8,
                    )
                manifest.append(
                    {
                        "figure": "c2_native_cost_curves.png",
                        "job_id": identity,
                        "role": "all18_task_seed_groups_with4_conditions",
                    }
                )
            if case == "straight" and seed == 1:
                axis.text(
                    0.5,
                    0.05,
                    "Anytime clock lost: native events only",
                    transform=axis.transAxes,
                    ha="center",
                    fontsize=7,
                    color="#d55e00",
                )
            axis.set_title(f"{case} / seed{seed}", fontsize=9)
            axis.set_xlim(0, 8.1)
            axis.grid(alpha=0.25)
            axis.tick_params(labelsize=8)
            if j == 0:
                axis.set_ylabel("Native arc cost (m)", fontsize=8)
            if i == 5:
                axis.set_xlabel("Native certificate event time (s)", fontsize=8)
    handles, labels = [], []
    for axis in axes.flat:
        h, lab = axis.get_legend_handles_labels()
        for a, b in zip(h, lab, strict=True):
            if b not in labels:
                handles.append(a)
                labels.append(b)
    fig.legend(handles, labels, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 0.975))
    fig.suptitle(
        "C2: all native first-solution and anytime cost events", fontsize=14, y=0.995
    )
    fig.text(
        0.5,
        0.012,
        "Event clocks exclude process/bridge/Python certificate costs. "
        "Strict end-to-end gates are in CSV.\nPlateaus are retained; "
        "the clock-loss case supplies no strict budget-qualified cost.",
        ha="center",
        fontsize=9,
    )
    fig.subplots_adjust(
        left=0.07, right=0.99, top=0.94, bottom=0.06, hspace=0.5, wspace=0.27
    )
    fig.savefig(output / "c2_native_cost_curves.png", dpi=140)
    fig.clear()
    return manifest


def main() -> None:
    """Render only complete audited records; visual QA is a separate real step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    if not read_json(args.output / "final_trace_audit.json")["passed"]:
        raise ValueError("Read-only final audit must pass before plotting")
    manifest = contract_trajectories(args.source_root, args.local_root, args.output)
    manifest += outcomes(args.output)
    manifest += cost_curves(args.local_root, args.output)
    write_csv(args.output / "figure_manifest.csv", manifest)
    files = []
    for name in dict.fromkeys(row["figure"] for row in manifest):
        with Image.open(args.output / name) as picture:
            files.append(
                {"file": name, "width": picture.width, "height": picture.height}
            )
    write_json(
        args.output / "figure_qa.json",
        {
            "visual_qa": "pending",
            "figures": files,
            "all_C1_pairs": 21,
            "all_C2_conditions": 72,
            "source": "Saved numeric records only",
            "new_searches": 0,
            "new_simulations": 0,
        },
    )
    print(json.dumps({"figures": files, "visual_qa": "pending"}))


if __name__ == "__main__":
    main()
