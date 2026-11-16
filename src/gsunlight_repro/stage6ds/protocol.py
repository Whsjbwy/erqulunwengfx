"""Exact inherited inputs and explicit clocks for the fixed54 development jobs."""

from __future__ import annotations

from typing import Any

from ..stage5a.maps import read_config
from ..stage6c.common import read_json
from ..stage6d.maps import roster
from . import BINARY_ID, PUBLIC


def frozen() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Reject any configuration drift against the pre-experiment snapshot."""
    protocol = read_config("stage6d_protocol.json")
    cfg, tasks = protocol["d2"], roster(protocol)
    if (
        cfg != read_json(PUBLIC / "inherited_protocol.json")
        or tasks != read_json(PUBLIC / "search_manifest.json")
        or len(tasks) != 54
    ):
        raise ValueError("Frozen6D protocol or roster changed")
    return cfg, tasks


def request_for(task: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    """Expose initial/goal/geometry to the planner, never supplied witness inputs."""
    cfg, _ = frozen()
    return {
        "mode": "plan",
        "algorithm": task["algorithm"],
        "search_mode": task["mode"],
        "seed": task["seed"],
        "scenario": scene,
        "search_budget_s": cfg["search_cap_s"],
        **{
            key: cfg[key]
            for key in (
                "selection_radius",
                "pruning_radius",
                "goal_bias",
                "propagation_min_steps",
                "propagation_max_steps",
            )
        },
    }


def check_identity(identity: dict[str, Any], task: dict[str, Any]) -> None:
    """Validate measured real planner settings and signed SI probes."""
    cfg, _ = frozen()
    settings = identity["actual_settings"]
    if (
        identity["binary_id"] != BINARY_ID
        or not identity["planner_si_same_object"]
        or identity["official_class"]
        != (
            "ompl::control::RRT" if task["algorithm"] == "rrt" else "ompl::control::SST"
        )
        or settings["goal_bias"] != cfg["goal_bias"]
        or identity["search_mode"] != task["mode"]
        or identity["objective"] != "official ControlDurationObjective"
        or identity["cost_threshold"]
        != (0.0 if task["mode"] == "anytime" else "infinity")
        or len(identity["signed_probes"]) != 2
    ):
        raise ValueError("Actual planner identity/stopping policy differs")
    if task["algorithm"] == "sst" and any(
        settings[key] != cfg[key] for key in ("selection_radius", "pruning_radius")
    ):
        raise ValueError("Actual SST radii differ from the inherited protocol")
    for row in identity["signed_probes"]:
        if not row["inside"]["si_is_valid"] or row["outside"]["si_is_valid"]:
            raise ValueError("Actual planner signed numerical contract failed")
