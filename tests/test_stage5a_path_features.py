"""Describe geometric demand without assigning finite curvature to a corner."""

from gsunlight_repro.stage5a.path_features import describe_path


def test_right_angle_and_vertical_edges_are_reported_as_such() -> None:
    path = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (2, 0, 1)]
    features = describe_path(path, path[0], path[-1])
    assert features["max_segment_pitch_deg"] == 90
    assert features["max_corner_turn_deg"] == 90
    assert features["nonzero_segments"] == 3
    assert features["initial_yaw_mismatch_deg"] == 0


def test_zero_length_path_and_undefined_vertical_heading_are_explicit() -> None:
    point = (1, 1, 1)
    assert describe_path([point, point], point, point)["max_segment_pitch_deg"] is None
    assert (
        describe_path([point, (1, 1, 3)], point, (1, 1, 3))["initial_yaw_mismatch_deg"]
        is None
    )
