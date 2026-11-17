"""Execute only the six approved nominal tasks after deterministic admission."""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from ..map_reader import OccupancyMap
from ..stage5a.maps import ROOT, Scene, read_config
from ..stage5a.tracking import State
from ..stage6b.scenarios import Scenario, effective_radius
from ..stage6c.common import boolean, read_csv, read_json
from ..stage6d.common import load_record, save_json, save_record
from ..stage7a.audit import native_source_consistency
from . import PUBLIC
from .execution import certify, execute
from .lqr import Limits, Matrix, jacobians, riccati, weights


def load_grid(spec: dict[str, Any], cache: dict[str, OccupancyMap]) -> OccupancyMap:
    """Read the original exact u8 voxel file once; never regenerate a map."""
    path = Path(spec["data_file"]).resolve()
    key = str(path)
    if key not in cache:
        values = np.fromfile(path, dtype=np.uint8)
        if values.size != math.prod(spec["shape"]) or not np.isin(values, [0, 1]).all():
            raise ValueError("Stored grid has wrong length or nonbinary occupancy")
        cache[key] = OccupancyMap(
            values.reshape(spec["shape"]).astype(bool),
            origin=tuple(spec["origin"]),
            spacing=tuple(spec["spacing"]),
        )
    grid = cache[key]
    if (
        grid.shape != tuple(spec["shape"])
        or grid.origin != tuple(spec["origin"])
        or grid.spacing != tuple(spec["spacing"])
    ):
        raise ValueError("Shared grid metadata differs between frozen inputs")
    return grid


def source(
    job: str, raw: Path, cache: dict[str, OccupancyMap]
) -> tuple[Scenario, dict[str, Any], list[State], list[Matrix]]:
    """Validate archived node/control correspondence and preserve full initial pose."""
    folder = raw / "search" / job
    payload = read_json(folder / "input.json")
    native = read_json(folder / "output.json")
    record = load_record(folder / "independent_record.json.gz")
    native_source_consistency(payload, native, record)
    spec = payload["scenario"]
    if spec["radius_m"] != effective_radius():
        raise ValueError("Stored circumsphere plus margin differs from frozen protocol")
    initial = State(tuple(spec["initial"][:3]), *spec["initial"][3:])
    scene = Scene(
        {"id": spec["id"], "family": "fixed_7b0_development"},
        load_grid(spec["physical"], cache),
        load_grid(spec["ceiling"], cache) if spec["ceiling"] else None,
        initial.position,
        tuple(spec["goal"]),
        None,
    )
    case = Scenario(
        spec["id"],
        scene,
        initial,
        (),
        "ok",
        "historical_strict_native",
        Path(spec["physical"]["data_file"]).stem,
    )
    references = [initial] + [
        State(tuple(r["position"]), r["yaw_rad"], r["pitch_rad"], r["speed_m_s"])
        for r in record["native_trace"]
    ]
    inputs = [
        np.array([r["yaw_rate_rad_s"], r["pitch_rate_rad_s"]], dtype=float)
        for r in record["native_trace"]
    ]
    return case, record, references, inputs


def run(raw: Path, local: Path, admission: Path) -> dict[str, Any]:
    """Use an exclusive ledger; an interrupted experiment is never retried."""
    cfg, limits = read_config("stage7b0_protocol.json"), Limits.frozen()
    gate = read_json(admission / "summary.json")
    if not gate["passed"] or gate["tests"] != 19:
        raise ValueError("Nineteen deterministic B1 cases must pass first")
    q, r, qf = weights(limits)
    if gate["Q"] != q.tolist() or gate["R"] != r.tolist() or gate["Qf"] != qf.tolist():
        raise ValueError("Weights changed after admission")
    local, raw = local.resolve(), raw.resolve()
    if local.exists() or local.is_relative_to(ROOT) or local.is_relative_to(raw):
        raise ValueError("Use a fresh raw directory outside Git and historical sources")
    if (
        len(cfg["jobs"]) != cfg["maximum_new_nominal_executions"]
        or len(set(cfg["jobs"])) != 6
    ):
        raise ValueError("The approved six-task roster changed")
    original = {
        row["job_id"]: row
        for row in read_csv(ROOT / "results/stage6ds/planning_runs.csv")
    }
    cache: dict[str, OccupancyMap] = {}
    sources = {job: source(job, raw, cache) for job in cfg["jobs"]}
    for job in cfg["jobs"]:
        if not boolean(original[job]["model_feasible"]):
            raise ValueError("Selected source lacks the frozen M_final certificate")
    local.mkdir(parents=True)
    save_json(
        local / "invocation.json",
        {
            "argv": sys.argv,
            "protocol": cfg,
            "source_root": str(raw),
            "admission": str(admission.resolve()),
            "head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
        },
        exclusive=True,
    )
    ledger: list[dict[str, Any]] = [
        {"job_id": job, "run_state": "not_run", "success": None} for job in cfg["jobs"]
    ]
    save_json(PUBLIC / "execution_ledger.json", ledger, exclusive=True)
    results = []
    for index, job in enumerate(cfg["jobs"]):
        folder = local / job
        folder.mkdir()
        case, record, references, inputs = sources[job]
        ledger[index]["run_state"] = "started"
        save_json(PUBLIC / "execution_ledger.json", ledger)
        started = time.perf_counter()
        try:
            gains, _ = riccati(
                [
                    jacobians(s, u, limits.step)
                    for s, u in zip(references[:-1], inputs, strict=True)
                ],
                q,
                r,
                qf,
            )
            setup_s = time.perf_counter() - started
            summary, trace = execute(
                case,
                references,
                inputs,
                gains,
                limits,
                started + cfg["execution_wall_budget_s"],
            )
            # Save the actual new sequence once, before the independent audit can fail.
            save_record(
                folder / "execution.json.gz", {"summary": summary, "trace": trace}
            )
            proof = certify(case, trace)
            elapsed = time.perf_counter() - started
            old_planning = float(original[job]["best_independent_certificate_s"])
            within_budget = (
                elapsed <= cfg["execution_wall_budget_s"]
                and old_planning + elapsed <= cfg["pipeline_budget_s"]
            )
            success = bool(
                summary["online_strict_success"]
                and proof["full_margin_safe"]
                and proof["goal_reached"]
                and within_budget
            )
            if summary["online_strict_success"] and not (
                proof["full_margin_safe"] and proof["goal_reached"]
            ):
                raise RuntimeError(
                    "Strict safety false positive; stop all later executions"
                )
            if (
                summary["maximum_reference_position_error_m"] > 1e-10
                or summary["maximum_reference_angle_error_rad"] > 1e-12
                or summary["maximum_feedforward_difference_rad_s"] > 1e-12
            ):
                raise RuntimeError(
                    "Zero-error nominal source consistency failed; stop batch"
                )
            saved = {
                "job_id": job,
                "source_record": f"search/{job}/independent_record.json.gz",
                "run_state": "completed",
                "success": success,
                "method": "LTV-LQR",
                "data_kind": "new_nominal_zero_initial_error_no_disturbance",
                "setup_wall_s": setup_s,
                "execution_and_certification_wall_s": elapsed,
                "original_planning_certificate_wall_s": old_planning,
                "combined_wall_s": old_planning + elapsed,
                "within_frozen_budgets": within_budget,
                "native_source_intervals": len(inputs),
                "historical_native_success": record["audit"]["model_feasible"],
                "historical_los_success": record["tracking"]["execution_success"],
                "historical_los_reason": record["tracking"]["failure_reason"],
                "failure_reason": summary["termination_reason"]
                if within_budget
                else "execution_or_pipeline_deadline",
                **summary,
                "independent_certificate": proof,
            }
            save_json(folder / "result.json", saved, exclusive=True)
            ledger[index] = {
                "job_id": job,
                "run_state": "completed",
                "success": success,
            }
            results.append(saved)
            print(
                f"{index + 1}/6 {job}: success={success}, wall={elapsed:.3f}s",
                flush=True,
            )
        except Exception as error:
            diagnostic = {
                "job_id": job,
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "elapsed_s": time.perf_counter() - started,
            }
            save_json(folder / "exception.json", diagnostic, exclusive=True)
            ledger[index] = {"job_id": job, "run_state": "exception", "success": False}
            save_json(PUBLIC / "execution_ledger.json", ledger)
            save_json(PUBLIC / "blocked.json", diagnostic, exclusive=True)
            raise
        save_json(PUBLIC / "execution_ledger.json", ledger)
        save_json(PUBLIC / "execution_results.json", results)
    result = {
        "registered": 6,
        "executed": len(results),
        "strict_successes": sum(r["success"] for r in results),
        "new_planning_searches": 0,
        "new_ltv_executions": len(results),
        "additional_independent_certifications": len(results),
        "new_los_executions": 0,
        "new_native_open_performance_replays": 0,
    }
    save_json(PUBLIC / "execution_summary.json", result, exclusive=True)
    return result


def main() -> None:
    """Require explicit source/output paths and the audited six-execution intent."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--local-root", type=Path, required=True)
    parser.add_argument("--admission", type=Path, default=PUBLIC / "admission")
    parser.add_argument("--execute-six", action="store_true", required=True)
    args = parser.parse_args()
    print(run(args.raw_root, args.local_root, args.admission))


if __name__ == "__main__":
    main()
