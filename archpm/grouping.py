"""Which processes belong to the same application, for the Grouped view.

The key is the systemd unit the process sits in (the app-*.scope or
app-*.service the desktop assigns at launch, or a plain .service), then the
executable path, then the process name. A Steam game is its own application
whatever cgroup it runs in.

One merge rule on top: a group whose root process was started by a process
in another group, running the same executable, is folded into that group. A
Chromium-based browser registers its main process in a scope of its own
while its children stay in the launch service; this puts them back together.

No Qt in this file.
"""
from __future__ import annotations

import re
from collections import Counter

from .model import ProcSample

_APP_UNIT = re.compile(r"/(app-[^/]+)")
_LAST_UNIT = re.compile(r"/([^/]+\.(?:service|scope))(?:/|$)")


def unit_of(cgroup: str) -> str:
    """The unit that names an application in a cgroup path, or ""."""
    m = _APP_UNIT.search(cgroup)
    if m:
        return m.group(1)
    # init.scope holds pid 1 and main.scope is a generic child; neither names an app.
    units = [u for u in _LAST_UNIT.findall(cgroup) if u not in ("init.scope", "main.scope")]
    return units[-1] if units else ""


def group_key(p: ProcSample) -> tuple[str, str]:
    """(key, source): source says which rule decided, "steam", "cgroup", "exe" or "name"."""
    if p.steam_appid:
        return f"steam:{p.steam_appid}", "steam"
    unit = unit_of(p.cgroup)
    if unit:
        return f"cgroup:{unit}", "cgroup"
    if p.argv and p.argv[0].startswith("/"):
        return f"exe:{p.argv[0]}", "exe"
    return f"name:{p.name}", "name"


def _exe(p: ProcSample) -> str:
    return p.argv[0] if p.argv else ""


def build_groups(procs: list[ProcSample]) -> dict[str, list[ProcSample]]:
    out: dict[str, list[ProcSample]] = {}
    key_of: dict[int, str] = {}
    for p in procs:
        key = group_key(p)[0]
        out.setdefault(key, []).append(p)
        key_of[p.pid] = key
    by_pid = {p.pid: p for p in procs}

    # Fold a group into the group of its root's parent when both run the same
    # executable. Repeat until nothing moves: a fold can create a new root.
    changed = True
    while changed:
        changed = False
        for key, members in list(out.items()):
            pids = {p.pid for p in members}
            for root in members:
                parent = by_pid.get(root.ppid)
                if parent is None or root.ppid in pids:
                    continue
                target = key_of[parent.pid]
                if target != key and _exe(root) and _exe(root) == _exe(parent):
                    out[target].extend(members)
                    del out[key]
                    for m in members:
                        key_of[m.pid] = target
                    changed = True
                    break
            if changed:
                break
    return out


def read_pss(pid: int, proc_root: str = "/proc") -> int:
    """Proportional set size in bytes from /proc/<pid>/smaps_rollup; 0 when
    unreadable. Shared pages are divided between the processes sharing them,
    so PSS values can be added up. Costs up to tens of ms for a big process."""
    try:
        with open(f"{proc_root}/{pid}/smaps_rollup", "rb") as fh:
            for line in fh:
                if line.startswith(b"Pss:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def main_process(members: list[ProcSample]) -> ProcSample:
    """The member that stands for the group: its root (parent outside the
    group), a user-facing program before a helper, the oldest before the rest."""
    pids = {p.pid for p in members}
    return min(members, key=lambda p: (p.ppid in pids, not p.program, p.create_time, p.pid))


def summarize(pid: int, key: str, members: list[ProcSample]) -> ProcSample:
    """One synthetic sample for the group row. The numbers are sums; memory
    adds RSS, which counts shared pages more than once, hence mem_approx."""
    main = main_process(members)
    names = Counter(p.app_name for p in members if p.app_name)
    app_name = main.app_name or (names.most_common(1)[0][0] if names else "")
    icon = main.icon or next((p.icon for p in members if p.icon), "")
    return ProcSample(
        pid=pid, ppid=0, name=main.name, username=main.username,
        cmdline=main.cmdline, argv=main.argv,
        cpu_percent=sum(p.cpu_percent for p in members),
        # PSS where measured, so shared pages count once; RSS for the rest
        mem_rss=sum(p.mem_pss or p.mem_rss for p in members),
        mem_percent=sum(p.mem_percent for p in members),
        num_threads=sum(p.num_threads for p in members),
        nice=main.nice, status="",
        io_read_bps=sum(p.io_read_bps for p in members),
        io_write_bps=sum(p.io_write_bps for p in members),
        gpu_sm=sum(p.gpu_sm for p in members),
        gpu_mem_mb=sum(p.gpu_mem_mb for p in members),
        create_time=min(p.create_time for p in members),
        affinity=main.affinity,
        owned=all(p.owned for p in members),
        app_name=app_name, icon=icon,
        category=main.category or next((p.category for p in members if p.category), ""),
        program=any(p.program for p in members),
        steam_appid=main.steam_appid,
        cgroup=key, members=len(members),
        mem_approx=any(not p.mem_pss for p in members),
    )
