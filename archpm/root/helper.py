#!/usr/bin/env python3
"""archpm-helper -- the only piece of ArchPM that runs as root.

Invoked via pkexec, one action per call, and replies with JSON on stdout.
Limited to process management, system services and memory; GPU tuning belongs
in a different tool. Deliberately stdlib-only and without imports from the archpm
package: this file lives root-owned in /usr/local/lib/archpm/ and must not be able
to load anything from a directory a regular user can write to.

Everything that comes in is validated: fixed subcommands, numeric bounds, a
unit-name regex and a list of services we refuse to stop because your session
would collapse with them. A shell is never started.
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
# First character may not be "-": a name like "--no-block.service" would otherwise
# reach systemctl looking like an option. The "--" below is the second line of defence.
UNIT_RE = re.compile(r"^[A-Za-z0-9@_][A-Za-z0-9@._:-]{0,127}\.(service|socket|timer|target|path)$")

# Services whose stopping wrecks your graphical session or the system.
PROTECTED_UNITS = {
    "dbus.service", "dbus-broker.service", "systemd-logind.service",
    "systemd-journald.service", "systemd-udevd.service", "polkit.service",
    "display-manager.service", "sddm.service", "gdm.service",
    "systemd-oomd.service", "dbus.socket",
}
SERVICE_ACTIONS = {"start", "stop", "restart"}


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
    try:
        n = int(value)
    except ValueError:
        raise HelperError(f"{what} must be an integer, not {value!r}") from None
    if not lo <= n <= hi:
        raise HelperError(f"{what} must be between {lo} and {hi} (got {n})")
    return n


def check_pid(pid: int) -> None:
    if pid <= 1:
        raise HelperError("pid 1 and below are protected")
    if not os.path.isdir(f"/proc/{pid}"):
        raise HelperError(f"process {pid} does not exist")


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
    check_pid(pid)
    os.kill(pid, getattr(signal, f"SIG{name}"))
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


# -- services and memory ------------------------------------------------------
def cmd_service(args) -> dict:
    action = args.action
    if action not in SERVICE_ACTIONS:
        raise HelperError(f"action {action!r} not allowed")
    unit = args.unit if "." in args.unit else f"{args.unit}.service"
    if not UNIT_RE.match(unit):
        raise HelperError(f"invalid unit name: {args.unit!r}")
    if unit in PROTECTED_UNITS and action != "start":
        raise HelperError(f"{unit} is protected: your session needs it")
    run("systemctl", action, "--", unit, timeout=30)
    state = run("systemctl", "is-active", "--", unit) if action != "stop" else "inactive"
    return {"unit": unit, "action": action, "state": state}


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

    p = sub.add_parser("service"); p.add_argument("action"); p.add_argument("unit")
    p.set_defaults(fn=cmd_service)
    p = sub.add_parser("swappiness"); p.add_argument("value"); p.set_defaults(fn=cmd_swappiness)
    p = sub.add_parser("drop-caches"); p.add_argument("level", nargs="?", default="3")
    p.set_defaults(fn=cmd_drop_caches)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
