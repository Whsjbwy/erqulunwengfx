"""Diagnose only the failed terrain witness; do not resume performance comparisons."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..stage6b.bridge import invoke_native
from ..stage6b.replay import _replay
from ..stage6b.scenarios import export_scenario
from ..stage6c.acceptance import environment
from ..stage6c.common import read_json
from .common import PUBLIC, load_record, save_json, save_record
from .maps import build_scenarios


def run(
    probe: Path, dependency: Path, local: Path, output: Path, source_input: Path | None
) -> dict[str, Any]:
    """Preserve the exact failure and expose each predicate without weakening it."""
    case = next(case for case in build_scenarios() if case.id == "terrain_1")
    request = (
        read_json(source_input)
        if source_input
        else {
            "mode": "replay",
            "scenario": export_scenario(case, local / "grids"),
            "controls": case.witness_controls,
        }
    )
    prior = local / "native_probe/output.json"
    if prior.exists():
        if read_json(local / "native_probe/input.json") != request:
            raise RuntimeError("Existing diagnostic request differs")
        result = read_json(prior)
    else:
        result = invoke_native(
            probe, request, local / "native_probe", environment=environment(dependency)
        ).payload
    if not (
        result["mismatch_detected"]
        and result["direct_interval_valid"]
        and result["candidate_model_valid"]
        and result["candidate_point_geometry_valid"]
        and result["position_subspace_bounds"]
        and result["yaw_subspace_bounds"]
        and not result["pitch_subspace_bounds"]
    ):
        raise RuntimeError(
            "Diagnostic did not reproduce the observed pitch predicate conflict"
        )
    # Supplied-control model replay; never an invented OMPL PathControl.
    audit, trace, _ = _replay(case, case.witness_controls)
    if audit["reason"] != "ok" or not audit["goal_reached"]:
        raise RuntimeError(
            "Independent full terrain model witness failed; retain this discrepancy"
        )
    index = result["interval_index"]
    if (
        max(
            abs(a - b)
            for a, b in zip(
                trace[index]["position"], result["candidate_state"][:3], strict=True
            )
        )
        > 1e-10
    ):
        raise RuntimeError("Native and Python failure location differ")
    result.update(
        admission="BLOCKED",
        model_mapping_gate_passed=False,
        independent_python_full_witness=audit,
        independent_python_intervals=len(trace),
        new_planning_searches=0,
        frozen_code_modified=False,
        python_witness_scope=(
            "Supplied-control model integration and continuous safety only; "
            "not a returned OMPL path or planner success"
        ),
        diagnosis_scope=(
            "One failed witness plus a deterministic predicate counterexample; "
            "performance comparisons remain stopped"
        ),
    )
    save_json(output / "model_mapping_failure.json", result)
    record_path = local / "model_witness_diagnostic.json.gz"
    if record_path.exists():
        saved = load_record(record_path)
        if json.dumps(saved["trace"], sort_keys=True) != json.dumps(
            trace, sort_keys=True
        ):
            raise RuntimeError("Existing diagnostic model trace differs")
        save_json(
            local / "python_witness_scope.json",
            {
                "note": (
                    "Initial audit used Python-generated boundary nodes, not native "
                    "returned nodes; trace unchanged. Public audit now uses direct "
                    "frozen supplied-control replay without synthetic native labels."
                ),
                "native_probe_repeated": False,
            },
        )
    else:
        save_record(record_path, {"audit": audit, "trace": trace})
    return result


def main() -> None:
    """Accept the original request locally, or generate the same synthetic CI case."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("probe", "dependency-root", "local-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-input", type=Path)
    parser.add_argument("--output", type=Path, default=PUBLIC)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.probe,
                args.dependency_root,
                args.local_root,
                args.output,
                args.source_input,
            )
        )
    )


if __name__ == "__main__":
    main()
