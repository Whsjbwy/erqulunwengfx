"""A corrupted replay metric must fail independent reconstruction."""

import copy

import pytest

from gsunlight_repro.stage5a.maps import read_config
from gsunlight_repro.stage5ar.audit import check_trace
from gsunlight_repro.stage5ar.p0 import BASELINE, empty_scene
from gsunlight_repro.stage5ar.replay import replay


def test_metrics_and_rk4_steps_reconstruct_and_corruption_is_rejected() -> None:
    protocol = read_config("stage5a_protocol.json")
    scene = empty_scene()
    result = replay([scene.start, scene.goal], scene, protocol, 0, BASELINE)
    record = {"summary": result.summary, "trace": result.trace}
    audit = check_trace(record, protocol["kinematics"])
    assert audit["rk4_steps"] == 3 and audit["max_rk4_error_m"] < 1e-10
    changed = copy.deepcopy(record)
    changed["summary"]["rms_tracking_error_m"] = 99.0
    with pytest.raises(ValueError, match="reconstruct"):
        check_trace(changed, protocol["kinematics"])
