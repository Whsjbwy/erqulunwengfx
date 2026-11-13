"""One preregistered resource-confound recheck, separate from the primary matrix."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np

from ..stage4a.runtime import configure_worker
from ..stage5a.analysis import write_csv
from ..stage5a.maps import body_radius, read_config
from ..stage5a.planners import plan
from ..stage5ar.audit import check_trace
from ..stage5ar.evidence import path_features
from ..stage5ar.replay import Replay
from ..stage5ar.runner import shortcut
from .analysis import flatten
from .audit import check_safety
from .diagnostics import detail
from .maps import generate
from .runtime import experiment_lock
from .storage import Records, public_output, write_json
from .tracking import simulate


def recheck(local: Path, old: Path, output: Path) -> dict:
    """Run the declared single repeat once; never replace a primary result."""
    if not (local / "formal_completed.json").exists():
        raise ValueError("Finish the original matrix before the resource recheck")
    output = public_output(output)
    amendment = read_config("stage5ae_resource_recheck.json")
    config = json.loads((local / "configuration.json").read_text(encoding="utf-8"))
    chosen = read_config("stage5ae_selected.json")["chosen"]
    directory = local / "resource_recheck"
    with experiment_lock(local):
        directory.mkdir(exist_ok=False)
        configure_worker()
        spec = next(
            spec for spec in config["maps"]["maps"] if spec["id"] == amendment["scene"]
        )
        scene = generate(spec, config["maps"])
        random.seed(amendment["seed"])
        np.random.seed(amendment["seed"])
        search = plan(
            scene,
            amendment["method"],
            amendment["seed"],
            amendment["mode"],
            config["vehicle"],
            seconds=amendment["planning_budget_s"],
            step=amendment["step_m"],
        )
        write_json(directory / "planning.json", search)
        raw = (
            search["paths"][search["raw_path_id"]]
            if search["raw_path_id"] is not None
            else None
        )
        rows, reference_checks = [], []
        primary = Records(local, old)
        records = Records(directory, old)
        if raw is not None:
            if not scene.geometry(body_radius(config["vehicle"])).path(raw).valid:
                raise ValueError("Resource recheck returned unsafe raw geometry")
            started = time.perf_counter()
            shortened, indices = shortcut(raw, scene, body_radius(config["vehicle"]))
            write_json(
                directory / "processing.json",
                {
                    "shortcut": shortened,
                    "source_indices": indices,
                    "processing_cost_s": time.perf_counter() - started,
                },
            )
            for controller in (config["protocol"]["legacy"], chosen):
                for processing, path in (("raw", raw), ("shortcut", shortened)):
                    source = (
                        amendment["job_id"]
                        + "--"
                        + processing
                        + "--"
                        + controller["id"]
                    )
                    identity = "resource_recheck_" + source
                    trace_source = (
                        "resource_recheck_"
                        + amendment["job_id"]
                        + "--raw--"
                        + controller["id"]
                        if processing == "shortcut" and path == raw
                        else None
                    )
                    if trace_source is not None:
                        previous = records.read(trace_source)
                        result = Replay(previous["summary"], previous["trace"])
                    else:
                        result = simulate(
                            path, scene, config["vehicle"], 0.0, controller
                        )
                    if result.summary["primary_class"] == "resource_timeout":
                        write_json(directory / "error.json", result.summary)
                        raise RuntimeError(
                            "Recheck execution guard reached; do not repeat"
                        )
                    extras, _ = detail(
                        result, path, scene, body_radius(config["vehicle"])
                    )
                    meta = {
                        "case_id": identity,
                        "primary_case_id": source,
                        "job_id": "resource_recheck_" + amendment["job_id"],
                        "scene": scene.specification["id"],
                        "family": scene.specification["family"],
                        "method": amendment["method"],
                        "mode": "body",
                        "seed": 0,
                        "processing": processing,
                        "controller": controller["id"],
                        "phase": "resource_recheck",
                    }
                    record = {
                        "meta": meta,
                        "summary": {
                            **result.summary,
                            **path_features(path, scene, config["vehicle"], "body"),
                            **extras,
                        },
                    }
                    record.update(
                        {"trace_reference": trace_source}
                        if trace_source
                        else {"trace": result.trace}
                    )
                    records.save(identity, record)
                    record = records.read(identity)
                    reference_checks.append(
                        check_trace(record, config["vehicle"]["kinematics"])
                    )
                    check_safety(record, path, scene, config["vehicle"])
                    rows.append(
                        {
                            **flatten(record),
                            "primary_execution_success": primary.read(source)[
                                "summary"
                            ]["execution_success"],
                        }
                    )
        result = {
            "status": "completed",
            "primary_matrix_replaced": False,
            "original_job_id": amendment["job_id"],
            "extra_searches": 1,
            "geometry_success": raw is not None,
            "execution_conditions": len(rows),
            "maximum_rk4_error_m": max(
                (row["max_rk4_error_m"] for row in reference_checks), default=None
            ),
            "search": {
                key: value
                for key, value in search.items()
                if key not in ("paths", "history", "raw_history", "checkpoints")
            },
        }
        write_json(directory / "completed.json", result)
        write_json(output / "resource_recheck.json", result)
        write_csv(output / "resource_recheck_runs.csv", rows)
        return result


def main() -> None:
    """Perform only the recorded operational recheck, with no tuning or retries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--old-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ae"))
    args = parser.parse_args()
    print(json.dumps(recheck(args.local_dir, args.old_evidence, args.output)))


if __name__ == "__main__":
    main()
