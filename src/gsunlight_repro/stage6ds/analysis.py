"""Full54 denominators, paired costs and descriptive map sensitivity."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from ..stage5a.analysis import write_csv
from ..stage6c.common import boolean, read_csv, read_json
from ..stage6d.common import load_record, save_json
from . import PUBLIC
from .protocol import frozen

CONDITIONS = ("rrt_first", "sst_radius2_first", "sst_radius2_anytime")
LABELS = ("Control RRT first", "SST first", "SST anytime")
COLORS = ("#405c93", "#1d8a78", "#c57a1e")


def deadline_choice(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep a certified first incumbent available when final certification is late."""
    available = [c for c in candidates if c["safe"] and c["finish_s"] <= 10]
    if not available:
        return {
            "certificate_available_before10": False,
            "deadline_best_certified_arc_m": None,
            "deadline_selected": None,
            "earliest_available_certificate_s": None,
        }
    best = min(available, key=lambda c: (round(c["cost_m"] / 0.1), c["finish_s"]))
    return {
        "certificate_available_before10": True,
        "deadline_best_certified_arc_m": best["cost_m"],
        "deadline_selected": best["label"],
        "earliest_available_certificate_s": min(c["finish_s"] for c in available),
    }


def group_rates(rows: list[dict[str, Any]]) -> dict[str, int | float | None]:
    """Do not remove unsuccessful jobs from K or confuse conditional S/E with S/K."""
    k = len(rows)
    m = sum(boolean(r["model_feasible"]) for r in rows)
    g = sum(r["reference_geometry_safe"] == "True" for r in rows)
    e = sum(boolean(r["los_was_run"]) and boolean(r["los_eligible"]) for r in rows)
    s = sum(boolean(r["los_strict_success"]) for r in rows)
    return {
        "K": k,
        "M": m,
        "Gref": g,
        "E": e,
        "S": s,
        "M_K": m / k if k else None,
        "S_E": s / e if e else None,
        "S_K": s / k if k else None,
    }


def leave_one_map_out(rows: list[dict[str, Any]]) -> tuple[float, float]:
    """A deterministic sample-sensitivity range, explicitly not a confidence bound."""
    values = [
        group_rates([r for r in rows if r["scenario"] != name])["M_K"]
        for name in sorted({r["scenario"] for r in rows})
    ]
    return float(min(values)), float(max(values))


def plots(
    rows: list[dict[str, Any]], events: list[dict[str, Any]], output: Path
) -> None:
    """Show every seed, failure and observed anytime curve without imputation."""
    maps = list(dict.fromkeys(r["scenario"] for r in rows))
    fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
    matrix = np.zeros((18, 3))
    for c, condition in enumerate(CONDITIONS):
        for i, name in enumerate(maps):
            for seed in range(1, 4):
                row = next(
                    r
                    for r in rows
                    if r["condition"] == condition
                    and r["scenario"] == name
                    and int(r["native_seed"]) == seed
                )
                value = (
                    3
                    if boolean(row["los_strict_success"])
                    else 2
                    if boolean(row["model_feasible"])
                    else 1
                    if boolean(row["native_M_before_budget"])
                    else 0
                )
                matrix[i * 3 + seed - 1, c] = value
                ax.text(
                    c,
                    i * 3 + seed - 1,
                    ("A", "Late", "M", "S")[value],
                    ha="center",
                    va="center",
                    color="white" if value < 2 else "black",
                )
    from matplotlib.colors import ListedColormap

    ax.imshow(
        matrix,
        aspect="auto",
        cmap=ListedColormap(["#6b7280", "#ad4e4e", "#dbaf50", "#75bd9b"]),
        vmin=0,
        vmax=3,
    )
    ax.set_xticks(range(3), LABELS)
    ax.set_yticks(
        range(18), [f"{name} / seed{s}" for name in maps for s in range(1, 4)]
    )
    ax.set_title(
        "All54: A=approximate; Late=final cert after10s; M=final native; S=LOS"
    )
    fig.savefig(output / "all54_outcomes.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4), constrained_layout=True)
    for c, condition in enumerate(CONDITIONS):
        group = [r for r in rows if r["condition"] == condition]
        for i, row in enumerate(group):
            good = boolean(row["model_feasible"])
            axes[0].scatter(
                c + (i - 8.5) * 0.025,
                float(row["best_independent_certificate_s"]),
                color=COLORS[c],
                marker="o" if good else "x",
                s=20,
            )
        success = [r for r in group if boolean(r["model_feasible"])]
        for i, row in enumerate(success):
            axes[1].scatter(
                c + (i - len(success) / 2) * 0.025,
                float(row["strict_control_arc_m"]),
                color=COLORS[c],
                s=20,
            )
        for i, name in enumerate(maps):
            subset = [r for r in group if r["scenario"] == name]
            axes[2].bar(
                i + (c - 1) * 0.25,
                group_rates(subset)["M"],
                width=0.24,
                color=COLORS[c],
                label=LABELS[c] if i == 0 else None,
            )
    axes[0].axhline(10, ls="--", color="black", lw=1)
    axes[0].set_ylabel("Independent certificate completion (s)")
    axes[0].set_title("All54 final-cert clocks; x=not final-qualified")
    axes[1].set_ylabel("Strict native control arc (m), speed=1m/s")
    axes[1].set_title("Final-certified costs; failures omitted here only")
    for ax in axes[:2]:
        ax.set_xticks(range(3), ["RRT", "SST first", "SST anytime"], rotation=15)
    axes[2].set_xticks(range(6), maps, rotation=40)
    axes[2].set_yticks(range(4))
    axes[2].set_ylabel("Strict M out of3 seeds")
    axes[2].set_title("Six development maps")
    axes[2].legend(fontsize=7)
    fig.savefig(output / "time_cost_coverage.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(2, 3, figsize=(12, 7), constrained_layout=True)
    for ax, name in zip(axes.flat, maps, strict=True):
        for seed, color in zip(range(1, 4), COLORS, strict=True):
            group = [
                e
                for e in events
                if e["scenario"] == name
                and e["native_seed"] == seed
                and e["condition"] == "sst_radius2_anytime"
            ]
            if group:
                source = next(
                    r
                    for r in rows
                    if r["scenario"] == name
                    and int(r["native_seed"]) == seed
                    and r["condition"] == "sst_radius2_anytime"
                )
                suffix = (
                    " (late final cert)"
                    if not boolean(source["model_feasible"])
                    else ""
                )
                ax.step(
                    [e["native_certificate_finish_s"] for e in group],
                    [e["cost"] for e in group],
                    where="post",
                    marker=".",
                    label=f"seed{seed}{suffix}",
                    color=color,
                )
            else:
                ax.plot([], [], label=f"seed{seed}: no exact", color=color)
        ax.set_title(name)
        ax.set_xlabel("Native certified incumbent clock (s)")
        ax.set_ylabel("Control arc (m)")
        ax.legend(fontsize=7)
    fig.suptitle("All18 anytime runs; native events are not independent Python times")
    fig.savefig(output / "all_anytime_costs.png", dpi=160)
    plt.close(fig)


def run(local: Path, output: Path = PUBLIC) -> dict[str, Any]:
    """Summarize complete original records; analysis never calls a native process."""
    cfg, tasks = frozen()
    rows = read_csv(PUBLIC / "planning_runs.csv")
    if len(rows) != 54 or [r["job_id"] for r in rows] != [t["job_id"] for t in tasks]:
        raise ValueError("The full inherited54 roster is not present")
    if any(r["run_state"] != "completed" for r in rows):
        raise ValueError("Unrun/exception jobs cannot be turned into completed results")
    rates, map_rates, failures, events, paired = [], [], [], [], []
    maps = cfg["maps"]
    for condition in CONDITIONS:
        group = [r for r in rows if r["condition"] == condition]
        success = [r for r in group if boolean(r["model_feasible"])]
        low, high = leave_one_map_out(group)
        rates.append(
            {
                "condition": condition,
                **group_rates(group),
                "cost_sample_n": len(success),
                "median_certified_arc_m": float(
                    np.median([float(r["strict_control_arc_m"]) for r in success])
                )
                if success
                else None,
                "median_all_certificate_finish_s": float(
                    np.median(
                        [float(r["best_independent_certificate_s"]) for r in group]
                    )
                ),
                "leave_one_map_out_MK_min": low,
                "leave_one_map_out_MK_max": high,
            }
        )
        for name in maps:
            subset = [r for r in group if r["scenario"] == name]
            map_rates.append(
                {"condition": condition, "scenario": name, **group_rates(subset)}
            )
        for (phase, reason), count in Counter(
            (
                "native_search_or_budget"
                if not boolean(r["model_feasible"])
                else "LOS_or_execution",
                r["failure_reason"],
            )
            for r in group
            if not boolean(r["los_strict_success"])
        ).items():
            failures.append(
                {
                    "condition": condition,
                    "phase": phase,
                    "reason": reason,
                    "count": count,
                }
            )
    available_rows = []
    for row in rows:
        payload = read_json(local / "search" / row["job_id"] / "output.json")
        record = load_record(
            local / "search" / row["job_id"] / "independent_record.json.gz"
        )
        first = record["first_audit"]
        first_path = payload.get("first_path") or payload
        candidates = [
            {
                "label": "final",
                "safe": record["audit"]["model_feasible"],
                "finish_s": float(row["best_independent_certificate_s"]),
                "cost_m": sum(c["duration_s"] for c in payload["controls"]),
            }
        ]
        if first is not None and row["first_independent_certificate_s"]:
            candidates.append(
                {
                    "label": "first",
                    "safe": first["model_feasible"],
                    "finish_s": float(row["first_independent_certificate_s"]),
                    "cost_m": sum(c["duration_s"] for c in first_path["controls"]),
                }
            )
        available_rows.append(
            {
                "job_id": row["job_id"],
                "condition": row["condition"],
                "frozen_final_qualified_M": boolean(row["model_feasible"]),
                "first_certificate_s": row["first_independent_certificate_s"],
                "final_certificate_s": row["best_independent_certificate_s"],
                **deadline_choice(candidates),
            }
        )
        events.extend(
            {
                "job_id": row["job_id"],
                "condition": row["condition"],
                "scenario": row["scenario"],
                "native_seed": int(row["native_seed"]),
                "event": i,
                **event,
            }
            for i, event in enumerate(payload["improvement_events"])
        )
    for name in maps:
        for seed in range(1, 4):
            first = next(
                r
                for r in rows
                if r["scenario"] == name
                and int(r["native_seed"]) == seed
                and r["condition"] == "sst_radius2_first"
            )
            anytime = next(
                r
                for r in rows
                if r["scenario"] == name
                and int(r["native_seed"]) == seed
                and r["condition"] == "sst_radius2_anytime"
            )
            both = boolean(first["model_feasible"]) and boolean(
                anytime["model_feasible"]
            )
            paired.append(
                {
                    "scenario": name,
                    "native_seed": seed,
                    "first_M": boolean(first["model_feasible"]),
                    "anytime_M": boolean(anytime["model_feasible"]),
                    "both_strict": both,
                    "first_arc_m": float(first["strict_control_arc_m"])
                    if both
                    else None,
                    "anytime_arc_m": float(anytime["strict_control_arc_m"])
                    if both
                    else None,
                    "paired_reduction_m": (
                        float(first["strict_control_arc_m"])
                        - float(anytime["strict_control_arc_m"])
                    )
                    if both
                    else None,
                }
            )
    write_csv(output / "deadline_available_incumbents.csv", available_rows)
    for rate in rates:
        rate["M_available_before10"] = sum(
            r["certificate_available_before10"]
            for r in available_rows
            if r["condition"] == rate["condition"]
        )
    for filename, data in (
        ("rates.csv", rates),
        ("map_rates.csv", map_rates),
        ("failure_counts.csv", failures),
        ("native_cost_events.csv", events),
        ("paired_sst_costs.csv", paired),
    ):
        write_csv(output / filename, data)
    result = {
        "complete": True,
        "registered": 54,
        **group_rates(rows),
        "native_exact_before_budget": sum(
            boolean(r["native_M_before_budget"]) for r in rows
        ),
        "late_native_exact": sum(
            boolean(r["native_M_before_budget"]) and not boolean(r["model_feasible"])
            for r in rows
        ),
        "at_least_one_independent_certificate_before10": sum(
            r["certificate_available_before10"] for r in available_rows
        ),
        "primary_M_definition": "Unchanged frozen6D final-return certificate chain",
        "availability_definition": (
            "Also disclose any first/final incumbent independently certified "
            "before10s; no additional tracking or replanning"
        ),
        "strong_maps_by_condition": {
            c: [r["scenario"] for r in map_rates if r["condition"] == c and r["M"] >= 2]
            for c in CONDITIONS
        },
        "paired_strict_cost_cases": sum(p["both_strict"] for p in paired),
        "paired_anytime_improvements": sum(
            p["paired_reduction_m"] is not None and p["paired_reduction_m"] > 0.05
            for p in paired
        ),
        "maximum_native_rss_bytes": max(int(r["peak_native_rss_bytes"]) for r in rows),
        "maximum_job_record_bytes": max(int(r["record_bytes"]) for r in rows),
        "independent_test_maps": 0,
        "uncertainty": (
            "Six development map clusters, three fixed seeds. Leave-one-map-out "
            "range is descriptive sensitivity, not a confidence interval or "
            "significance test."
        ),
    }
    save_json(output / "statistics.json", result)
    plots(rows, events, output)
    return result


def main() -> None:
    """Generate statistics/figures from original saved experiments only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.local_root))


if __name__ == "__main__":
    main()
