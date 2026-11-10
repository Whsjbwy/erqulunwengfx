"""Protect original computation while adding observations and bounded orchestration."""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from gsunlight_repro.author_worker import author_termination, execute_author
from gsunlight_repro.experiment_runner import WorkerClient, parse_arguments


@pytest.fixture
def synthetic_source(tmp_path: Path) -> Path:
    """Create independently written source with candidate and capacity operations."""
    source = tmp_path / "synthetic_author"
    source.mkdir()
    (source / "utils.py").write_text(
        "import random,numpy as np\n"
        "def showpoint(*args): pass\n"
        "showline=showline1=showdashedline=showvoxel=showpoint\n"
        "def findtangent(empty):\n"
        "    if empty: return np.empty((0,4))\n"
        "    return np.array([[random.random(),np.random.random(),0.,0.],"
        "[1.,1.,1.,1.]])\n",
        encoding="utf-8",
    )
    (source / "main_sunlight_3Dgrid.py").write_text(
        "import time,random,numpy as np\n"
        "from utils import *\n"
        "time_start=time.time()\n"
        "first=findtangent(False)\nsecond=findtangent(True)\n"
        "grids_ids=[0,1]\nmax_num=1\n"
        "if len(grids_ids)>max_num:\n"
        "    draw=random.randint(1,len(grids_ids)-1)\n"
        "path=np.array([[first[0,0],first[0,1],draw],"
        "[random.random(),np.random.random(),0.]])\n"
        "path1=path.copy()\npaths=[path]\npaths_lengths=[1.]\n"
        "Closeset=[0,1,2]\nOpenset=[3]\nAllset=path\niter=2\nmax_iter=100\n"
        "time_end=time.time()\n",
        encoding="utf-8",
    )
    (source / "map.vti").touch()
    return source


def fake_pyvista(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Provide display/read attributes without loading a real map or window."""
    module = ModuleType("pyvista")
    module.read = object()
    module.Plotter = object()
    monkeypatch.setitem(sys.modules, "pyvista", module)
    return module


def test_observers_preserve_rng_draws_and_expose_counters(
    synthetic_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each original RNG call executes once and all observed outputs stay intact."""
    fake_pyvista(monkeypatch)
    original_randint = random.randint
    calls = []

    def observed_draw(first: int, last: int) -> int:
        calls.append((first, last))
        return original_randint(first, last)

    monkeypatch.setattr(random, "randint", observed_draw)
    result = execute_author(
        synthetic_source, synthetic_source / "map.vti", object(), 11, "author_original"
    )
    expected_python = random.Random(11)
    expected_numpy = np.random.RandomState(11)
    expected_first = [expected_python.random(), expected_numpy.random_sample()]
    expected_draw = expected_python.randint(1, 1)
    expected_next = [expected_python.random(), expected_numpy.random_sample(), 0.0]
    np.testing.assert_array_equal(
        result["raw_path"], [[*expected_first, expected_draw], expected_next]
    )
    assert calls == [(1, 1)]
    assert random.randint is observed_draw
    assert result["termination_reason"] == "found_first_batch"
    counters = result["counters"]
    assert counters["expanded_nodes"] == 3
    assert counters["open_nodes"] == 1
    assert counters["candidate_batches"] == 2
    assert counters["empty_candidate_batches"] == 1
    assert counters["emitted_candidates"] == counters["raw_candidates"] == 2
    assert counters["grid_evictions"] == 1
    assert counters["collision_filter_valid_candidates"] is None
    assert "not a common search-only" in result["timing_scopes"]["worker_seconds"]


@pytest.mark.parametrize(
    ("namespace", "found", "expected"),
    [
        ({"Openset": [], "iter": 3, "max_iter": 100}, False, "open_exhausted"),
        ({"Openset": [1], "iter": 100, "max_iter": 100}, False, "iteration_budget"),
        ({"Openset": [], "iter": 100, "max_iter": 100}, False, "iteration_budget"),
        ({"Openset": [], "iter": 1, "max_iter": 100}, True, "found_first_batch"),
        ({}, False, "unknown_no_path_stop"),
    ],
)
def test_termination_uses_real_frontier_and_budget(
    namespace: dict, found: bool, expected: str
) -> None:
    """The author's skipped iteration increments cannot stand in for expansions."""
    assert author_termination(namespace, found) == expected


def test_unknown_eviction_and_candidate_counts_remain_null(
    synthetic_source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not convert unsupported source observations into measured zero counts."""
    fake_pyvista(monkeypatch)
    (synthetic_source / "main_sunlight_3Dgrid.py").write_text(
        "time_start=0.\ntime_end=1.\npaths_lengths=[]\nAllset=[]\n",
        encoding="utf-8",
    )
    (synthetic_source / "utils.py").write_text(
        "def showpoint(*args): pass\n"
        "showline=showline1=showdashedline=showvoxel=showpoint\n",
        encoding="utf-8",
    )
    result = execute_author(
        synthetic_source, synthetic_source / "map.vti", object(), 0, "author_original"
    )
    assert result["status"] == "no_path"
    assert result["counters"]["grid_evictions"] is None
    assert result["counters"]["candidate_batches"] is None
    assert result["counters"]["expanded_nodes"] is None


def test_startup_time_is_not_taken_from_seed_budget(tmp_path: Path) -> None:
    """A slow startup followed by a fast request still gets its full seed budget."""
    code = (
        "import json,sys,time; time.sleep(0.8); "
        "print(json.dumps({'event':'ready'}),flush=True); "
        "request=json.loads(sys.stdin.readline()); time.sleep(0.1); "
        "print(json.dumps({'event':'result','seed':request['seed'],'status':'ok'}),flush=True)"
    )
    worker = WorkerClient(
        [sys.executable, "-c", code], tmp_path / "stderr.log", startup_timeout=10
    )
    try:
        result = worker.run_seed(0, timeout=0.5)
        assert result["status"] == "ok"
        assert result["startup_seconds"] >= 0.8
        assert result["parent_seconds"] < 0.5
        assert result["total_parent_seconds"] > 0.8
    finally:
        worker.close()


def test_startup_timeout_is_distinguished_and_reaped(tmp_path: Path) -> None:
    """Missing readiness is a startup failure with a real process exit code."""
    worker = WorkerClient(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path / "stderr.log",
        startup_timeout=0.1,
    )
    try:
        result = worker.run_seed(0, timeout=5)
        assert result["status"] == "timeout"
        assert result["termination_reason"] == "startup_timeout"
        assert result["parameters"] is None
        assert result["wall_seconds"] is None
        assert result["exit_code"] not in (None, 0)
        assert worker.process is None
    finally:
        worker.close()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_client_rejects_nonfinite_or_nonpositive_timeouts(
    tmp_path: Path, timeout: float
) -> None:
    """Reject invalid budgets before starting any subprocess."""
    with pytest.raises(ValueError, match="finite and positive"):
        WorkerClient([], tmp_path / "log", startup_timeout=timeout)
    worker = WorkerClient([], tmp_path / "log")
    with pytest.raises(ValueError, match="finite and positive"):
        worker.run_seed(0, timeout)


@pytest.mark.parametrize("seed", [-1, 2**32, 0.5])
def test_client_enforces_numpy_seed_range(tmp_path: Path, seed: int) -> None:
    """Reject invalid seeds before process creation, including direct Python use."""
    worker = WorkerClient([], tmp_path / "log")
    with pytest.raises(ValueError, match="Seed"):
        worker.run_seed(seed, 1)


def cli_arguments(source: Path, local_dir: Path) -> list[str]:
    """Build explicit synthetic paths for parser-only tests."""
    return [
        "--source-dir",
        str(source),
        "--map-path",
        str(source / "map.vti"),
        "--local-dir",
        str(local_dir),
        "--output",
        str(local_dir.parent / "out.csv"),
    ]


def test_cli_rejects_mixing_prior_evidence(
    synthetic_source: Path, tmp_path: Path
) -> None:
    """Keep existing JSONL and CSV trials from being accidentally mixed."""
    local_dir = tmp_path / "evidence"
    local_dir.mkdir()
    marker = local_dir / "paths.jsonl"
    marker.write_text(json.dumps({"prior": True}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        parse_arguments(cli_arguments(synthetic_source, local_dir))
    assert json.loads(marker.read_text(encoding="utf-8"))["prior"] is True


def test_cli_accepts_an_empty_directory_and_original_alias(
    synthetic_source: Path, tmp_path: Path
) -> None:
    """An explicitly empty record directory is safe for the legacy interface."""
    local_dir = tmp_path / "empty"
    local_dir.mkdir()
    args = parse_arguments(
        [*cli_arguments(synthetic_source, local_dir), "--mode", "author_original"]
    )
    assert args.mode == "author_original"
    assert args.startup_timeout == 30


@pytest.mark.parametrize("option", ["--timeout", "--startup-timeout"])
@pytest.mark.parametrize("value", ["nan", "inf", "0", "-1"])
def test_cli_rejects_invalid_timeout(
    synthetic_source: Path, tmp_path: Path, option: str, value: str
) -> None:
    """Do not pass NaN or infinity into operating-system waits."""
    with pytest.raises(SystemExit):
        parse_arguments(
            [*cli_arguments(synthetic_source, tmp_path / "logs"), option, value]
        )
