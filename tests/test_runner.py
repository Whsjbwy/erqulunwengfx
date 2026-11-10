"""Test repeatability, subprocess limits, and separation of reported validity."""

from __future__ import annotations

import random
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from gsunlight_repro.author_worker import execute_author
from gsunlight_repro.experiment_runner import WorkerClient, result_rows
from gsunlight_repro.map_reader import OccupancyMap
from gsunlight_repro.metrics import endpoints_match, path_length, processor_name


def test_metric_uses_all_segments() -> None:
    """Measure full polylines and reject nonfinite evidence."""
    assert path_length([[0, 0, 0], [3, 4, 0], [3, 4, 12]]) == 17
    with pytest.raises(ValueError, match="finite"):
        path_length([[0, 0, 0], [np.nan, 0, 0]])


def test_reported_success_is_not_strict_validity() -> None:
    """Keep an author's success flag when independent geometry rejects its path."""
    occupied = np.zeros((3, 3, 3), dtype=bool)
    occupied[1, 0, 0] = True
    grid = OccupancyMap(occupied)
    result = {
        "seed": 0,
        "status": "ok",
        "reported_success": True,
        "parameters": {"start": [0.5, 0.5, 0.5], "goal": [2.5, 0.5, 0.5]},
        "raw_path": [[0.5, 0.5, 0.5], [2.5, 0.5, 0.5]],
        "postprocessed_path": [
            [0.5, 0.5, 0.5],
            [0.5, 2.5, 0.5],
            [2.5, 2.5, 0.5],
            [2.5, 0.5, 0.5],
        ],
    }
    raw, processed = result_rows(result, grid, "synthetic", "test")
    assert raw["reported_success"] is True
    assert raw["strict_valid"] is False
    assert raw["collision_segment_count"] == 1
    assert processed["strict_valid"] is True


def test_endpoints_must_match_in_either_orientation() -> None:
    """A collision-free fragment is not a successful start-to-goal path."""
    assert endpoints_match([[2, 2, 2], [0, 0, 0]], [0, 0, 0], [2, 2, 2])
    assert not endpoints_match([[0, 0, 0], [1, 1, 1]], [0, 0, 0], [2, 2, 2])


def test_worker_times_out_and_reaps_process(tmp_path: Path) -> None:
    """A hung synthetic planner must not survive its per-seed deadline."""
    code = (
        "import json,sys,time; "
        "print(json.dumps({'event':'ready'}),flush=True); "
        "sys.stdin.readline(); time.sleep(30)"
    )
    worker = WorkerClient([sys.executable, "-c", code], tmp_path / "stderr.log")
    try:
        result = worker.run_seed(4, timeout=0.5)
        assert result["status"] == "timeout"
        assert result["exit_code"] is not None
        assert result["exit_code"] != 0
        assert result["parameters"] is None
        assert worker.process is None
    finally:
        worker.close()


@pytest.mark.parametrize("selected_before_error", [False, True])
def test_postprocessor_error_preserves_completed_raw_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selected_before_error: bool,
) -> None:
    """Preserve completed search evidence without publishing partial smoothing."""
    source = tmp_path / "synthetic_failure"
    source.mkdir()
    source.joinpath("utils.py").write_text(
        "def showpoint(*args): pass\n"
        "showline=showline1=showdashedline=showvoxel=showpoint\n",
        encoding="utf-8",
    )
    selection = (
        "min_index=0\npath=np.asarray(paths[0],dtype=np.float32)\n"
        if selected_before_error
        else ""
    )
    source.joinpath("main_sunlight_3Dgrid.py").write_text(
        "import numpy as np\n"
        "from utils import *\n"
        "start=[0.1,0.1,0.1]\ngoal=[1.9,1.9,1.9]\nmax_num=1\n"
        "paths=[[goal,start]]\npaths_lengths=[3.117691]\n"
        "Allset=np.array([start,goal])\n"
        + selection
        + "path1=np.array([[999.,999.,999.],[1.,1.,1.]])\n"
        "raise RuntimeError('synthetic postprocessor failed')\n",
        encoding="utf-8",
    )
    pyvista = ModuleType("pyvista")
    pyvista.read = object()
    pyvista.Plotter = object()
    monkeypatch.setitem(sys.modules, "pyvista", pyvista)
    result = execute_author(source, source / "map.vti", object(), 0, "test")
    assert result["status"] == "crash"
    assert result["reported_success"] is True
    assert result["parameters"]["max_num"] == 1
    assert result["raw_path"] is not None
    assert result["postprocessed_path"] is None
    assert result["partial"] is True
    expected_state = (
        "selected_before_error"
        if selected_before_error
        else "selected_from_completed_candidates_after_error"
    )
    assert result["raw_path_state"] == expected_state
    grid = OccupancyMap(np.zeros((2, 2, 2), dtype=bool))
    result["seed"] = 0
    raw, postprocessed = result_rows(result, grid, "synthetic", "test")
    assert raw["strict_valid"] is True
    assert "RuntimeError: synthetic postprocessor failed" in raw["failure_reason"]
    assert postprocessed["strict_valid"] is False
    assert "Traceback" in capsys.readouterr().err


def test_normal_no_path_and_invalid_endpoints_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Record a normal empty search separately from an incomplete geometric path."""
    source = tmp_path / "synthetic_no_path"
    source.mkdir()
    source.joinpath("utils.py").write_text(
        "def showpoint(*args): pass\n"
        "showline=showline1=showdashedline=showvoxel=showpoint\n",
        encoding="utf-8",
    )
    source.joinpath("main_sunlight_3Dgrid.py").write_text(
        "from utils import *\n"
        "start=[0.1,0.1,0.1]\ngoal=[1.9,1.9,1.9]\n"
        "paths=[]\npaths_lengths=[]\nAllset=[start]\n"
        "time_start=0.\ntime_end=1.\n",
        encoding="utf-8",
    )
    pyvista = ModuleType("pyvista")
    pyvista.read = object()
    pyvista.Plotter = object()
    monkeypatch.setitem(sys.modules, "pyvista", pyvista)
    result = execute_author(source, source / "map.vti", object(), 0, "test")
    result["seed"] = 0
    assert result["status"] == "no_path"
    assert result["exit_code"] == 0
    assert result["reported_success"] is False
    grid = OccupancyMap(np.zeros((2, 2, 2), dtype=bool))
    rows = result_rows(result, grid, "synthetic", "test")
    assert all(row["failure_reason"] == "author_returned_no_path" for row in rows)
    result.update(
        status="ok",
        reported_success=True,
        failure_reason="",
        raw_path=[[0.1, 0.1, 0.1], [1.0, 1.0, 1.0]],
    )
    raw, _ = result_rows(result, grid, "synthetic", "test")
    assert raw["reported_success"] is True
    assert raw["strict_valid"] is False
    assert raw["failure_reason"] == "endpoint_mismatch"


def test_cpu_description_falls_back_to_read_only_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows' empty platform CPU name uses only the read permission on one key."""
    from gsunlight_repro import metrics

    monkeypatch.setattr(metrics.platform, "processor", lambda: "")
    monkeypatch.setattr(metrics.platform, "system", lambda: "Windows")
    registry = ModuleType("winreg")
    registry.HKEY_LOCAL_MACHINE = "local-machine"
    registry.KEY_READ = 1
    permissions = []

    def open_key(root: str, key: str, *, access: int) -> nullcontext[str]:
        permissions.append(access)
        return nullcontext(key)

    registry.OpenKey = open_key
    registry.QueryValueEx = lambda key, name: ("Synthetic CPU", 1)
    monkeypatch.setitem(sys.modules, "winreg", registry)
    assert processor_name() == "Synthetic CPU"
    assert permissions == [registry.KEY_READ]


def test_author_context_is_repeatable_and_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed both RNGs, preserve source files, and restore imports and patches."""
    source = tmp_path / "author"
    source.mkdir()
    source.joinpath("utils.py").write_text(
        "def showpoint(*args): pass\n"
        "showline=showline1=showdashedline=showvoxel=showpoint\n",
        encoding="utf-8",
    )
    source.joinpath("main_sunlight_3Dgrid.py").write_text(
        "import time,random,numpy as np,pyvista as pv\n"
        "from utils import *\n"
        "time_start=time.time()\n"
        "assert pv.read('./map.vti') is not None\n"
        "paths_lengths=[1.]\n"
        "path=np.array([[random.random(),np.random.random(),0.],[1.,1.,1.]])\n"
        "path1=path.copy()\n"
        "Allset=path\n"
        "time_end=time.time()\n",
        encoding="utf-8",
    )
    pyvista = ModuleType("pyvista")
    original_read = object()
    original_plotter = object()
    pyvista.read = original_read
    pyvista.Plotter = original_plotter
    monkeypatch.setitem(sys.modules, "pyvista", pyvista)
    sentinel = ModuleType("utils")
    monkeypatch.setitem(sys.modules, "utils", sentinel)
    cwd = Path.cwd()
    argv = sys.argv[:]
    random_state = random.getstate()
    numpy_state = np.random.get_state()
    first = execute_author(source, source / "map.vti", object(), 7, "test")
    second = execute_author(source, source / "map.vti", object(), 7, "test")
    assert first["raw_path"] == second["raw_path"]
    assert Path.cwd() == cwd
    assert sys.argv == argv
    assert sys.modules["utils"] is sentinel
    assert pyvista.read is original_read
    assert pyvista.Plotter is original_plotter
    assert random.getstate() == random_state
    assert np.array_equal(np.random.get_state()[1], numpy_state[1])


def test_private_protocol_survives_author_output_and_reuses_worker(
    tmp_path: Path,
) -> None:
    """Native and Python output cannot corrupt the persistent JSON control channel."""
    import pyvista as pv

    source = tmp_path / "synthetic_source"
    source.mkdir()
    source.joinpath("utils.py").write_text(
        "def showpoint(*args): pass\n"
        "showline=showline1=showdashedline=showvoxel=showpoint\n",
        encoding="utf-8",
    )
    source.joinpath("main_sunlight_3Dgrid.py").write_text(
        "import os,time,random,numpy as np,pyvista as pv\n"
        "from utils import *\n"
        "print('author Python output')\n"
        "os.write(1,b'native output\\n')\n"
        "time_start=time.time()\n"
        "assert pv.read('./map.vti').n_cells==8\n"
        "start=[0.1,0.1,0.1]\n"
        "goal=[1.9,1.9,1.9]\n"
        "paths_lengths=[1.]\n"
        "path=np.array([start,[random.random(),np.random.random(),0.5],goal])\n"
        "path1=path.copy()\n"
        "Allset=path\n"
        "time_end=time.time()\n",
        encoding="utf-8",
    )
    image = pv.ImageData(dimensions=(3, 3, 3))
    image.cell_data["obstacle"] = np.zeros(8)
    map_path = tmp_path / "map.vti"
    image.save(map_path)
    local_dir = tmp_path / "logs"
    local_dir.mkdir()
    worker = WorkerClient(
        [
            sys.executable,
            "-m",
            "gsunlight_repro.author_worker",
            "--source-dir",
            str(source),
            "--map-path",
            str(map_path),
            "--local-dir",
            str(local_dir),
        ],
        tmp_path / "stderr.log",
    )
    try:
        first = worker.run_seed(7, timeout=20)
        second = worker.run_seed(7, timeout=20)
        assert first["status"] == second["status"] == "ok"
        assert first["raw_path"] == second["raw_path"]
        assert first["worker_pid"] == second["worker_pid"]
        assert first["map_load_count"] == second["map_load_count"] == 1
        log = (local_dir / "seed_7.log").read_text(encoding="utf-8")
        assert "author Python output" in log
        assert "native output" in log
    finally:
        worker.close()
