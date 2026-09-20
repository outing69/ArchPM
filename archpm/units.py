"""Bytes and rates as text, one way each.

The widgets' QML carries its own copy of the byte formatter (fmtBytes, the
same steps and decimals), since QML cannot import this module.
"""
from __future__ import annotations

KIB = 1024.0
GIB = float(2**30)
MIB = float(2**20)


def human_bytes(n: float) -> str:
    """"512 B", "1.5 KB", "3.0 GB": steps of 1024, no decimals for bytes and
    one above them, "PB" past terabytes."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < KIB:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= KIB
    return f"{n:.1f} PB"


def gb(n: float, decimals: int = 1) -> str:
    """The number of gigabytes as text, without the unit: "15.6", or "16"
    with decimals=0, for a pair that carries the unit once ("15.6 / 16 GB")."""
    return f"{n / GIB:.{decimals}f}"


def gigabytes(n: float, decimals: int = 1) -> str:
    """Always in gigabytes: "15.6 GB", or "16 GB" with decimals=0. A pair
    ("15.6 of 16 GB") needs both sides in one unit, which human_bytes does
    not promise; `n` is bytes, a value in megabytes is passed as n * MIB."""
    return f"{gb(n, decimals)} GB"


def human_rate(bps: float, *, blank_below: float = 1.0) -> str:
    """"300 B/s", "1.5 MB/s"; "" under `blank_below` bytes per second. The
    Network page blanks under a byte, the process list's Disk column under
    a kilobyte, the Overview's graphs never."""
    if bps < blank_below:
        return ""
    return f"{human_bytes(bps)}/s"
