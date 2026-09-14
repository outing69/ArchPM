#!/usr/bin/env python3
"""archpm-helper -- the only piece of ArchPM that runs as root.

Invoked via pkexec, one action per call, and replies with JSON on stdout.
Limited to process management, memory and two fixed cleanup commands (package
cache, journal); GPU tuning belongs in a different tool, and services are not
managed here at all: ArchPM only touches your own session's services, which
need no root (see actions.py).
Deliberately stdlib-only and without imports from the archpm package: this
file lives root-owned in /usr/lib/archpm/ (or /usr/local/lib/archpm/ when
installed from a checkout) and must not be able to load anything from a
directory a regular user can write to.

Everything that comes in is validated: fixed subcommands, numeric bounds and a
list of units whose processes we refuse to signal because your session would
collapse with them. A shell is never started.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys

PATH = "/usr/bin:/usr/sbin:/bin:/sbin"

ALLOWED_SIGNALS = {"TERM", "KILL", "STOP", "CONT", "HUP", "INT", "USR1", "USR2"}
INT_RE = re.compile(r"-?[0-9]{1,10}")

# Units your graphical session or the system cannot live without. A process
# inside one of these cgroups is never signalled, whatever the caller says.
PROTECTED_UNITS = {
    "dbus.service", "dbus-broker.service", "dbus.socket",
    "systemd-logind.service", "systemd-logind-varlink.socket",
    "systemd-journald.service", "systemd-journald.socket",
    "systemd-journald-dev-log.socket", "systemd-journald-audit.socket",
    "systemd-udevd.service", "systemd-udevd-control.socket", "systemd-udevd-kernel.socket",
    "polkit.service", "systemd-oomd.service", "systemd-oomd.socket",
    "display-manager.service", "sddm.service", "gdm.service", "lightdm.service",
    "ly.service", "greetd.service", "lxdm.service", "xdm.service",
}
# Subcommands that used to exist. Refused explicitly so an old client gets a
# JSON error it understands instead of argparse usage text.
REMOVED_COMMANDS = {
    "service": "the helper no longer manages services; ArchPM runs your own "
               "session's services through systemctl --user without root",
}
# Processes of system accounts (root, polkitd, dbus, ...) are never signalled:
# that is how you would kill logind or the display manager by pid and bypass the
# unit protection above. Arch and most distributions start regular users at 1000.
SYSTEM_UID_MAX = 999


class HelperError(Exception):
    pass


def run(*cmd: str, timeout: int = 20) -> str:
    """Execute without a shell, with a clean PATH."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
            env={"PATH": PATH, "LC_ALL": "C"},
        )
    except FileNotFoundError:
        raise HelperError(f"{cmd[0]} not found") from None
    except subprocess.TimeoutExpired:
        raise HelperError(f"{cmd[0]} did not respond within {timeout}s") from None
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip().splitlines()
        raise HelperError(msg[-1] if msg else f"{cmd[0]} returned code {proc.returncode}")
    return proc.stdout.strip()


def as_int(value: str, lo: int, hi: int, what: str) -> int:
    # int() would also accept " 5 ", "+5", "1_0" and non-ASCII digits; we don't.
    if not INT_RE.fullmatch(value):
        raise HelperError(f"{what} must be an integer, not {value!r}")
    n = int(value)
    if not lo <= n <= hi:
        raise HelperError(f"{what} must be between {lo} and {hi} (got {n})")
    return n


def check_pid(pid: int) -> None:
    if pid <= 1:
        raise HelperError("pid 1 and below are protected")
    if not os.path.isdir(f"/proc/{pid}"):
        raise HelperError(f"process {pid} does not exist")


def proc_uid(pid: int) -> int:
    """Real uid of a process, from /proc/<pid>/status."""
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    raise HelperError(f"process {pid} does not exist")


def proc_units(pid: int) -> set[str]:
    """systemd units the process's cgroup path passes through, e.g. {'sddm.service'}."""
    try:
        with open(f"/proc/{pid}/cgroup") as fh:
            path = fh.read().strip().rpartition(":")[2]
    except OSError:
        return set()
    return {part for part in path.split("/") if "." in part}


def check_signal_target(pid: int) -> None:
    """Refuse pids the helper must never signal, whatever the caller says."""
    uid = proc_uid(pid)
    if uid <= SYSTEM_UID_MAX:
        raise HelperError(
            f"process {pid} runs as a system account (uid {uid}); "
            "the helper only signals processes of regular users"
        )
    hit = proc_units(pid) & PROTECTED_UNITS
    if hit:
        raise HelperError(f"process {pid} belongs to {sorted(hit)[0]}, which is protected")


# -- processes ----------------------------------------------------------------
def cmd_proc_nice(args) -> dict:
    pid = as_int(args.pid, 2, 2**22, "pid")
    value = as_int(args.value, -20, 19, "nice")
    check_pid(pid)
    os.setpriority(os.PRIO_PROCESS, pid, value)
    return {"pid": pid, "nice": os.getpriority(os.PRIO_PROCESS, pid)}


def cmd_proc_signal(args) -> dict:
    pid = as_int(args.pid, 2, 2**22, "pid")
    name = args.signal.upper().removeprefix("SIG")
    if name not in ALLOWED_SIGNALS:
        raise HelperError(f"signal {name} not allowed")
    # A pidfd pins the process *before* we look at who it is, so a pid that is
    # recycled between the check and the signal cannot receive it.
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        raise HelperError(f"process {pid} does not exist") from None
    try:
        check_signal_target(pid)
        signal.pidfd_send_signal(fd, getattr(signal, f"SIG{name}"))
    except ProcessLookupError:
        raise HelperError(f"process {pid} does not exist") from None
    finally:
        os.close(fd)
    return {"pid": pid, "signal": name}


def cmd_proc_affinity(args) -> dict:
    pid = as_int(args.pid, 2, 2**22, "pid")
    check_pid(pid)
    ncpu = os.cpu_count() or 1
    cores = {as_int(c, 0, ncpu - 1, "core") for c in args.cores.split(",") if c != ""}
    if not cores:
        raise HelperError("no cores specified")
    os.sched_setaffinity(pid, cores)
    return {"pid": pid, "affinity": sorted(os.sched_getaffinity(pid))}


def cmd_proc_ionice(args) -> dict:
    pid = as_int(args.pid, 2, 2**22, "pid")
    klass = as_int(args.klass, 0, 3, "IO class")
    value = as_int(args.value, 0, 7, "IO priority")
    check_pid(pid)
    run("ionice", "-c", str(klass), *(() if klass == 3 else ("-n", str(value))), "-p", str(pid))
    return {"pid": pid, "class": klass, "level": value}


# -- memory ------------------------------------------------------------------
def cmd_swappiness(args) -> dict:
    value = as_int(args.value, 0, 200, "swappiness")
    with open("/proc/sys/vm/swappiness", "w") as fh:
        fh.write(str(value))
    return {"swappiness": value}


def cmd_drop_caches(args) -> dict:
    level = as_int(args.level, 1, 3, "level")
    os.sync()
    with open("/proc/sys/vm/drop_caches", "w") as fh:
        fh.write(str(level))
    return {"dropped": level}


# -- cleanup: fixed commands, nothing from the caller reaches them --------------
def cmd_paccache_clean(_args) -> dict:
    """Remove cached package versions beyond the last two of each package."""
    out = run("paccache", "-rk2", timeout=120)
    return {"paccache": out.splitlines()[-1] if out else "nothing to do"}


def cmd_journal_vacuum(_args) -> dict:
    """Shrink archived journal files to the most recent 100 MB."""
    out = run("journalctl", "--vacuum-size=100M", timeout=60)
    return {"journal": out.splitlines()[-1] if out else "nothing to do"}


# -- status -------------------------------------------------------------------
def cmd_status(_args) -> dict:
    out: dict = {"uid": os.getuid()}
    try:
        with open("/proc/sys/vm/swappiness") as fh:
            out["swappiness"] = int(fh.read().strip())
    except OSError:
        pass
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="archpm-helper", description="ArchPM root helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("proc-nice"); p.add_argument("pid"); p.add_argument("value")
    p.set_defaults(fn=cmd_proc_nice)
    p = sub.add_parser("proc-signal"); p.add_argument("pid"); p.add_argument("signal")
    p.set_defaults(fn=cmd_proc_signal)
    p = sub.add_parser("proc-affinity"); p.add_argument("pid"); p.add_argument("cores")
    p.set_defaults(fn=cmd_proc_affinity)
    p = sub.add_parser("proc-ionice")
    p.add_argument("pid"); p.add_argument("klass"); p.add_argument("value", nargs="?", default="4")
    p.set_defaults(fn=cmd_proc_ionice)

    p = sub.add_parser("swappiness"); p.add_argument("value"); p.set_defaults(fn=cmd_swappiness)
    p = sub.add_parser("drop-caches"); p.add_argument("level", nargs="?", default="3")
    p.set_defaults(fn=cmd_drop_caches)
    sub.add_parser("paccache-clean").set_defaults(fn=cmd_paccache_clean)
    sub.add_parser("journal-vacuum").set_defaults(fn=cmd_journal_vacuum)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        if argv and argv[0] in REMOVED_COMMANDS:
            raise HelperError(REMOVED_COMMANDS[argv[0]])
        args = build_parser().parse_args(argv)
        payload = {"ok": True, "result": args.fn(args)}
    except HelperError as exc:
        payload = {"ok": False, "error": str(exc)}
    except PermissionError as exc:
        payload = {"ok": False, "error": f"no permission: {exc}"}
    except OSError as exc:
        payload = {"ok": False, "error": str(exc)}
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
