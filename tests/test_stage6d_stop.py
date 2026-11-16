"""A known mapping conflict must prevent any performance search."""

from pathlib import Path

import pytest

from gsunlight_repro.stage6d.common import save_json
from gsunlight_repro.stage6d.planning import run


def test_mapping_conflict_blocks_search_despite_passing_witness_flag(
    tmp_path: Path,
) -> None:
    save_json(
        tmp_path / "model_mapping_failure.json", {"model_mapping_gate_passed": False}
    )
    save_json(tmp_path / "d2_witness_acceptance.json", {"passed": True})
    with pytest.raises(RuntimeError, match="BLOCKED"):
        run(
            tmp_path / "missing.exe",
            tmp_path / "dependency",
            tmp_path / "raw",
            tmp_path,
        )
    assert not (tmp_path / "raw").exists()
