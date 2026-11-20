"""Check review provenance and unrun accounting without simulating a vehicle."""

from __future__ import annotations

import argparse
import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..stage5a.maps import ROOT
from ..stage7b0.public_evidence import validate as validate_history

PUBLIC = ROOT / "results/stage8a"


@dataclass(frozen=True)
class GateEvidence:
    """Human-reviewed evidence flags, not an automated novelty assessment."""

    equivalent_mechanism_verified: bool
    key_method_unknown: bool
    difference_verified: bool


def gate_status(evidence: GateEvidence) -> str:
    """Enforce the taskbook's stop rules before any model implementation."""
    if any(type(value) is not bool for value in vars(evidence).values()):
        raise ValueError("Gate evidence must use explicit booleans")
    if evidence.difference_verified and (
        evidence.equivalent_mechanism_verified or evidence.key_method_unknown
    ):
        raise ValueError("A verified difference conflicts with unresolved evidence")
    if evidence.equivalent_mechanism_verified:
        return "PIVOT"
    if evidence.key_method_unknown or not evidence.difference_verified:
        return "NEED_MORE_EVIDENCE"
    return "PASS"


def load_json(path: Path) -> Any:
    """Read UTF-8 research records and propagate malformed-file errors."""
    return json.loads(path.read_text(encoding="utf-8"))


def check_sources(papers: list[dict[str, Any]]) -> None:
    """Reject missing identities or a false claim of full-text verification."""
    if len(papers) < 8:
        raise ValueError("At least eight real method papers must be reviewed")
    ids = [paper["id"] for paper in papers]
    dois = [paper["doi"].lower() for paper in papers]
    if len(set(ids)) != len(ids) or len(set(dois)) != len(dois):
        raise ValueError("Duplicate paper identity")
    for paper in papers:
        for field in (
            "authors",
            "title",
            "venue",
            "doi",
            "doi_verification",
            "sections_read",
            "flow_knowledge",
            "gradient_time_bounds",
            "model_controls",
            "certificate",
            "experiments",
            "overlap",
            "unknown",
            "license",
            "windows_run",
            "checked_on",
        ):
            if not paper.get(field):
                raise ValueError(f"Missing provenance: {paper['id']}/{field}")
        if paper["access"] not in {
            "full_method",
            "full_method_preprint",
            "abstract_only",
            "prior_full_current_abstract",
        }:
            raise ValueError("Unrecognized method-access status")
        if not paper["doi"].startswith("10."):
            raise ValueError("Invalid DOI identifier")
        for field in ("official_url", "method_url"):
            parsed = urlparse(paper[field])
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError("Source URL must identify an HTTPS host")


def table_text(rows: list[dict[str, Any]]) -> str:
    """Serialize a small audit table with explicit column order."""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def demonstration_rows(case_families: list[str]) -> list[dict[str, Any]]:
    """Reserve six taskbook families; blank measurements mean never executed."""
    return [
        {
            "case_id": index,
            "case_family": family,
            "run_state": "not_run_gate_A",
            "reason": "NEED_MORE_EVIDENCE: model development not admitted",
            "control_sequence": None,
            "flow_parameters": None,
            "flow_bounds": None,
            "final_state": None,
            "success": None,
            "first_rejected_interval": None,
            "minimum_clearance_m": None,
            "integration_error_m": None,
            "wall_s": None,
            "execution_command": None,
        }
        for index, family in enumerate(case_families, start=1)
    ]


def validate(root: Path = ROOT) -> dict[str, Any]:
    """Verify saved records and denominators, without accessing external sources."""
    config = load_json(root / "configs/stage8a_review.json")
    public = root / "results/stage8a"
    papers = load_json(public / "literature_sources.json")
    decision = load_json(public / "decision.json")
    check_sources(papers)
    candidate = config["candidate"]
    evidence = GateEvidence(
        **{name: candidate[name] for name in GateEvidence.__annotations__}
    )
    if gate_status(evidence) != decision["gate_A"]:
        raise ValueError("Decision does not follow the recorded gate evidence")
    sources = {paper["id"]: paper for paper in papers}
    if any(
        sources[key]["access"] not in {"full_method", "full_method_preprint"}
        for key in candidate["nearest_sources"]
    ):
        raise ValueError("Nearest-method analysis must identify actual method text")
    if len(candidate["nearest_sources"]) not in (2, 3):
        raise ValueError("Use two or three closest methods")
    if not any(
        sources[key]["access"] in {"abstract_only", "prior_full_current_abstract"}
        for key in candidate["critical_sources"]
    ):
        raise ValueError("The documented access blocker no longer matches the sources")
    expected = {
        "project_decision": "BLOCKED",
        "gate_A": "NEED_MORE_EVIDENCE",
        "gate_B": "NOT_ENTERED",
        "papers_reviewed": len(papers),
        "papers_2023_2026": sum(2023 <= p["year"] <= 2026 for p in papers),
        "candidates_retained": 1,
        "candidate_admitted": False,
        "case_families_reserved": 6,
        "new_model_demonstrations": 0,
        "not_run_gate_A": 6,
        "new_planning_searches": 0,
        "new_trajectory_replays": 0,
        "success_rate": None,
        "flow_model_correctness_established": False,
        "continuous_flow_safety_established": False,
        "robustness_established": False,
        "original_algorithm_authorized": False,
        "stop_for_review": True,
    }
    if any(decision[key] != value for key, value in expected.items()):
        raise ValueError("Unrun accounting or scientific scope changed")
    if len(config["case_families"]) != 6 or len(set(config["case_families"])) != 6:
        raise ValueError("The six taskbook case families changed")
    tables = {
        "literature.csv": table_text(papers),
        "demonstrations.csv": table_text(demonstration_rows(config["case_families"])),
    }
    for name, expected_text in tables.items():
        if (public / "tables" / name).read_text(encoding="utf-8") != expected_text:
            raise ValueError(f"Audit CSV differs from reviewed source: {name}")
    return {
        "passed": True,
        "gate_A": decision["gate_A"],
        "project_decision": decision["project_decision"],
        "papers": len(papers),
        "unrun_case_families": 6,
        "new_model_or_planning_trials": 0,
        "scope": "metadata/gate/accounting only, not model or novelty certification",
    }


def main() -> None:
    """Export once or validate; neither mode provides an experiment entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-tables", action="store_true")
    args = parser.parse_args()
    if args.export_tables:
        config = load_json(ROOT / "configs/stage8a_review.json")
        papers = load_json(PUBLIC / "literature_sources.json")
        check_sources(papers)
        tables = PUBLIC / "tables"
        tables.mkdir(exist_ok=False)
        for name, rows in {
            "literature.csv": papers,
            "demonstrations.csv": demonstration_rows(config["case_families"]),
        }.items():
            with (tables / name).open("x", encoding="utf-8", newline="") as stream:
                stream.write(table_text(rows))
    validate_history()
    print(json.dumps(validate(), ensure_ascii=False))


if __name__ == "__main__":
    main()
