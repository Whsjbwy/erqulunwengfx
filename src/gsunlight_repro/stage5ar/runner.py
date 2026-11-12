"""Sequential gated P0-P3 replay with resumable single-copy local traces."""

from __future__ import annotations

import argparse
import gzip
import json
import logging
from dataclasses import asdict
from pathlib import Path

from ..stage4a.runtime import configure_worker
from ..stage5a.maps import ROOT, body_radius, load_scene, mode_radius, read_config
from ..stage5a.tracking import track
from .evidence import (
    compare_public,
    freeze_manifest,
    inventory,
    load_history,
    path_features,
    protect_output,
    read_manifest,
    select_pilot,
)
from .p0 import run_all
from .reference import sampled_curve_evidence
from .replay import Replay, compare_frozen, replay
from .storage import read_record

LOGGER = logging.getLogger(__name__)


def write_json(path: Path, data: dict | list) -> None:
    """Create immutable evidence; never silently overwrite an earlier run."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)


def shortcut(path: list, scene, radius: float) -> tuple[list, list[int]]:
    """Apply one fixed farthest-visible vertex pass to this exact raw path."""
    geometry = scene.geometry(radius)
    if not geometry.path(path).valid:
        raise ValueError("Raw path is invalid at its original planning radius")
    indices, current = [0], 0
    while current < len(path) - 1:
        chosen = current + 1
        for candidate in range(len(path) - 1, current, -1):
            if geometry.segment(path[current], path[candidate]).valid:
                chosen = candidate
                break
        indices.append(chosen)
        current = chosen
    result = [path[index] for index in indices]
    if not geometry.path(result).valid:
        raise RuntimeError("Derived shortcut failed complete geometry certification")
    return result, indices


class Runner:
    """Own gates and immutable traces, keeping public tables independently derived."""

    def __init__(self, history: Path, local: Path, output: Path) -> None:
        self.history, self.local, self.output = (
            history.resolve(),
            local.resolve(),
            protect_output(output),
        )
        if (
            self.local.is_relative_to(ROOT)
            or self.local == self.history
            or self.local.is_relative_to(self.history)
            or self.history.is_relative_to(self.local)
        ):
            raise ValueError(
                "New full evidence must be separate from repository/history"
            )
        self.local.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        self.protocol = read_config("stage5ar_protocol.json")
        self.config, items = load_history(self.history)
        self.items = {item["row"]["job_id"]: item for item in items}
        self.scenes = {}
        frozen = self.local / "configuration.json"
        configuration = {"diagnostic": self.protocol, "historical": self.config}
        if frozen.exists():
            if json.loads(frozen.read_text(encoding="utf-8")) != configuration:
                raise ValueError("Frozen diagnostic configuration changed")
        else:
            write_json(frozen, configuration)

    def require_gate(self, name: str) -> None:
        """Refuse to start the next phase on an absent or failed gate."""
        marker = self.local / f"{name}_completed.json"
        if (
            not marker.exists()
            or not json.loads(marker.read_text(encoding="utf-8"))["passed"]
        ):
            raise ValueError(f"Phase requires completed {name} gate")

    def finish(self, phase: str, count: int) -> None:
        """Record a successful gate only after every registered replay finishes."""
        marker = self.local / f"{phase}_completed.json"
        if not marker.exists():
            write_json(marker, {"phase": phase, "passed": True, "replays": count})

    def scene(self, scene_id: str):
        """Reuse immutable map arrays across sequential replays."""
        if scene_id not in self.scenes:
            self.scenes[scene_id] = load_scene(scene_id, self.config["maps"])
        return self.scenes[scene_id]

    def phase_p0(self) -> None:
        """Run all analytic cases without using the held-out scenes."""
        path = self.output / "p0_analytic_results.json"
        if path.exists():
            self.require_gate("p0")
            return
        write_json(path, run_all())
        self.finish("p0", 8)

    def freeze(self) -> None:
        """Freeze full inventory and sampling before any controlled replay."""
        self.require_gate("p0")
        rows = select_pilot(
            inventory(
                list(self.items.values()), self.config, self.protocol["protocol_id"]
            ),
            self.protocol["pilot_per_family"],
        )
        audit = compare_public(
            list(self.items.values()), ROOT / "results/stage5a/runs.csv"
        )
        freeze_manifest(self.output / "sampling_manifest.csv", rows)
        write_json(self.output / "historical_csv_audit.json", audit)
        self.finish("manifest", sum(row["is_selected"] for row in rows))
        LOGGER.info(
            "Frozen manifest: %s pilot, %s expanded paths",
            sum(row["is_selected"] for row in rows),
            sum(row["in_expansion"] for row in rows),
        )

    def selected(self, pilot: bool = False) -> list[dict]:
        """Read frozen selected identities, never rerank using new outcomes."""
        self.require_gate("manifest")
        rows = read_manifest(self.output / "sampling_manifest.csv")
        key = "is_selected" if pilot else "in_expansion"
        return [row for row in rows if row[key]]

    def execute(
        self,
        row: dict,
        path_id: int,
        path: list,
        condition: dict,
        variant: str = "selected",
        extra: dict | None = None,
    ) -> Replay:
        """Run once or reuse exactly matching evidence, with no silent retry."""
        identity = {
            key: row[key]
            for key in ("job_id", "scene", "family", "mode", "method", "seed")
        }
        identity.update(
            path_id=path_id,
            path_uid=f"{row['job_id']}::p{path_id}",
            variant=variant,
            condition_id=condition["id"],
            version=self.protocol["protocol_id"],
            protocol_id=self.protocol["protocol_id"],
        )
        identity.update(extra or {})
        if variant == "shortcut":
            identity["path_uid"] = identity["shortcut_path_id"]
        directory = self.local / "replays"
        directory.mkdir(exist_ok=True)
        name = f"{row['job_id']}--{variant}-p{path_id}--{condition['id']}.json.gz"
        target = directory / name
        specification = {"identity": identity, "condition": condition}
        if target.exists():
            previous = read_record(target)
            if previous["specification"] != specification:
                raise ValueError("Existing replay differs from requested condition")
            return Replay(previous["summary"], previous["trace"])
        # The same task may publish the same coordinates as selected/raw/shortcut.
        # Reuse the verified baseline trace instead of simulating/storing it again.
        if condition["id"] == "baseline" and variant != "selected":
            item = self.items[row["job_id"]]
            selected_id = item["row"]["selected_path_id"]
            selected_path = item["paths"][selected_id]
            source_variant = "selected" if path == selected_path else "raw"
            source_id = selected_id if source_variant == "selected" else path_id
            same_raw = path == item["paths"][item["row"]["raw_path_id"]]
            if path == selected_path or (variant == "shortcut" and same_raw):
                reference = (
                    f"{row['job_id']}--{source_variant}-p{source_id}--baseline.json.gz"
                )
                previous = read_record(directory / reference)
                result = Replay({**previous["summary"], **identity}, previous["trace"])
                with gzip.open(target, "xt", encoding="utf-8") as stream:
                    json.dump(
                        {
                            "specification": specification,
                            "summary": result.summary,
                            "trace_reference": reference,
                        },
                        stream,
                        allow_nan=False,
                    )
                return result
        scene = self.scene(row["scene"])
        protocol = self.config["protocol"]
        margin = (
            protocol["vehicle"]["safety_margin_m"] if row["mode"] == "margin" else 0.0
        )
        result = replay(path, scene, protocol, margin, condition)
        if result.summary["primary_class"] == "resource_timeout":
            write_json(self.local / (name + ".error.json"), result.summary)
            raise RuntimeError(
                "Resource timeout: preserve error and review before retry"
            )
        if condition["id"] == "baseline":
            compare_frozen(result.summary, track(path, scene, protocol, margin))
            if variant == "selected":
                compare_frozen(
                    result.summary,
                    self.items[row["job_id"]]["executions"][str(path_id)],
                )
        if result.trace and result.summary["primary_class"] in (
            "swept_safety_reject",
            "mission_band_reject",
            "margin_only_failure",
        ):
            event_name = (
                "margin"
                if result.summary["primary_class"] == "margin_only_failure"
                else "physical"
                if result.summary["primary_class"] == "swept_safety_reject"
                else "mission"
            )
            event = next(
                step for step in result.trace if step[event_name + "_reason"] != "ok"
            )
            result.summary.update(
                sampled_curve_evidence(event, scene, body_radius(protocol))
            )
            result.summary["reference_event"] = event_name
        result.summary = {
            **identity,
            **condition,
            **path_features(path, scene, protocol, row["mode"]),
            **result.summary,
        }
        with gzip.open(target, "xt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(
                {"specification": specification, **asdict(result)},
                stream,
                allow_nan=False,
            )
        LOGGER.info(
            "%s %s %s %s t=%.1f",
            row["scene"],
            condition["id"],
            variant,
            result.summary["primary_class"],
            result.summary.get("simulation_time_s", 0),
        )
        return result

    def p1(self, pilot: bool) -> None:
        """Replay the pilot before expanding to the entire registered inventory."""
        self.require_gate("p0")
        if not pilot:
            self.require_gate("pilot")
        rows = self.selected(pilot)
        for row in rows:
            item = self.items[row["job_id"]]
            self.execute(
                row,
                row["path_id"],
                item["paths"][row["path_id"]],
                self.protocol["conditions"][0],
            )
        self.finish("pilot" if pilot else "p1", len(rows))

    def p2(self) -> None:
        """Replay every expanded path under every preregistered single factor."""
        self.require_gate("p1")
        rows = self.selected()
        for condition in self.protocol["conditions"][1:]:
            for row in rows:
                item = self.items[row["job_id"]]
                self.execute(
                    row, row["path_id"], item["paths"][row["path_id"]], condition
                )
        self.finish("p2", len(rows) * len(self.protocol["conditions"]))

    def p3(self) -> None:
        """Keep same-source raw and derived shortcut provenance for every task."""
        self.require_gate("p2")
        pairs = []
        for row in self.selected():
            item = self.items[row["job_id"]]
            path_id = item["row"]["raw_path_id"]
            raw = item["paths"][path_id]
            scene = self.scene(row["scene"])
            shortened, indices = shortcut(
                raw, scene, mode_radius(row["mode"], self.config["protocol"])
            )
            source_id = f"{row['job_id']}::p{path_id}"
            extra = {
                "raw_path_id": source_id,
                "shortcut_source_id": source_id,
                "shortcut_path_id": source_id + "::shortcut-v1",
            }
            outcomes = []
            for variant, path in (("raw", raw), ("shortcut", shortened)):
                result = self.execute(
                    row, path_id, path, self.protocol["conditions"][0], variant, extra
                )
                outcomes.append(result.summary)
            pairs.append(
                {
                    "job_id": row["job_id"],
                    **extra,
                    "source_indices": indices,
                    "shortcut_coordinates": shortened,
                    "raw": outcomes[0],
                    "shortcut": outcomes[1],
                }
            )
        path = self.local / "shortcut_pairs.json"
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != json.loads(
                json.dumps(pairs)
            ):
                raise ValueError("Existing shortcut pairs differ")
        else:
            write_json(path, pairs)
        self.finish("p3", 2 * len(pairs))


def main() -> None:
    """Execute a named gate; all full evidence stays outside the repository."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("p0", "freeze", "pilot", "p1", "p2", "p3"), required=True
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--local-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/stage5ar"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    configure_worker()
    runner = Runner(args.history, args.local_dir, args.output)
    if args.phase == "p0":
        runner.phase_p0()
    elif args.phase == "freeze":
        runner.freeze()
    elif args.phase in ("pilot", "p1"):
        runner.p1(args.phase == "pilot")
    elif args.phase == "p2":
        runner.p2()
    else:
        runner.p3()


if __name__ == "__main__":
    main()
