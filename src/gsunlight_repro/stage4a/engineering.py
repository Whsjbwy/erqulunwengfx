"""Fixed-work timing controls and isolated exact-cache feasibility checks."""

from __future__ import annotations

import csv
import json
import time
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

from .. import paper_planner, safety_planner
from ..grid_candidates import CandidateNode
from ..planning import PlanningLimits
from .maps import load_map
from .measurement import Measurement


def fixed_work(
    scene_id: str,
    mode: str,
    protocol: dict,
    *,
    trace: bool = False,
) -> dict[str, Any]:
    """Time a nonbinding-deadline attempt, excluding map construction."""
    scene = load_map(scene_id)
    options = {**protocol["shared_parameters"], "n_max": protocol["fixed_work_n_max"]}
    chosen = []
    original = paper_planner._choose_sun

    def choose(*args: Any) -> CandidateNode:
        node = original(*args)
        chosen.append((node.node_id, node.parent_id, node.point, node.accumulated_cost))
        return node

    started = time.perf_counter()
    measurement = Measurement(
        scene.grid, protocol["cache_max_entries"] if mode == "cache" else 0
    )
    with ExitStack() as stack:
        if mode != "bare":
            stack.enter_context(measurement.installed())
        if trace:
            stack.enter_context(patch.object(paper_planner, "_choose_sun", choose))
        result = safety_planner.plan(
            scene.grid, scene.start, scene.goal, 0, PlanningLimits(120), options
        )
    elapsed = time.perf_counter() - started
    if result.termination_reason == "time_budget":
        raise RuntimeError(
            "Fixed-work timing reached its deadline; equivalence is inconclusive"
        )
    return {
        "scene": scene_id,
        "mode": mode,
        "elapsed_s": elapsed,
        "result": asdict(result),
        "expanded_sequence": chosen,
        **measurement.metrics(),
    }


def benchmark(protocol: dict, local: Path, output: Path) -> dict:
    """Retain all preregistered five repeats, including slow or negative results."""
    evidence_path = local / "engineering_evidence.json"
    if evidence_path.exists():
        raise FileExistsError("Engineering evidence already exists; do not overwrite")
    rows, checks, traces = [], [], []
    for scene in protocol["fixed_work_maps"]:
        cases = {
            mode: fixed_work(scene, mode, protocol, trace=True)
            for mode in ("bare", "light", "cache")
        }
        traces.extend(cases.values())
        reference = cases["bare"]
        equal = {
            field + "_equal": all(
                c["result"][field] == reference["result"][field] for c in cases.values()
            )
            for field in ("raw_path", "status", "termination_reason", "parameters")
        }
        equal["expanded_sequence_equal"] = all(
            c["expanded_sequence"] == reference["expanded_sequence"]
            for c in cases.values()
        )
        count_fields = [
            key for key in reference["result"]["counters"] if key != "collision_checks"
        ]
        equal["logical_counters_equal"] = all(
            c["result"]["counters"][key] == reference["result"]["counters"][key]
            for c in cases.values()
            for key in count_fields
        )
        checks.append({"scene": scene, **equal})
        if not all(equal.values()):
            evidence_path.write_text(
                json.dumps({"traces": traces, "checks": checks}, indent=2),
                encoding="utf-8",
            )
            raise RuntimeError("Engineering fixed-work equivalence failed")
        for repeat in range(protocol["timing_repetitions"]):
            # Rotate mode order deterministically, never select the fastest run.
            modes = ("bare", "light", "cache")
            order = modes[repeat % 3 :] + modes[: repeat % 3]
            for mode in order:
                trial = fixed_work(scene, mode, protocol)
                trial.pop("expanded_sequence")
                native = trial.pop("result")
                rows.append(
                    {
                        **trial,
                        "repeat": repeat,
                        "expanded_nodes": native["counters"]["expanded_nodes"],
                        "native_collision_checks": native["counters"][
                            "collision_checks"
                        ],
                    }
                )
    evidence_path.write_text(
        json.dumps({"traces": traces, "checks": checks, "timing": rows}, indent=2),
        encoding="utf-8",
    )
    output.mkdir(parents=True, exist_ok=True)
    with (output / "fixed_work_timing.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "engineering_equivalence.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    return {"timing_trials": len(rows), "fixed_work_equivalence": checks}
