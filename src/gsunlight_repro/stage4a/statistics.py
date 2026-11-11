"""Map-level paired estimates with stratified hierarchical bootstrap."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


def interval(values: np.ndarray) -> list[float] | None:
    """Return a percentile interval only for defined bootstrap estimates."""
    observed = values[np.isfinite(values)]
    return (
        [float(x) for x in np.percentile(observed, [2.5, 97.5])]
        if len(observed)
        else None
    )


def map_means(values: np.ndarray) -> np.ndarray:
    """Average defined paired lengths within each map, retaining missing maps."""
    counts = np.isfinite(values).sum(axis=-1)
    means = np.full(counts.shape, np.nan, dtype=float)
    np.divide(np.nansum(values, axis=-1), counts, out=means, where=counts > 0)
    return means


def paired_estimate(
    pairs: list[dict], repetitions: int = 2000, seed: int = 4901
) -> dict[str, Any]:
    """Resample maps within families, then matched seeds within chosen maps.

    Length gains are conditional on both methods being valid. Their coverage,
    map counts and undefined bootstrap draws remain explicit.
    """
    grouped = defaultdict(list)
    families = defaultdict(list)
    for row in pairs:
        grouped[row["scene"]].append(row)
    scenes = sorted(grouped)
    if not scenes:
        return {"maps": 0, "pairs": 0, "length_gain": None, "length_gain_ci95": None}
    for index, scene in enumerate(scenes):
        group = sorted(grouped[scene], key=lambda r: r["seed"])
        if len({r["seed"] for r in group}) != len(group):
            raise ValueError("Duplicate paired planning seed")
        grouped[scene] = group
        families[group[0]["family"]].append(index)
    widths = {len(group) for group in grouped.values()}
    if len(widths) != 1:
        raise ValueError("Hierarchical bootstrap requires the complete fixed seed list")
    left = np.array([[int(r["left_valid"]) for r in grouped[s]] for s in scenes])
    right = np.array([[int(r["right_valid"]) for r in grouped[s]] for s in scenes])
    gains = np.array(
        [
            [
                np.nan
                if r["relative_length_gain"] is None
                else r["relative_length_gain"]
                for r in grouped[s]
            ]
            for s in scenes
        ],
        dtype=float,
    )
    per_map_gain = map_means(gains)
    rng = np.random.default_rng(seed)
    map_indices = np.concatenate(
        [
            rng.choice(indices, size=(repetitions, len(indices)), replace=True)
            for _, indices in sorted(families.items())
        ],
        axis=1,
    )
    seed_indices = rng.integers(
        0, left.shape[1], size=(*map_indices.shape, left.shape[1])
    )
    expanded_map_indices = map_indices[:, :, None]
    left_draw = left[expanded_map_indices, seed_indices]
    right_draw = right[expanded_map_indices, seed_indices]
    gain_draw = gains[expanded_map_indices, seed_indices]
    bootstrap_gain = map_means(map_means(gain_draw))
    family_gain = {}
    for family, indices in families.items():
        valid = per_map_gain[indices]
        family_gain[family] = (
            float(np.mean(valid[np.isfinite(valid)]))
            if np.any(np.isfinite(valid))
            else None
        )
    return {
        "maps": len(scenes),
        "pairs": int(left.size),
        "left_rate": float(left.mean(axis=1).mean()),
        "right_rate": float(right.mean(axis=1).mean()),
        "left_rate_ci95": interval(left_draw.mean(axis=(1, 2))),
        "right_rate_ci95": interval(right_draw.mean(axis=(1, 2))),
        "success_delta": float((left - right).mean()),
        "success_delta_ci95": interval((left_draw - right_draw).mean(axis=(1, 2))),
        "joint_coverage": float((left * right).mean()),
        "joint_valid_pairs": int((left * right).sum()),
        "length_gain": float(np.mean(per_map_gain[np.isfinite(per_map_gain)]))
        if np.any(np.isfinite(per_map_gain))
        else None,
        "length_gain_ci95": interval(bootstrap_gain),
        "length_maps": int(np.isfinite(per_map_gain).sum()),
        "length_bootstrap_defined": int(np.isfinite(bootstrap_gain).sum()),
        "family_length_gain": family_gain,
        "bootstrap_repetitions": repetitions,
        "bootstrap_seed": seed,
    }


def decide(summary: dict, gate: dict, *, complete: bool, invalid_paths: int) -> dict:
    """Apply the frozen operational gate, without choosing a favorable method."""
    if not complete:
        return {"recommendation": "Incomplete", "reasons": ["预注册矩阵尚未完成"]}
    if invalid_paths:
        return {
            "recommendation": "Blocked",
            "reasons": ["存在非法接受路径，须先审核安全错误"],
        }
    reasons = []
    if summary["left_rate"] < summary["right_rate"]:
        reasons.append("A4留出图等权有效率低于RRT重启")
    if summary["joint_coverage"] < gate["minimum_joint_coverage"]:
        reasons.append("共同有效覆盖未达到预注册门槛")
    gain = summary["length_gain"]
    if gain is None or gain < gate["minimum_length_reduction"]:
        reasons.append("地图等权条件长度收益不足5%")
    bounds = summary["length_gain_ci95"]
    if bounds is None or bounds[0] <= 0:
        reasons.append("长度收益95%分层区间下界未大于0")
    positive = sum(
        v is not None and v > 0 for v in summary["family_length_gain"].values()
    )
    if positive < gate["minimum_families_with_reduction"]:
        reasons.append("收益未覆盖至少两类地图")
    return {
        "recommendation": "Pivot" if reasons else "Go",
        "reasons": reasons or ["达到预注册路线门槛，仍限于小规模静态点模型证据"],
        "primary_method": "A4",
        "comparator": "rrt_restart",
        "warning": "项目路线建议，不是期刊录用标准或普遍优劣证明",
    }
