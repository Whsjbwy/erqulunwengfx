"""Windows worker scheduling and nonprivate system workload measurements."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any


def configure_worker() -> dict[str, Any]:
    """Use normal priority and one consistent allowed logical CPU per worker."""
    if os.name != "nt":
        allowed = (
            sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else []
        )
        if allowed:
            os.sched_setaffinity(0, {allowed[min(2, len(allowed) - 1)]})
        return {
            "single_core": bool(allowed),
            "affinity": sorted(os.sched_getaffinity(0)) if allowed else None,
            "priority": "unchanged_non_windows",
        }
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    handle = kernel.GetCurrentProcess()
    kernel.GetProcessAffinityMask.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
    if not kernel.GetProcessAffinityMask(
        handle, ctypes.byref(process_mask), ctypes.byref(system_mask)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    mask = 4 if process_mask.value & 4 else process_mask.value & -process_mask.value
    if not mask or not kernel.SetProcessAffinityMask(handle, mask):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.SetPriorityClass(handle, 0x20):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"single_core": True, "affinity_mask": mask, "priority": "normal"}


def system_snapshot() -> dict[str, Any]:
    """Read aggregate CPU times and process count without names or command lines."""
    if os.name != "nt":
        return {"cpu_ticks": None, "process_count": None}
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    idle, system, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not kernel.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(system), ctypes.byref(user)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = [
        int(t.dwLowDateTime | (t.dwHighDateTime << 32)) for t in (idle, system, user)
    ]
    ids = (wintypes.DWORD * 8192)()
    returned = wintypes.DWORD()
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(returned)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "cpu_ticks": ticks,
        "process_count": returned.value // ctypes.sizeof(wintypes.DWORD),
    }


def cpu_busy_fraction(before: dict, after: dict) -> float | None:
    """Compute whole-machine busy fraction, not this worker's CPU share."""
    if before["cpu_ticks"] is None or after["cpu_ticks"] is None:
        return None
    idle, kernel, user = [
        b - a for a, b in zip(before["cpu_ticks"], after["cpu_ticks"], strict=True)
    ]
    total = kernel + user
    return max(0.0, min(1.0, 1 - idle / total)) if total > 0 else None
