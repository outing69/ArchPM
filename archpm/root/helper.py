#!/usr/bin/env python3
"""archpm-helper -- the only piece of ArchPM that runs as root.

Invoked via pkexec, one action per call, and replies with JSON on stdout.
Limited to process management, memory, two fixed cleanup commands (package
cache, journal), filesystem snapshots (list, take, delete; never restore:
that changes what the machine boots and stays outside ArchPM) and one look
at the firewall's own status output (ufw's or firewalld's; it changes no
rule and switches nothing on or off); GPU tuning
belongs in a different tool, and services are not managed here at all: ArchPM
only touches your own session's services, which need no root (see actions.py).
Deliberately stdlib-only and without imports from the archpm package: this
file lives root-owned in /usr/lib/archpm/ (or /usr/local/lib/archpm/ when
installed from a checkout) and must not be able to load anything from a
directory a regular user can write to.

Everything that comes in is validated: fixed subcommands, numeric bounds, a
fixed character set for a snapshot's description, and
one target check for every process command (signal, nice, affinity, IO class):
only a regular user's process, never one inside a unit your session or the
system would collapse without, and pinned by a pidfd so a recycled pid cannot
become the target. A shell is never started.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import signal
import subprocess
import sys
import time

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
# Processes of system accounts (root, polkitd, dbus, ...) are never touched:
# that is how you would kill logind or the display manager by pid, or renice
# journald, and bypass the unit protection above. A regular user is what
# /etc/login.defs calls UID_MIN to UID_MAX, 1000 to 60000 on Arch and most
# distributions. Above that range sit nobody (65534) and systemd's DynamicUser
# accounts (61184 to 65519), and neither is a person whose processes the helper
# should touch, so an upper bound matters as much as the lower one.
REGULAR_UID_RANGE = (1000, 60000)
LOGIN_DEFS = "/etc/login.defs"


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


def regular_uid_range(path: str = LOGIN_DEFS) -> tuple[int, int]:
    """UID_MIN and UID_MAX from login.defs, root-owned like this file; the
    usual 1000 to 60000 when the file is missing or says something odd."""
    lo, hi = REGULAR_UID_RANGE
    found = {}
    try:
        with open(path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] in ("UID_MIN", "UID_MAX") and parts[1].isdigit():
                    found[parts[0]] = int(parts[1])
    except OSError:
        return lo, hi
    lo, hi = found.get("UID_MIN", lo), found.get("UID_MAX", hi)
    if not 1 <= lo <= hi:
        return REGULAR_UID_RANGE
    return lo, hi


def is_regular_uid(uid: int, uid_range: tuple[int, int] | None = None) -> bool:
    lo, hi = regular_uid_range() if uid_range is None else uid_range
    return lo <= uid <= hi


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


def units_in(cgroup_text: str) -> set[str]:
    """systemd units a /proc/<pid>/cgroup path passes through, e.g. {'sddm.service'}.
    The line is "0::/path"; split at the second colon, not the last, since a
    dbus-activated unit carries a colon in its name."""
    for line in cgroup_text.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0":
            return {part for part in parts[2].split("/") if "." in part}
    return set()


def proc_units(pid: int) -> set[str]:
    try:
        with open(f"/proc/{pid}/cgroup") as fh:
            return units_in(fh.read())
    except OSError:
        return set()


def check_target(pid: int) -> None:
    """Refuse pids the helper must never touch, whatever the caller says. The
    same rule for a signal, a nice value, an affinity mask and an IO class."""
    uid = proc_uid(pid)
    lo, hi = regular_uid_range()
    if not is_regular_uid(uid, (lo, hi)):
        raise HelperError(
            f"process {pid} runs as uid {uid}, which is not a regular user ({lo} to {hi}); "
            "the helper only acts on processes of regular users"
        )
    hit = proc_units(pid) & PROTECTED_UNITS
    if hit:
        raise HelperError(f"process {pid} belongs to {sorted(hit)[0]}, which is protected")


def pin(pid: int) -> int:
    """A pidfd for the process, opened before anything is looked at."""
    try:
        return os.pidfd_open(pid)
    except ProcessLookupError:
        raise HelperError(f"process {pid} does not exist") from None


def exited(fd: int) -> bool:
    """True once the process behind the pidfd has exited: the descriptor becomes readable."""
    poller = select.poll()
    poller.register(fd, select.POLLIN)
    return bool(poller.poll(0))


def change(pid: int, apply) -> dict:
    """Run `apply` on the process that passed the target check, and on that one only.

    setpriority, sched_setaffinity and ionice address a pid, not a pidfd, so
    the pidfd cannot carry the change the way it carries a signal. What it can
    do is tell whether the process the check looked at was still alive when
    the change was done. A pid is only handed out again once its process has
    exited, so a pidfd that has not become readable means the pid named the
    same process throughout; one that has means the change may have reached
    a newcomer, and that is reported instead of hidden."""
    fd = pin(pid)
    try:
        check_target(pid)
        try:
            result = apply()
        except ProcessLookupError:
            raise HelperError(f"process {pid} does not exist") from None
        if exited(fd):
            raise HelperError(f"process {pid} ended while it was being changed; the change "
                              "may have reached a process that reused its pid")
        return result
    finally:
        os.close(fd)


# -- processes ----------------------------------------------------------------
def cmd_proc_nice(args) -> dict:
    pid = as_int(args.pid, 2, 2**22, "pid")
    value = as_int(args.value, -20, 19, "nice")

    def apply() -> dict:
        os.setpriority(os.PRIO_PROCESS, pid, value)
        return {"pid": pid, "nice": os.getpriority(os.PRIO_PROCESS, pid)}
    return change(pid, apply)


def cmd_proc_signal(args) -> dict:
    pid = as_int(args.pid, 2, 2**22, "pid")
    name = args.signal.upper().removeprefix("SIG")
    if name not in ALLOWED_SIGNALS:
        raise HelperError(f"signal {name} not allowed")
    # The pidfd pins the process *before* we look at who it is and carries the
    # signal itself, so a pid recycled between the check and the signal cannot
    # receive it.
    fd = pin(pid)
    try:
        check_target(pid)
        signal.pidfd_send_signal(fd, getattr(signal, f"SIG{name}"))
    except ProcessLookupError:
        raise HelperError(f"process {pid} does not exist") from None
    finally:
        os.close(fd)
    return {"pid": pid, "signal": name}


def cmd_proc_affinity(args) -> dict:
    pid = as_int(args.pid, 2, 2**22, "pid")
    ncpu = os.cpu_count() or 1
    cores = {as_int(c, 0, ncpu - 1, "core") for c in args.cores.split(",") if c != ""}
    if not cores:
        raise HelperError("no cores specified")

    def apply() -> dict:
        os.sched_setaffinity(pid, cores)
        return {"pid": pid, "affinity": sorted(os.sched_getaffinity(pid))}
    return change(pid, apply)


def cmd_proc_ionice(args) -> dict:
    pid = as_int(args.pid, 2, 2**22, "pid")
    klass = as_int(args.klass, 0, 3, "IO class")
    value = as_int(args.value, 0, 7, "IO priority")

    def apply() -> dict:
        run("ionice", "-c", str(klass), *(() if klass == 3 else ("-n", str(value))),
            "-p", str(pid))
        return {"pid": pid, "class": klass, "level": value}
    return change(pid, apply)


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


# -- snapshots: Snapper or Timeshift, fixed commands, one validated name and
# one validated description; the description's character set is the only
# free text this helper ever passes on, and it is checked here again --------
SNAPPER_CONFIG_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
# letters, digits, space, dot, underscore, hyphen; at most 72 (snap-pac's limit)
DESCRIPTION_RE = re.compile(r"[A-Za-z0-9 ._-]{0,72}")
TIMESHIFT_NAME_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}")
TIMESHIFT = "timeshift"
SNAPPER_BIN, TIMESHIFT_BIN = "/usr/bin/snapper", "/usr/bin/timeshift"


def snapshot_tool() -> str:
    """snapper when it is installed, else timeshift, else an error."""
    if os.path.isfile(SNAPPER_BIN):
        return "snapper"
    if os.path.isfile(TIMESHIFT_BIN):
        return TIMESHIFT
    raise HelperError("neither snapper nor timeshift is installed")


def snapper_configs() -> list[str]:
    try:
        data = json.loads(run("snapper", "--jsonout", "list-configs") or "{}")
    except ValueError:
        raise HelperError("snapper list-configs gave no JSON") from None
    return [c.get("config", "") for c in data.get("configs", []) if c.get("config")]


def check_config(config: str) -> str:
    """The tool the config belongs to: "snapper" for one of snapper's configs,
    "timeshift" for the literal name timeshift when that is the tool."""
    if not SNAPPER_CONFIG_RE.fullmatch(config):
        raise HelperError(f"config name not allowed: {config!r}")
    tool = snapshot_tool()
    if tool == "snapper":
        if config not in snapper_configs():
            raise HelperError(f"snapper has no config named {config!r}")
        return "snapper"
    if config != TIMESHIFT:
        raise HelperError(f"timeshift has no configs; the config must be {TIMESHIFT!r}")
    return TIMESHIFT


def check_description(text: str) -> str:
    if not DESCRIPTION_RE.fullmatch(text):
        raise HelperError("the description may hold letters, digits, space, dot, underscore "
                          "and hyphen, at most 72 of them")
    return text.strip()


def snapper_numbers(config: str) -> list[int]:
    """The snapshot numbers of a config, from the same listing the page reads."""
    try:
        data = json.loads(run("snapper", "--jsonout", "--utc", "--iso", "-c", config, "list") or "{}")
    except ValueError:
        raise HelperError("snapper list gave no JSON") from None
    rows = data.get(config) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        rows = next((v for v in data.values() if isinstance(v, list)), []) \
            if isinstance(data, dict) else []
    return [r["number"] for r in rows if isinstance(r, dict)
            and isinstance(r.get("number"), int) and r["number"] > 0]


def timeshift_names() -> list[str]:
    out = run("timeshift", "--list", timeout=60)
    return [m.group(1) for m in (re.match(r"\s*\d+\s+>?\s*(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", l)
                                 for l in out.splitlines()) if m]


def cmd_snapshots_list(_args) -> dict:
    """The raw listing per config; the page parses it with the same code as
    the plain read. The time is the tool's own, without polkit's."""
    tool = snapshot_tool()
    start = time.perf_counter()
    outputs = []
    if tool == "snapper":
        for config in snapper_configs():
            outputs.append([config, run("snapper", "--jsonout", "--utc", "--iso",
                                        "-c", config, "list")])
    else:
        outputs.append([TIMESHIFT, run("timeshift", "--list", timeout=60)])
    return {"tool": tool, "outputs": outputs, "took_ms": (time.perf_counter() - start) * 1000}


def cmd_snapshots_create(args) -> dict:
    tool = check_config(args.config)
    desc = check_description(args.description or "")
    if tool == "snapper":
        cmd = ["snapper", "-c", args.config, "create", "--type", "single",
               "--userdata", "made-by=archpm", "--print-number"]
        if desc:
            cmd += ["--description", desc]
        out = run(*cmd, timeout=120)
        return {"id": out.strip().splitlines()[-1] if out else ""}
    cmd = ["timeshift", "--create", "--scripted", "--tags", "O"]
    if desc:
        cmd += ["--comments", desc]
    before = set(timeshift_names())
    run(*cmd, timeout=600)
    new = sorted(set(timeshift_names()) - before)
    return {"id": new[-1] if new else ""}


def cmd_snapshots_delete(args) -> dict:
    """Never the last one: a machine with no snapshot has no way back, and a
    page that can take that away by one click should not exist."""
    tool = check_config(args.config)
    if tool == "snapper":
        number = as_int(args.id, 1, 2**31 - 1, "snapshot number")
        have = snapper_numbers(args.config)
        if number not in have:
            raise HelperError(f"snapshot {number} does not exist in config {args.config!r}")
        if len(have) <= 1:
            raise HelperError("this is the last snapshot; the helper does not delete the last one")
        run("snapper", "-c", args.config, "delete", str(number), timeout=120)
        return {"deleted": number, "remaining": len(have) - 1}
    if not TIMESHIFT_NAME_RE.fullmatch(args.id):
        raise HelperError(f"not a timeshift snapshot name: {args.id!r}")
    have = timeshift_names()
    if args.id not in have:
        raise HelperError(f"timeshift has no snapshot {args.id}")
    if len(have) <= 1:
        raise HelperError("this is the last snapshot; the helper does not delete the last one")
    run("timeshift", "--delete", "--scripted", "--snapshot", args.id, timeout=600)
    return {"deleted": args.id, "remaining": len(have) - 1}


# -- firewall: one fixed, read-only command, nothing from the caller ---------
UFW_BIN, FIREWALL_CMD_BIN = "/usr/bin/ufw", "/usr/bin/firewall-cmd"


def cmd_firewall_status(_args) -> dict:
    """The firewall's own status text, for the Network page to parse: `ufw
    status verbose` when ufw is installed, else firewalld's state, default
    zone and that zone's listing. Read-only: no rule is added or removed
    and the firewall is not switched on or off, here or anywhere in ArchPM.
    The raw nftables ruleset is never returned."""
    start = time.perf_counter()
    if os.path.isfile(UFW_BIN):
        outputs = [["status", run("ufw", "status", "verbose")]]
        return {"tool": "ufw", "outputs": outputs,
                "took_ms": (time.perf_counter() - start) * 1000}
    if os.path.isfile(FIREWALL_CMD_BIN):
        try:
            state = run("firewall-cmd", "--state")
        except HelperError as exc:      # exit 252: "not running"
            if "not running" not in str(exc):
                raise
            outputs = [["state", "not running"]]
        else:
            zone = run("firewall-cmd", "--get-default-zone")
            outputs = [["state", state], ["zone", zone],
                       ["list-all", run("firewall-cmd", f"--zone={zone}", "--list-all")]]
        return {"tool": "firewalld", "outputs": outputs,
                "took_ms": (time.perf_counter() - start) * 1000}
    raise HelperError("neither ufw nor firewalld is installed")


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
    sub.add_parser("snapshots-list").set_defaults(fn=cmd_snapshots_list)
    p = sub.add_parser("snapshots-create"); p.add_argument("config")
    p.add_argument("description", nargs="?", default="")
    p.set_defaults(fn=cmd_snapshots_create)
    p = sub.add_parser("snapshots-delete"); p.add_argument("config"); p.add_argument("id")
    p.set_defaults(fn=cmd_snapshots_delete)
    sub.add_parser("firewall-status").set_defaults(fn=cmd_firewall_status)
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
