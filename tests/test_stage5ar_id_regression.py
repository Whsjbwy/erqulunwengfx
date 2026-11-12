"""Regression: flattening must not overwrite same-source global path IDs."""

from gsunlight_repro.stage5ar.analysis import shortcut_rows


def test_shortcut_csv_preserves_global_source_and_derived_ids() -> None:
    source, derived = "job::p7", "job::p7::shortcut-v1"
    raw = {
        "job_id": "job",
        "scene": "S",
        "family": "ordinary",
        "mode": "body",
        "method": "rrt_star",
        "seed": 0,
        "path_id": 7,
        "path_uid": source,
        "primary_class": "success",
        "execution_success": True,
        "nominal_body_valid": True,
    }
    pair = {
        "job_id": "job",
        "raw_path_id": source,
        "shortcut_source_id": source,
        "shortcut_path_id": derived,
        "source_indices": [0, 1],
        "raw": raw,
        "shortcut": raw | {"path_uid": derived},
    }
    row = shortcut_rows([pair])[0]
    assert row["raw_path_id"] == row["shortcut_source_id"] == source
    assert row["shortcut_path_id"] == derived
