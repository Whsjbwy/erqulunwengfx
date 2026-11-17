"""Plot only the one saved new trace and archived comparison traces per task."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from ..stage5a.maps import read_config  # noqa: E402
from ..stage6d.common import load_record  # noqa: E402
from . import PUBLIC  # noqa: E402


def main() -> None:
    """Render six fixed pairs and two diagnostic control/gap comparisons."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    args = parser.parse_args()
    jobs = read_config("stage7b0_protocol.json")["jobs"]
    folder = PUBLIC / "figures"
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    fig = plt.figure(figsize=(12, 7.5), constrained_layout=True)
    for index, job in enumerate(jobs):
        old = load_record(args.raw_root / "search" / job / "independent_record.json.gz")
        new = load_record(args.local_root / job / "execution.json.gz")
        records.append((old, new))
        axis = fig.add_subplot(2, 3, index + 1, projection="3d")
        for trace, label, style in (
            (old["native_trace"], "Native (saved)", "--"),
            (old["los_trace"], "Frozen LOS (saved)", "-"),
            (new["trace"], "LTV-LQR (new)", ":"),
        ):
            positions = np.asarray(
                [trace[0]["start_position"]] + [r["position"] for r in trace]
            )
            axis.plot(*positions.T, linestyle=style, label=label, linewidth=1.6)
        title = job.replace("--", "\n").replace("sst_radius2_", "SST ")
        axis.set(title=title, xlabel="x [m]", ylabel="y [m]", zlabel="z [m]")
        axis.tick_params(labelsize=7)
        if index == 0:
            axis.legend(fontsize=7)
    fig.suptitle(
        "Fixed six nominal tasks: native/LTV overlap is expected; "
        "lines are not safety certificates"
    )
    fig.savefig(folder / "six_trajectories.png", dpi=160)
    plt.close(fig)
    fig, axes = plt.subplots(2, 2, figsize=(11, 6), constrained_layout=True)
    for column, index in enumerate((2, 3)):
        old, new = records[index]
        for trace, label, linestyle in (
            (old["native_trace"], "Native", "--"),
            (old["los_trace"], "Frozen LOS", "-"),
            (new["trace"], "LTV-LQR", ":"),
        ):
            t = [r["time_s"] for r in trace]
            axes[0, column].plot(
                t,
                [math.degrees(r["yaw_rate_rad_s"]) for r in trace],
                linestyle=linestyle,
                label=label,
            )
            gap = (
                [r["mission_clearance_lower_bound_m"] - 0.25 for r in trace]
                if label == "Frozen LOS"
                else [
                    r["minimum_required_gap_lower_bound_m"]
                    if label == "LTV-LQR"
                    else r["minimum_gap_lower_bound_m"]
                    for r in trace
                ]
            )
            axes[1, column].plot(t, gap, linestyle=linestyle, label=label)
        axes[0, column].set(
            title=jobs[index].replace("sst_radius2_", "SST "), ylabel="yaw rate [deg/s]"
        )
        axes[1, column].set(
            xlabel="saved time [s]", ylabel="required-gap lower bound [m]"
        )
        axes[1, column].axhline(0, color="black", linewidth=0.7)
        for axis in axes[:, column]:
            axis.legend(fontsize=8)
    fig.savefig(folder / "controls_and_clearance.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
