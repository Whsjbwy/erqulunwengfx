"""Guard against inflating scientific path quality with invalid or missing paths."""

from gsunlight_repro.summarize import aggregate


def test_only_strict_valid_lengths_contribute_to_quality() -> None:
    base = {
        "scene_id": "S1",
        "method": "synthetic",
        "reported_success": "True",
        "search_seconds": "1",
        "failure_categories": "[]",
        "termination_reason": "found",
        "budget_valid_success": "False",
        "common_post_valid": "",
        "status": "ok",
    }
    rows = [
        {**base, "strict_valid": "True", "raw_path_length": "10"},
        {**base, "strict_valid": "False", "raw_path_length": "1"},
        {
            **base,
            "strict_valid": "",
            "raw_path_length": "",
            "reported_success": "",
            "search_seconds": "",
            "status": "timeout",
        },
    ]
    summaries, _ = aggregate(rows)
    summary = summaries[0]
    assert summary["runs"] == 3
    assert summary["strict_valid_paths"] == 1
    assert summary["strict_invalid_paths"] == 1
    assert summary["no_path_evidence"] == 1
    assert summary["reported_unknown"] == 1
    assert summary["valid_raw_length_mean"] == 10
    assert summary["search_seconds_observed"] == 2
