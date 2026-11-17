"""Plot preserved observations only; no state or controller propagation."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from ..stage6d.common import load_record  # noqa: E402
from . import PUBLIC  # noqa: E402
from .audit import first_event  # noqa: E402


def draw_turn(records: list[dict[str, Any]], output: Path) -> None:
    """Use all three preregistered SST-first turn_2 seeds, without selection."""
    fig, axes = plt.subplots(2, 3, figsize=(12, 6), constrained_layout=True)
    for seed, record in enumerate(records, start=1):
        native, los = record["native_trace"], record["los_trace"]
        first = first_event(los, "margin")
        if not isinstance(first, int):
            raise ValueError("Expected the preserved turn_2 first margin event")
        for trace, label in ((native, "Native control"), (los, "Frozen LOS")):
            points = np.asarray(
                [trace[0]["start_position"]] + [r["position"] for r in trace]
            )
            axes[0, seed - 1].plot(points[:, 0], points[:, 1], label=label)
        point = los[first]["position"]
        axes[0, seed - 1].scatter(point[0], point[1], color="crimson", marker="x")
        axes[0, seed - 1].set(
            title=f"turn_2 SST-first seed {seed}", xlabel="x [m]", ylabel="y [m]"
        )
        axes[0, seed - 1].set_aspect("equal", adjustable="datalim")
        axes[0, seed - 1].legend(fontsize=8)
        axes[1, seed - 1].plot(
            [r["time_s"] for r in native],
            [r["minimum_gap_lower_bound_m"] for r in native],
            label="Native required-gap LB",
        )
        axes[1, seed - 1].plot(
            [r["time_s"] for r in los],
            [r["mission_clearance_lower_bound_m"] - 0.25 for r in los],
            label="LOS required-gap LB",
        )
        axes[1, seed - 1].axhline(0, color="black", linewidth=0.7)
        axes[1, seed - 1].axvline(los[first]["time_s"], color="crimson", linestyle=":")
        axes[1, seed - 1].set(xlabel="saved time [s]", ylabel="gap lower bound [m]")
        axes[1, seed - 1].legend(fontsize=7)
    fig.suptitle(
        "Saved nominal simulations only; XY projection is not a safety certificate"
    )
    fig.savefig(output, dpi=160)
    plt.close(fig)


def draw_workspace(record: dict[str, Any], output: Path) -> None:
    """Separate first margin loss from physical rejection, using recorded samples."""
    los = record["los_trace"]
    t = [r["time_s"] for r in los]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.5), constrained_layout=True)
    axes[0].plot(t, [r["position"][0] for r in los], label="LOS candidate x")
    axes[0].axhline(56 - math.sqrt(1.04), label="Body limit", color="black")
    axes[0].axhline(
        56 - math.sqrt(1.04) - 0.25, label="Required-margin limit", color="orange"
    )
    axes[0].set(
        xlim=(58, 61.3), ylim=(54.3, 55.1), xlabel="saved time [s]", ylabel="x [m]"
    )
    axes[1].plot(t, [r["cross_track_m"] for r in los], label="Global path distance")
    axes[1].axhline(3, color="black", linestyle="--", label="Tracking stop limit")
    axes[1].set(xlabel="saved time [s]", ylabel="distance [m]")
    for kind, color in (("margin", "orange"), ("physical", "crimson")):
        index = first_event(los, kind)
        if not isinstance(index, int):
            raise ValueError("Expected preserved workspace failure events")
        for axis in axes:
            axis.axvline(
                t[index],
                color=color,
                linestyle=":",
                label=f"First {kind}: {t[index]:.1f}s",
            )
    for axis in axes:
        axis.legend(fontsize=7)
    fig.suptitle(
        "terrain_2 SST-first seed 2: saved candidate endpoints, not collision instants"
    )
    fig.savefig(output, dpi=160)
    plt.close(fig)


def main() -> None:
    """Require existing private source records; save two compact new figures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    raw = parser.parse_args().raw_root / "search"
    out = PUBLIC / "figures"
    out.mkdir(parents=True, exist_ok=True)
    records = [
        load_record(
            raw
            / f"turn_2--sst_radius2_first--seed{seed}"
            / "independent_record.json.gz"
        )
        for seed in (1, 2, 3)
    ]
    draw_turn(records, out / "turn2_saved_pairs.png")
    workspace = load_record(
        raw / "terrain_2--sst_radius2_first--seed2" / "independent_record.json.gz"
    )
    draw_workspace(workspace, out / "workspace_first_loss.png")


if __name__ == "__main__":
    main()
