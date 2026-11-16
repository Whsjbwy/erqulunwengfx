"""Actual SI propagation and independent continuous certification of all six maps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from ..stage5a.analysis import write_csv
from ..stage6b.bridge import invoke_native
from ..stage6b.replay import audit_controls
from ..stage6b.scenarios import export_scenario, state_values
from ..stage6c.acceptance import environment
from ..stage6c.common import read_json
from .common import PUBLIC, save_json, save_record
from .maps import build_scenarios


def run(
    executable: Path, dependency: Path, local: Path, output: Path, *, ci: bool = False
) -> dict[str, Any]:
    """Never supply hidden controls to a planning request or infer unreachable tasks."""
    if not ci and not read_json(output / "d1_summary.json")["passed"]:
        raise RuntimeError("D1 gate must pass before D2 witness acceptance")
    rows = []
    for case in build_scenarios():
        native = invoke_native(
            executable,
            {
                "mode": "replay",
                "scenario": export_scenario(case, local / "grids"),
                "controls": case.witness_controls,
            },
            local / "witnesses" / case.id,
            environment=environment(dependency),
        )
        controls = [
            {**control, "duration_s": 0.1}
            for control in case.witness_controls
            for _ in range(round(control["duration_s"] / 0.1))
        ]
        if native.payload["reason"] != "ok" or len(native.payload["states"]) != len(
            controls
        ):
            save_json(
                local / "witnesses" / case.id / "rejected.json",
                {"reason": native.payload["reason"], "reachability": "unknown"},
                exclusive=True,
            )
            raise RuntimeError(f"Witness rejected in {case.id}; no search is allowed")
        audit, trace = audit_controls(
            case,
            {
                "status": "exact",
                "controls": controls,
                "states": [state_values(case.initial), *native.payload["states"]],
            },
        )
        if not audit["model_feasible"]:
            raise RuntimeError("Native and independent witness certificate disagree")
        gaps = np.array([r["minimum_gap_lower_bound_m"] for r in trace])
        final = native.payload["states"][-1]
        row = {
            "map": case.id,
            "family": case.scene.specification["family"],
            "reachability": "independently_certified_control_witness",
            "passed": True,
            "initial_state": state_values(case.initial),
            "witness_final_state": final,
            "goal_position": list(case.scene.goal),
            "terminal_orientation_constrained": False,
            "occupied_voxels": int(case.scene.grid.occupancy.sum()),
            "accepted_intervals": len(trace),
            "actual_propagator_calls": native.payload["propagator_calls"],
            "minimum_certified_gap_m": float(gaps.min()),
            "gap_q25_m": float(np.quantile(gaps, 0.25)),
            "gap_median_m": float(np.median(gaps)),
            "gap_query_truncation_m": 3.0,
            "witness_arc_m": len(trace) * 0.1,
            "maximum_rk4_error_m": audit["maximum_rk4_error_m"],
            "maximum_native_state_error_m": audit[
                "maximum_native_node_position_error_m"
            ],
            "native_calls_are_searches": False,
        }
        rows.append(row)
        save_record(
            local / "witnesses" / case.id / "independent.json.gz",
            {"summary": row, "audit": audit, "trace": trace},
        )
        write_csv(output / "d2_witnesses.csv", rows)
        print(json.dumps(row), flush=True)
    result = {
        "passed": True,
        "maps": 6,
        "families": 3,
        "accepted_intervals": sum(r["accepted_intervals"] for r in rows),
        "new_searches": 0,
        "all_witnesses_hidden_from_planners": True,
    }
    save_json(output / "d2_witness_acceptance.json", result)
    return result


def main() -> None:
    """Certify deterministic supplied controls without running any planner."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "dependency-root", "local-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    parser.add_argument("--ci", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.executable,
                args.dependency_root,
                args.local_root,
                args.output,
                ci=args.ci,
            )
        )
    )


if __name__ == "__main__":
    main()
