"""Scientific figures from all saved conditions, without new searches or simulations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from ..stage5a.analysis import write_csv
from ..stage6c.common import read_json
from .analysis import d1_sources
from .common import PUBLIC, load_record, save_json
from .maps import build_scenarios

COLORS = {"A": "#303030", "B": "#0072b2", "C": "#a020a0", "D": "#009e73"}


def plot_pairs(source: Path, previous: Path, local: Path, output: Path) -> None:
    """Show all21 source paths and every saved execution version."""
    fig = plt.figure(figsize=(13.5, 18))
    for index, data in enumerate(d1_sources(source, previous, local)):
        ax = fig.add_subplot(7, 3, index + 1, projection="3d")
        for version, trace in data["traces"].items():
            points = np.asarray(
                [data["case"].initial.position] + [r["position"] for r in trace]
            )
            ax.plot(
                *points.T,
                color=COLORS[version],
                lw=0.8,
                ls="--" if version in ("B", "C") else "-",
            )
        ax.set_title(data["job"], fontsize=7, pad=1)
        ax.tick_params(labelsize=5, pad=0)
        ax.set(xlabel="x (m)", ylabel="y (m)", zlabel="z (m)")
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.label.set_size(5)
        ax.view_init(elev=25, azim=-65)
    fig.suptitle(
        "All21 fixed source paths: four saved LOS versions", fontsize=13, y=0.995
    )
    fig.legend(
        [
            Line2D([], [], color=COLORS[v], ls="--" if v in ("B", "C") else "-")
            for v in COLORS
        ],
        [
            "A: archived dense",
            "B: same geometry, midpoints",
            "C: same A points, arc trigger",
            "D: archived tail chord",
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, 0.977),
        ncol=2,
        fontsize=9,
    )
    fig.subplots_adjust(top=0.92, bottom=0.04, hspace=0.30, wspace=0.08)
    fig.text(
        0.04,
        0.014,
        "All outcomes included. Panel scales vary; "
        "3D projections do not certify safety. Units: metres.",
        fontsize=9,
    )
    fig.savefig(output / "d1_all21_trajectories.png", dpi=150)
    plt.close(fig)


def plot_maps(local: Path, diagnostic: Path, output: Path) -> None:
    """Show the six fixed voxel recipes and their actual acceptance status."""
    fig = plt.figure(figsize=(14, 9))
    for index, case in enumerate(build_scenarios()):
        ax = fig.add_subplot(2, 3, index + 1)
        values = case.scene.grid.occupancy
        terrain = case.scene.specification["family"] == "terrain_climb"
        axes = (0, 2) if terrain else (0, 1)
        sliced = (
            values[:, round(case.initial.position[1] / 0.5), :]
            if terrain
            else values[:, :, round(case.initial.position[2] / 0.5)]
        )
        height = 28 if terrain else 44
        ax.imshow(
            sliced.T,
            origin="lower",
            extent=(0, 56, 0, height),
            cmap="Greys",
            vmin=0,
            vmax=1,
            alpha=0.55,
            interpolation="nearest",
        )
        if terrain:
            ax.axhspan(18, 28, color="#cc79a7", alpha=0.2)
        path = local / "witnesses" / case.id / "independent.json.gz"
        trace = None
        if path.exists():
            trace, status, color = (
                load_record(path)["trace"],
                "SI + independent witness PASS",
                "#0072b2",
            )
        elif case.id == "terrain_1":
            trace = load_record(diagnostic / "model_witness_diagnostic.json.gz")[
                "trace"
            ]
            status, color = "SI FAILED; orange = Python model diagnostic", "#d55e00"
        else:
            status, color = "NOT RUN after mandatory stop", "#333333"
        if trace:
            points = np.asarray(
                [case.initial.position] + [r["position"] for r in trace]
            )
            ax.plot(points[:, axes[0]], points[:, axes[1]], color=color, lw=2)
        ax.scatter(
            case.initial.position[axes[0]],
            case.initial.position[axes[1]],
            color="black",
            marker="o",
            s=15,
        )
        ax.scatter(
            case.scene.goal[axes[0]],
            case.scene.goal[axes[1]],
            color="black",
            marker="*",
            s=40,
        )
        ax.set(
            xlim=(0, 56),
            ylim=(0, height),
            xlabel="x (m)",
            ylabel="z (m)" if terrain else "y (m)",
        )
        plane = "XZ at y=22m" if terrain else "XY at z=10m"
        ax.set_title(case.id + " (" + plane + ")\n" + status, fontsize=8)
        ax.tick_params(labelsize=7)
    fig.suptitle(
        "Six preregistered obstacle development maps; ZERO planning searches",
        fontsize=13,
    )
    fig.subplots_adjust(top=0.90, bottom=0.09, hspace=0.30, wspace=0.28)
    fig.text(
        0.04,
        0.025,
        "Grey: actual occupied slice, not full3D certification. Black: start/goal. "
        "Pink: mission ceiling.\nOnly four witnesses passed both engines; "
        "terrain_1 orange is a Python model diagnostic, not an OMPL success.",
        fontsize=9,
    )
    fig.savefig(output / "d2_maps_and_witness_status.png", dpi=150)
    plt.close(fig)


def plot_failure(diagnostic: Path, output: Path) -> None:
    """Separate the macroscopic pitch path from its numerical predicate conflict."""
    failure = read_json(output / "model_mapping_failure.json")
    trace = load_record(diagnostic / "model_witness_diagnostic.json.gz")["trace"]
    subset = [r for r in trace if r["time_s"] <= 9.2]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].plot(
        [0] + [r["time_s"] for r in subset],
        [0] + [np.degrees(r["pitch_rad"]) for r in subset],
        color="#0072b2",
    )
    axes[0].axhline(20, color="black", ls="--", label="Frozen nominal20 degree bound")
    axes[0].scatter(
        [9],
        [20],
        color="#d55e00",
        s=35,
        zorder=3,
        label="First SI rejection (candidate)",
    )
    axes[0].set(
        xlabel="Simulation time (s)",
        ylabel="Pitch (degrees)",
        title="Failed supplied-control witness",
    )
    axes[0].legend(fontsize=8, loc="upper left")
    heights = [
        failure["machine_epsilon"],
        failure["candidate_pitch_minus_limit_rad"],
        failure["model_pitch_tolerance_rad"],
    ]
    axes[1].bar(
        ["OMPL epsilon", "Actual excess", "Frozen model tolerance"],
        heights,
        color=["#777777", "#d55e00", "#0072b2"],
    )
    axes[1].set(
        yscale="log",
        ylabel="Radians (log scale)",
        title="Position/yaw/continuous geometry pass",
    )
    axes[1].tick_params(axis="x", labelsize=8)
    for index, value in enumerate(heights):
        axes[1].text(index, value * 1.3, f"{value:.3e}", ha="center", fontsize=8)
    axes[1].set_ylim(1e-16, 1e-11)
    fig.suptitle("Model/SI pitch predicates disagree: scientific admission BLOCKED")
    fig.tight_layout(rect=(0, 0.06, 1, 0.92))
    fig.text(
        0.03,
        0.02,
        "Diagnostic only: no model correction, no relaxed safety, no search. "
        "Candidate is not an accepted OMPL state.",
        fontsize=8,
    )
    fig.savefig(output / "pitch_mapping_failure.png", dpi=160)
    plt.close(fig)


def main() -> None:
    """Create three necessary figures from existing numeric records only."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "previous-root", "local-root", "diagnostic-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    plot_pairs(args.source_root, args.previous_root, args.local_root, args.output)
    plot_maps(args.local_root, args.diagnostic_root, args.output)
    plot_failure(args.diagnostic_root, args.output)
    names = [
        "d1_all21_trajectories.png",
        "d2_maps_and_witness_status.png",
        "pitch_mapping_failure.png",
    ]
    write_csv(
        args.output / "figure_manifest.csv",
        [
            {"file": name, "source": "saved numeric records", "new_searches": 0}
            for name in names
        ],
    )
    save_json(
        args.output / "figure_qa.json",
        {"status": "pending actual visual inspection", "files": names},
    )
    print(json.dumps({"figures": names, "new_searches": 0, "new_simulations": 0}))


if __name__ == "__main__":
    main()
