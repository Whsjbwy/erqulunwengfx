"""Analytic acceptance before real-scene diagnostics."""

import pytest

from gsunlight_repro.stage5ar.p0 import run_case


@pytest.mark.parametrize("case", [f"T{i:02d}" for i in range(1, 9)])
def test_predeclared_analytic_case(case: str) -> None:
    assert run_case(case)["status"] == "passed"
