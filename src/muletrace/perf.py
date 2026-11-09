"""Wall time and peak memory of the current process, for ``docs/performance.md``.

Peak resident memory is read from the operating system, so it includes memory allocated by
Polars and LightGBM outside the Python heap (which ``tracemalloc`` would miss).
"""

from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

_BYTES_PER_MB = 1024 * 1024


if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
    from ctypes import wintypes

    class _ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        )

    def _peak_bytes() -> int:
        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCounters),
            wintypes.DWORD,
        )
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return int(counters.PeakWorkingSetSize)

else:  # pragma: no cover - exercised on Linux and macOS only
    import resource

    def _peak_bytes() -> int:
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)


def peak_memory_mb() -> float:
    """Peak resident set size of this process so far, in MiB."""
    return _peak_bytes() / _BYTES_PER_MB


@dataclass
class Measurement:
    """Result of :func:`measure`; filled in when the block exits."""

    seconds: float = 0.0
    peak_memory_mb: float = 0.0


@contextmanager
def measure() -> Iterator[Measurement]:
    """Time a block and record the process's peak memory when it ends."""
    result = Measurement()
    start = time.perf_counter()
    try:
        yield result
    finally:
        result.seconds = time.perf_counter() - start
        result.peak_memory_mb = peak_memory_mb()
