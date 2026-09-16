"""Writes a compact status to a JSON file for the desktop widgets.

The file is data only. The widgets read numbers and names from it and run
nothing that comes out of it: ArchPM is started by a path fixed when the
widget is installed, and "End game" asks the window to do it, guards and all.

Every write goes through a descriptor of the directory, checked with fstat
after it is opened: a real directory, owned by us, writable by nobody else.
Checking a path and opening it afterwards would leave a gap in which the
directory can be swapped for another one.
"""
from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
from pathlib import Path

from . import net as netmod
from .game import game_summary, pick_game
from .model import Snapshot

_APP = "archpm"
STATUS_NAME = "status.json"
_TMP_NAME = "status.tmp"


class PublishError(RuntimeError):
    """The status file cannot be written somewhere safe. The message says where and why."""


def runtime_dir() -> Path | None:
    """$XDG_RUNTIME_DIR/archpm, or None when the session has no runtime directory."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    return Path(base) / _APP if base else None


def cache_dir() -> Path:
    """~/.cache/archpm: the widgets read here, and it is where we write when
    there is no runtime directory. Ours in either case."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / _APP


def status_dir() -> Path:
    """Where status.json goes: the runtime directory, or the cache directory
    without one. Never a shared temporary directory: a directory another user
    can create first is a directory another user can replace the file in."""
    return runtime_dir() or cache_dir()


def status_path() -> Path:
    return status_dir() / STATUS_NAME


def cache_link() -> Path:
    """~/.cache/archpm/status.json -> $XDG_RUNTIME_DIR/archpm/status.json

    The widget runs inside plasmashell and does not know $XDG_RUNTIME_DIR; via
    StandardPaths it does always end up at ~/.cache.
    """
    return cache_dir() / STATUS_NAME


def open_owned_dir(path: Path, uid: int | None = None) -> int:
    """A descriptor of `path`, created if needed, after it passed the checks:
    a directory and not a symlink, owned by `uid` (us), no write bit for group
    or others. Raises PublishError otherwise. The caller closes it."""
    uid = os.getuid() if uid is None else uid
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise PublishError(f"{path}: cannot create it ({exc.strerror})") from exc
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        # O_NOFOLLOW with O_DIRECTORY: a symlink comes back as ELOOP or, on
        # Linux when it points at a directory, as ENOTDIR.
        why = ("a symlink or not a directory" if exc.errno in (errno.ELOOP, errno.ENOTDIR)
               else exc.strerror or str(exc))
        raise PublishError(f"{path}: not a directory of our own ({why})") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise PublishError(f"{path}: not a directory")
        if st.st_uid != uid:
            raise PublishError(f"{path}: owned by uid {st.st_uid}, not by us (uid {uid}); "
                               "the status file is not written there")
        if st.st_mode & 0o022:
            raise PublishError(f"{path}: writable by others (mode {stat.S_IMODE(st.st_mode):o}); "
                               "the status file is not written there")
    except PublishError:
        os.close(fd)
        raise
    return fd


def _write_atomic(dir_fd: int, name: str, text: str) -> None:
    """status.tmp then rename, both relative to the checked directory, so the
    widget never reads a half-written file and no path is resolved twice."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(_TMP_NAME, flags, 0o600, dir_fd=dir_fd)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.rename(_TMP_NAME, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)


def ensure_link() -> None:
    """The symlink in the cache directory, when the file lives elsewhere. With
    the file in the cache directory itself there is nothing to link."""
    target = status_path()
    if target.parent == cache_dir():
        return
    dir_fd = open_owned_dir(cache_dir())
    try:
        try:
            if os.readlink(STATUS_NAME, dir_fd=dir_fd) == str(target):
                return
        except OSError:
            pass  # absent, or not a symlink
        try:
            os.unlink(STATUS_NAME, dir_fd=dir_fd)
        except FileNotFoundError:
            pass
        os.symlink(str(target), STATUS_NAME, dir_fd=dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


_state = {"game_pid": 0}   # the game shown last tick, so the widget does not hop

AGENT_UNIT = "archpm-agent"


def agent_service_active(run=subprocess.run) -> bool:
    """True when the agent runs as a systemd user service. Then the agent is
    the one producer of status.json and the GUI must not write it too: the
    two do not carry the same content, and the widget would alternate."""
    try:
        proc = run(["systemctl", "--user", "is-active", "--quiet", AGENT_UNIT],
                   capture_output=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


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
        "top_cpu": [{"name": p.display_name, "pid": p.pid, "v": round(p.cpu_percent, 1)}
                    for p in top_cpu],
        "top_mem": [{"name": p.display_name, "pid": p.pid, "v": round(p.mem_mb)}
                    for p in top_mem],
    }
    ncpu = len(s.per_core) or 1
    game = pick_game(snap.procs, _state["game_pid"])
    _state["game_pid"] = game.pid if game else 0
    if game is not None:
        payload["game"] = game_summary(game, snap.procs, ncpu)
    if snap.net is not None:
        payload["net"] = netmod.to_payload(snap.net, {p.pid: p.display_name for p in snap.procs})
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
    """Write the status file. Raises PublishError when its directory is not
    one of our own; the caller says so and stops publishing."""
    target = path or status_path()
    dir_fd = open_owned_dir(target.parent)
    try:
        _write_atomic(dir_fd, target.name, json.dumps(to_payload(snap), separators=(",", ":")))
    except OSError as exc:
        raise PublishError(f"{target}: cannot write it ({exc.strerror or exc})") from exc
    finally:
        os.close(dir_fd)
    if path is None:
        ensure_link()
    return target
