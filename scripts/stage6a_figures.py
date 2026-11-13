"""Plot supplied-control traces and the scalar-curvature compatibility check."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, Rectangle

from gsunlight_repro.stage6a.feasibility import output_directory


def main() -> None:
    """Read the single local numeric record; never rerun acceptance for a plot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("results/stage6a/feasibility_witnesses.png")
    )
    args = parser.parse_args()
    with gzip.open(args.trace, "rt", encoding="utf-8") as stream:
        records = json.load(stream)
    positive = [r for r in records if r["summary"]["motion_witness_feasible"]]
    if len(positive) != 6:
        raise ValueError("Expected the six preregistered motion witnesses")
    figure, axes = plt.subplots(1, 3, figsize=(12, 4.8))
    figure.subplots_adjust(top=0.81, bottom=0.25, left=0.06, right=0.98, wspace=0.35)
    for record in positive:
        trace = record["trace"]
        points = np.asarray(
            [trace[0]["start_position"]] + [row["position"] for row in trace]
        )
        for axis, index in zip(axes[:2], (1, 2), strict=True):
            axis.plot(points[:, 0], points[:, index], label=record["spec"]["id"])
    for axis, label, title in zip(
        axes[:2],
        ("Y (m)", "Z (m)"),
        ("(a) Actual witness XY", "(b) Actual witness XZ"),
        strict=True,
    ):
        axis.set(xlabel="X (m)", ylabel=label, title=title)
        axis.grid(alpha=0.25)
    axes[0].legend(fontsize=8, loc="upper right")
    axis = axes[2]
    axis.add_patch(
        Circle((0, 0), 10, fill=False, linestyle="--", label="Scalar curvature bound")
    )
    axis.add_patch(
        Rectangle(
            (-10, -5),
            20,
            10,
            alpha=0.25,
            facecolor="tab:blue",
            label="Frozen separate-rate limits",
        )
    )
    axis.scatter([0], [8], color="tab:red", zorder=3)
    axis.annotate(
        "Invalid pitch rate",
        (0, 8),
        xytext=(-10.7, 11),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "color": "tab:red"},
    )
    axis.scatter([10], [5], color="tab:green", zorder=3)
    axis.annotate(
        "Allowed joint rates",
        (10, 5),
        xytext=(-10.5, -7),
        fontsize=8,
        arrowprops={"arrowstyle": "->", "color": "tab:green"},
    )
    axis.set(
        xlim=(-12, 12),
        ylim=(-12, 12),
        aspect="equal",
        xlabel="Yaw rate (deg/s)",
        ylabel="Pitch rate (deg/s)",
        title="(c) v=1 m/s, pitch=0",
    )
    axis.legend(fontsize=7, loc="lower center", bbox_to_anchor=(0.5, -0.33))
    figure.suptitle(
        "Stage6A: supplied-control acceptance, not planner performance",
        y=0.97,
        fontsize=13,
    )
    output_directory(args.output.parent)
    figure.savefig(args.output, dpi=160)
    plt.close(figure)
    print(json.dumps({"positive_traces": len(positive), "output": str(args.output)}))


if __name__ == "__main__":
    main()
