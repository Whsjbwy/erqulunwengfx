"""A second process must stop before experiment search, with crash-safe release."""

import subprocess
import sys

from gsunlight_repro.stage5ae.runtime import experiment_lock


def test_another_process_is_rejected_and_lock_is_released(tmp_path) -> None:
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; "
        "from gsunlight_repro.stage5ae.runtime import experiment_lock; "
        "\nwith experiment_lock(Path(sys.argv[1])): print('acquired')",
        str(tmp_path),
    ]
    with experiment_lock(tmp_path):
        refused = subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=False
        )
    assert refused.returncode != 0 and "Another worker" in refused.stderr
    accepted = subprocess.run(
        command, capture_output=True, text=True, timeout=10, check=False
    )
    assert accepted.returncode == 0 and accepted.stdout.strip() == "acquired"
