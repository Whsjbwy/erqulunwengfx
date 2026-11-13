"""Process-safe experiment ownership without relying on process-list visibility."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


def _set_file_lock(stream: BinaryIO, acquire: bool) -> None:
    """Lock one fixed byte; the operating system releases it on process exit."""
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        mode = msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK
        msvcrt.locking(stream.fileno(), mode, 1)
    else:
        import fcntl

        mode = fcntl.LOCK_EX | fcntl.LOCK_NB if acquire else fcntl.LOCK_UN
        fcntl.flock(stream.fileno(), mode)


@contextmanager
def experiment_lock(directory: Path) -> Iterator[None]:
    """Reject a second worker before search, retaining a harmless one-byte file."""
    with (directory / "experiment.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        try:
            _set_file_lock(stream, True)
        except OSError as error:
            raise RuntimeError(
                "Another worker owns this experiment directory"
            ) from error
        try:
            yield
        finally:
            _set_file_lock(stream, False)
