"""Plot the frozen Stage6B records without rerunning searches or controllers."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib as mpl
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

CASES = (
    "straight",
    "left_arc",
    "right_arc",
    "climb",
    "dive",
    "combined",
    "F_O1",
    "F_N1",
    "F_B1",
)
SELECTED_CASES = ("straight", "climb", "dive", "F_O1")
COLUMNS = (("rrt", "0"), ("rrt", "1"), ("sst", "0"), ("sst", "1"))
BLUE, ORANGE, PURPLE, GRAY = "#2166ac", "#df8f2d", "#9c559d", "#e5e7eb"
SELECTION = "First native exact job_id in lexicographic order within each fixed case"


def _true(row: dict[str, str], key: str) -> bool:
    """Require explicit Boolean evidence in the public table."""
    if row[key] not in ("True", "False"):
        raise ValueError(f"Invalid Boolean {key}: {row[key]}")
    return row[key] == "True"


def _rows(output: Path) -> list[dict[str, str]]:
    """Read and validate the complete fixed matrix."""
    with (output / "planning_runs.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    expected = {
        (case, algorithm, seed) for case in CASES for algorithm, seed in COLUMNS
    }
    observed = {(r["scenario"], r["algorithm"], r["seed_label"]) for r in rows}
    if len(rows) != 36 or observed != expected:
        raise ValueError("The fixed 36-run matrix is incomplete or duplicated")
    if len({r["job_id"] for r in rows}) != 36:
        raise ValueError("The matrix contains duplicate job identifiers")
    for row in rows:
        model = _true(row, "model_feasible_before_deadline")
        if model != _true(row, "model_feasible"):
            raise ValueError("Budget and final native model outcomes differ")
        if model and (
            row["native_status"] != "exact"
            or not _true(row, "independent_audit_passed")
            or _true(row, "planning_deadline_rejected")
        ):
            raise ValueError("A displayed native certificate fails its evidence gates")
        if not model and row["native_status"] != "approximate":
            raise ValueError(
                "A non-approximate native failure needs its own figure key"
            )
        if _true(row, "los_strict_success") and not _true(row, "was_run"):
            raise ValueError("A LOS success lacks an actual controller execution")
    return rows


def _save(figure: Figure, output: Path, name: str) -> None:
    """Export one readable PNG without duplicating derived artifacts."""
    FigureCanvasAgg(figure)
    figure.savefig(output / f"{name}.png", dpi=180, facecolor="white")


def _los_category(row: dict[str, str]) -> int:
    """Keep every observed failure class separate from strict success."""
    if not _true(row, "was_run"):
        return 0
    if _true(row, "los_strict_success"):
        return 1
    categories = {
        "tracking_error_limit": 2,
        "goal_reached_required_margin_violated": 3,
    }
    if row["los_failure_reason"] not in categories:
        raise ValueError("An unregistered LOS outcome needs an explicit figure key")
    return categories[row["los_failure_reason"]]


def _matrix(rows: list[dict[str, str]], output: Path) -> None:
    """Show all 36 native outcomes and their corresponding LOS outcomes."""
    lookup = {(r["scenario"], r["algorithm"], r["seed_label"]): r for r in rows}
    native = np.array(
        [
            [int(_true(lookup[case, *col], "model_feasible")) for col in COLUMNS]
            for case in CASES
        ]
    )
    los = np.array(
        [[_los_category(lookup[case, *col]) for col in COLUMNS] for case in CASES]
    )
    figure = Figure(figsize=(11.4, 6.7))
    axes = figure.subplots(1, 2)
    figure.subplots_adjust(left=0.13, right=0.97, top=0.80, bottom=0.22, wspace=0.42)
    native_count = int(native.sum())
    run_count = sum(_true(r, "was_run") for r in rows)
    strict_count = sum(_true(r, "los_strict_success") for r in rows)
    titles = (
        f"Native control certificate: M = {native_count}/36",
        f"LOS strict execution: S = {strict_count}/{run_count} run",
    )
    for index, (axis, values, title) in enumerate(
        zip(axes, (native, los), titles, strict=True)
    ):
        colors = (GRAY, BLUE) if index == 0 else (GRAY, BLUE, ORANGE, PURPLE)
        codes = ("A", "M") if index == 0 else ("-", "S", "T", "C")
        axis.imshow(
            values,
            cmap=ListedColormap(colors),
            vmin=-0.5,
            vmax=len(colors) - 0.5,
            aspect="auto",
        )
        axis.set_xticks(range(4), [f"{a.upper()}\nlabel {s}" for a, s in COLUMNS])
        axis.set_yticks(range(9), CASES)
        axis.tick_params(length=0, pad=7)
        axis.set_xticks(np.arange(-0.5, 4, 1), minor=True)
        axis.set_yticks(np.arange(-0.5, 9, 1), minor=True)
        axis.grid(which="minor", color="white", linewidth=2)
        axis.tick_params(which="minor", length=0)
        axis.set_title(title, fontsize=12, pad=12)
        for (y, x), category in np.ndenumerate(values):
            axis.text(
                x,
                y,
                codes[category],
                ha="center",
                va="center",
                color="white" if category == 1 else "#222222",
                fontsize=11,
            )
        for spine in axis.spines.values():
            spine.set_visible(False)
    figure.suptitle("Stage6B: all 36 registered runs", y=0.95, fontsize=16)
    figure.text(
        0.5,
        0.875,
        f"K = 36; native M = {native_count}; LOS E = {run_count}; "
        f"complete-task S/K = {strict_count}/36",
        ha="center",
        fontsize=11,
    )
    legend = [
        Patch(color=BLUE, label="M: exact, audited, within planning deadline"),
        Patch(color=GRAY, label="A: approximate; LOS -: not run"),
        Patch(color=ORANGE, label="T: tracking error limit"),
        Patch(color=PURPLE, label="C: goal reached; required margin violated"),
    ]
    figure.legend(
        handles=legend,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.075),
        ncol=2,
        frameon=False,
        fontsize=9,
        columnspacing=2,
    )
    figure.text(
        0.5,
        0.037,
        "S: goal reached with required clearance. Seed labels 0/1 use "
        "native seeds 1/2. No registered run is omitted.",
        ha="center",
        fontsize=9,
    )
    _save(figure, output, "native_los_matrix")


def _load(row: dict[str, str], local: Path) -> dict[str, Any]:
    """Load existing numeric evidence; never import an experiment runner."""
    folder = local / "search" / row["job_id"]
    scenario = json.loads((folder / "input.json").read_text(encoding="utf-8"))[
        "scenario"
    ]
    with gzip.open(folder / "independent_record.json.gz", "rt", encoding="utf-8") as f:
        record = json.load(f)
    if scenario["id"] != row["scenario"]:
        raise ValueError("Raw scenario and public job table differ")
    native_trace, los_trace = record["native_replay_trace"], record["los_trace"]
    if (
        not native_trace
        or not los_trace
        or any(not r["accepted"] for r in native_trace)
    ):
        raise ValueError("Selected native exact trajectory has incomplete evidence")
    if record["tracking"]["reference_bridge_is_native_control"] is not False:
        raise ValueError("The geometric reference bridge is not a native control")
    if record["tracking"]["failure_reason"] != row["los_failure_reason"]:
        raise ValueError("Raw and public LOS failure reasons differ")
    native = np.array([scenario["initial"][:3]] + [r["position"] for r in native_trace])
    los = np.array([scenario["initial"][:3]] + [r["position"] for r in los_trace])
    if not np.isfinite(native).all() or not np.isfinite(los).all():
        raise ValueError("Trajectory coordinates must be finite")
    return {"scenario": scenario, "record": record, "native": native, "los": los}


def _obstacles(axis: Any, scenario: dict[str, Any], dim: int) -> None:
    """Show physical voxel projections only, without claiming 3D clearance."""
    physical = scenario["physical"]
    path = Path(physical["data_file"])
    grid = np.fromfile(path, dtype=np.uint8).reshape(physical["shape"])
    projected = grid.any(axis=2 if dim == 1 else 1).T
    if not projected.any():
        return
    origin, spacing, shape = (
        physical["origin"],
        physical["spacing"],
        physical["shape"],
    )
    axis.imshow(
        np.ma.masked_where(~projected, projected),
        origin="lower",
        extent=(
            origin[0],
            origin[0] + shape[0] * spacing[0],
            origin[dim],
            origin[dim] + shape[dim] * spacing[dim],
        ),
        cmap=ListedColormap(["#d5d7da"]),
        vmin=0,
        vmax=1,
        interpolation="nearest",
        aspect="auto",
        zorder=0,
    )


def _trajectories(
    selected: list[dict[str, str]], local: Path, output: Path
) -> list[dict[str, Any]]:
    """Compare fixed selected examples, including their LOS failures."""
    figure = Figure(figsize=(12.0, 13.2))
    axes = figure.subplots(4, 2)
    figure.subplots_adjust(
        left=0.075, right=0.97, top=0.85, bottom=0.10, hspace=0.51, wspace=0.18
    )
    details = []
    labels = {
        "goal_reached": "strict success",
        "tracking_error_limit": "tracking limit",
        "goal_reached_required_margin_violated": "required margin violated",
    }
    for index, row in enumerate(selected):
        data = _load(row, local)
        scenario, native, los = data["scenario"], data["native"], data["los"]
        goal = np.array(scenario["goal"])
        first_margin = data["record"]["tracking"]["first_margin_rejection_position"]
        for dim, axis in zip((1, 2), axes[index], strict=True):
            _obstacles(axis, scenario, dim)
            axis.plot(native[:, 0], native[:, dim], color=BLUE, lw=1.35, zorder=2)
            axis.plot(los[:, 0], los[:, dim], color=ORANGE, ls="--", lw=1.15, zorder=3)
            axis.plot(
                [native[-1, 0], goal[0]],
                [native[-1, dim], goal[dim]],
                color="#298055",
                ls=":",
                lw=2.3,
                zorder=4,
            )
            axis.scatter(*native[0, [0, dim]], s=21, color="#222222", zorder=5)
            axis.scatter(*goal[[0, dim]], s=75, marker="*", color="#a93232", zorder=5)
            axis.scatter(
                *los[-1, [0, dim]],
                s=34,
                marker="s",
                facecolors="none",
                edgecolors=ORANGE,
                linewidths=1.3,
                zorder=6,
            )
            if first_margin is not None:
                axis.scatter(
                    first_margin[0],
                    first_margin[dim],
                    s=55,
                    marker="x",
                    color=PURPLE,
                    linewidths=1.4,
                    zorder=7,
                )
            axis.set_xlabel("x (m)", labelpad=2)
            axis.set_ylabel(f"{'y' if dim == 1 else 'z'} (m)", labelpad=2)
            projection = "XY" if dim == 1 else "XZ"
            axis.set_title(
                f"{row['scenario']} | {projection} | "
                f"{row['algorithm'].upper()}, label {row['seed_label']}\n"
                f"LOS: {labels[row['los_failure_reason']]}",
                fontsize=10,
                pad=6,
            )
            axis.grid(color="#dddddd", lw=0.5, alpha=0.7)
            axis.set_axisbelow(True)
            axis.margins(0.07)
            if row["scenario"] == "F_O1":
                physical = scenario["physical"]
                axis.set_xlim(0, physical["shape"][0] * physical["spacing"][0])
                axis.set_ylim(0, physical["shape"][dim] * physical["spacing"][dim])
            for spine in axis.spines.values():
                spine.set_color("#b0b0b0")
        details.append(
            {
                "job_id": row["job_id"],
                "native_samples": len(native),
                "los_samples": len(los),
                "los_failure_reason": row["los_failure_reason"],
                "reference_bridge_length_m": data["record"]["tracking"][
                    "reference_bridge_length_m"
                ],
                "margin_rejected_endpoint_shown": first_margin is not None,
            }
        )
    handles = [
        Line2D([], [], color=BLUE, lw=1.5, label="Native control replay"),
        Line2D([], [], color=ORANGE, ls="--", label="Frozen LOS execution"),
        Line2D([], [], color="#298055", ls=":", lw=2, label="Reference-only bridge"),
        Patch(color="#d5d7da", label="Physical voxel projection"),
        Line2D([], [], color="#222222", marker="o", ls="none", label="Start"),
        Line2D(
            [],
            [],
            color="#a93232",
            marker="*",
            ls="none",
            markersize=9,
            label="Goal position",
        ),
        Line2D(
            [],
            [],
            color=ORANGE,
            marker="s",
            ls="none",
            markerfacecolor="none",
            label="Last LOS endpoint",
        ),
        Line2D(
            [],
            [],
            color=PURPLE,
            marker="x",
            ls="none",
            label="First margin-rejected interval endpoint",
        ),
    ]
    figure.suptitle(
        "Stage6B: native and LOS trajectory projections", y=0.975, fontsize=16
    )
    figure.text(
        0.5,
        0.94,
        "Fixed cases; first native exact job_id in lexicographic order "
        "within each case. LOS outcome is not a selection criterion.",
        ha="center",
        fontsize=9,
    )
    figure.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.921),
        ncol=4,
        frameon=False,
        fontsize=8.7,
        columnspacing=1.3,
    )
    figure.text(
        0.5,
        0.035,
        "Coordinate projections use independent axis scales; they do not "
        "establish 3D clearance.\nA rejected-interval endpoint is not a "
        "collision instant. The dotted goal bridge is a geometric "
        "reference extension, not a native control.",
        ha="center",
        fontsize=9,
        linespacing=1.5,
    )
    _save(figure, output, "trajectory_comparison")
    return details


def main() -> None:
    """Build public figures and compact provenance from completed evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage6b"))
    args = parser.parse_args()
    output, local = args.output.resolve(), args.local_root.resolve()
    rows = _rows(output)
    selected = [
        min(
            (
                r
                for r in rows
                if r["scenario"] == case and r["native_status"] == "exact"
            ),
            key=lambda r: r["job_id"],
        )
        for case in SELECTED_CASES
    ]
    with mpl.rc_context({"font.family": "DejaVu Sans", "font.size": 10}):
        _matrix(rows, output)
        details = _trajectories(selected, local, output)
    manifest = []
    for name, cohort, rule in (
        ("native_los_matrix", rows, "All 36 fixed registered runs; no selection"),
        ("trajectory_comparison", selected, SELECTION),
    ):
        manifest.extend(
            {
                "figure": name,
                "job_id": row["job_id"],
                "scenario": row["scenario"],
                "algorithm": row["algorithm"],
                "seed_label": row["seed_label"],
                "selection_rule": rule,
                "native_status": row["native_status"],
                "native_M": row["model_feasible"],
                "los_was_run": row["was_run"],
                "los_strict_success": row["los_strict_success"],
                "los_failure_reason": row["los_failure_reason"],
            }
            for row in cohort
        )
    with (output / "figure_manifest.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest[0]))
        writer.writeheader()
        writer.writerows(manifest)
    qa = {
        "source": "Existing planning_runs.csv and local numeric records only",
        "new_searches_or_executions": 0,
        "registered_runs_shown": len(rows),
        "native_M": sum(_true(r, "model_feasible") for r in rows),
        "los_E": sum(_true(r, "was_run") for r in rows),
        "los_S": sum(_true(r, "los_strict_success") for r in rows),
        "los_outcome_counts": dict(Counter(r["los_failure_reason"] for r in rows)),
        "selection_rule": SELECTION,
        "selected": details,
        "notes": [
            "Bridge is reference-only, never native control",
            "2D projection is not a 3D safety certificate",
            "Rejected interval endpoints are not collision instants",
        ],
        "visual_review": {"status": "pending", "reviewed_images": []},
    }
    (output / "figure_qa.json").write_text(
        json.dumps(qa, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "figures": ["native_los_matrix", "trajectory_comparison"],
                "runs": len(rows),
                "selected": [r["job_id"] for r in selected],
            }
        )
    )


if __name__ == "__main__":
    main()
