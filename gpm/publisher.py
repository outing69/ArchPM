"""Writes a compact status to a JSON file for the desktop widget."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .model import Snapshot

_APP = "gpm"


def status_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    d = Path(base) / _APP
    d.mkdir(parents=True, exist_ok=True)
    return d


def status_path() -> Path:
    return status_dir() / "status.json"


def cache_link() -> Path:
    """~/.cache/gpm/status.json -> $XDG_RUNTIME_DIR/gpm/status.json

    The widget runs inside plasmashell and does not know $XDG_RUNTIME_DIR; via
    StandardPaths it does always end up at ~/.cache.
    """
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    d = Path(base) / _APP
    d.mkdir(parents=True, exist_ok=True)
    return d / "status.json"


def ensure_link() -> None:
    link, target = cache_link(), status_path()
    if link.is_symlink() and link.readlink() == target:
        return
    if link.exists() or link.is_symlink():
        link.unlink()
    try:
        link.symlink_to(target)
    except OSError:
        pass


def to_payload(snap: Snapshot, top_n: int = 5) -> dict:
    s = snap.system
    # Only processes that are actually doing something; a list of five 0% entries is noise.
    top_cpu = [p for p in sorted(snap.procs, key=lambda p: p.cpu_percent, reverse=True)[:top_n]
               if p.cpu_percent >= 0.5]
    top_mem = sorted(snap.procs, key=lambda p: p.mem_rss, reverse=True)[:top_n]
    payload = {
        "ts": s.ts,
        "cpu": round(s.cpu_percent, 1),
        "cpu_temp": round(s.cpu_temp_c, 1),
        "freq": round(s.freq_mhz),
        "cores": [round(c, 1) for c in s.per_core],
        "mem_used": s.mem_used,
        "mem_total": s.mem_total,
        "mem_pct": round(s.mem_pct, 1),
        "swap_pct": round(100.0 * s.swap_used / s.swap_total, 1) if s.swap_total else 0.0,
        "procs": s.proc_count,
        "threads": s.thread_count,
        "net_rx": round(s.net_rx_bps),
        "net_tx": round(s.net_tx_bps),
        "disk_r": round(s.disk_r_bps),
        "disk_w": round(s.disk_w_bps),
        "top_cpu": [{"name": p.name, "pid": p.pid, "v": round(p.cpu_percent, 1)} for p in top_cpu],
        "top_mem": [{"name": p.name, "pid": p.pid, "v": round(p.mem_mb)} for p in top_mem],
    }
    if s.gpu is not None:
        g = s.gpu
        payload["gpu"] = {
            "name": g.name,
            "util": round(g.util, 1),
            "temp": round(g.temp_c, 1),
            "mem_used": round(g.mem_used_mb),
            "mem_total": round(g.mem_total_mb),
            "mem_pct": round(g.mem_pct, 1),
            "power": round(g.power_w, 1),
            "clock": round(g.clock_mhz),
            "fan": round(g.fan_pct),
        }
    return payload


def publish(snap: Snapshot, path: Path | None = None) -> Path:
    """Atomic write: the widget never reads a half-written file."""
    target = path or status_path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(to_payload(snap), separators=(",", ":")))
    os.replace(tmp, target)
    if path is None:
        ensure_link()
    return target
