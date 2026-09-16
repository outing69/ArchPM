"""Failed services, read-only: one look at `systemctl --failed` and one at
`systemctl --user --failed`, with the last lines of each failed unit's log.

Taken once, when the window starts, and again only when the user presses
Refresh on the System page; never on the sampling cycle, never on a timer.
Both listings read fine as the normal user, so no pkexec and no root helper,
and ArchPM still starts or stops no system service.

No Qt in this file.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field

SESSION, SYSTEM = "session", "system"
LOG_LINES = 8
TIMEOUT = 5


@dataclass
class FailedUnit:
    unit: str
    description: str = ""
    scope: str = SYSTEM          # "session" (systemctl --user) or "system"
    since: str = ""              # when it entered the failed state, as systemd prints it
    log: list[str] = field(default_factory=list)
    note: str = ""               # why there is no log, when there is none

    @property
    def title(self) -> str:
        return self.description or self.unit


@dataclass
class FailedReport:
    units: list[FailedUnit] = field(default_factory=list)
    journal_readable: bool = True    # the system journal, for this user
    took_ms: float = 0.0
    taken_at: float = 0.0            # time.time()
    error: str = ""                  # systemctl itself could not be asked


def _argv(scope: str, *args: str) -> list[str]:
    return ["systemctl", *(["--user"] if scope == SESSION else []), *args]


def parse_list(out: str) -> list[tuple[str, str]]:
    """(unit, description) per line of `systemctl --failed --no-legend --plain`:
    UNIT LOAD ACTIVE SUB DESCRIPTION."""
    units = []
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] in ("●", "*", "x", "✗"):
            parts = parts[1:]
        if len(parts) >= 4:
            desc = " ".join(parts[4:])
            units.append((parts[0], desc if desc != parts[0] else ""))
    return units


def parse_show(out: str) -> dict[str, dict[str, str]]:
    """`systemctl show -p Id -p Description -p StateChangeTimestamp a b`: one
    block of key=value lines per unit, blank line between."""
    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] = {}
    for line in out.splitlines() + [""]:
        if not line.strip():
            if current.get("Id"):
                blocks[current["Id"]] = current
            current = {}
            continue
        key, _, value = line.partition("=")
        current[key] = value
    return blocks


def journal_readable(run=subprocess.run) -> bool:
    """Can this user read the system journal? journalctl says so on stderr when not."""
    try:
        proc = run(["journalctl", "--system", "-n", "1", "-q", "--no-pager"],
                   capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    err = proc.stderr or ""
    return proc.returncode == 0 and "insufficient permissions" not in err \
        and "not seeing messages" not in err


def unit_log(unit: str, scope: str, run=subprocess.run, lines: int = LOG_LINES) -> list[str]:
    argv = ["journalctl", *(["--user"] if scope == SESSION else []), "-u", unit,
            "-n", str(lines), "-q", "--no-pager", "-o", "short"]
    try:
        proc = run(argv, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line for line in (proc.stdout or "").splitlines() if line.strip()]


def check(run=subprocess.run, lines: int = LOG_LINES) -> FailedReport:
    """The snapshot. Two systemctl calls always; details and logs only for
    what failed, and the system journal is probed only when a system unit did."""
    start = time.perf_counter()
    report = FailedReport(taken_at=time.time())
    found: list[FailedUnit] = []
    for scope in (SYSTEM, SESSION):
        try:
            proc = run(_argv(scope, "--failed", "--no-legend", "--plain", "--no-pager"),
                       capture_output=True, text=True, timeout=TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            report.error = f"systemctl could not be asked: {exc}"
            break
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            report.error = err[-1] if err else f"systemctl returned code {proc.returncode}"
            continue
        units = [FailedUnit(unit, desc, scope) for unit, desc in parse_list(proc.stdout)]
        if not units:
            continue
        try:
            shown = run(_argv(scope, "show", "-p", "Id", "-p", "Description",
                              "-p", "StateChangeTimestamp", "--", *(u.unit for u in units)),
                        capture_output=True, text=True, timeout=TIMEOUT, check=False)
            details = parse_show(shown.stdout or "")
        except (OSError, subprocess.TimeoutExpired):
            details = {}
        for u in units:
            d = details.get(u.unit, {})
            u.description = u.description or d.get("Description", "")
            u.since = d.get("StateChangeTimestamp", "")
        found.extend(units)
    if any(u.scope == SYSTEM for u in found):
        report.journal_readable = journal_readable(run)
    for u in found:
        if u.scope == SYSTEM and not report.journal_readable:
            u.note = ("The system log is not readable for this user; add yourself to the "
                      "systemd-journal group, or read it as root: journalctl -u " + u.unit)
            continue
        u.log = unit_log(u.unit, u.scope, run, lines)
        if not u.log:
            u.note = "Nothing in the log for this unit."
    report.units = found
    report.took_ms = (time.perf_counter() - start) * 1000
    return report
