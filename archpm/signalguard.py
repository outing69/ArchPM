"""Checks before a signal is sent.

There is no undo for a signal, so the GUI asks here first: what is refused
outright, what needs a confirmation, and what the dialog should say in plain
language. No Qt in this file, so every rule is testable.

This guard acts on pids and process names. The service guard in actions.py
acts on unit names; both read the desktop session's pieces from session.py.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

from .grouping import unit_of
from .helptext import CANNOT_UNDO
from .model import ProcSample
from .session import process_loss, unit_loss

SESSIONS_DIR = Path("/run/systemd/sessions")
RESTART_TIMEOUT = 2   # seconds for one systemctl show; measured at 4 ms, 7 ms worst
MAX_LISTED = 6
MAX_COMMAND = 120

def short(sig_name: str) -> str:
    """"SIGTERM", "sigterm" and "TERM" are the same signal here."""
    return sig_name.upper().removeprefix("SIG")


VERBS = {
    "TERM": ("Ask {} to quit?", "Quit"),
    "KILL": ("Force kill {}?", "Force kill"),
    "STOP": ("Pause {}?", "Pause"),
    "CONT": ("Resume {}?", "Resume"),
}


@dataclass
class Verdict:
    refused: str = ""        # why nothing may be sent; empty when allowed
    confirm: bool = False    # ask first
    title: str = ""
    text: str = ""
    button: str = ""         # label of the button that goes ahead


# What you lose when a process of the desktop session ends: the shared list
# in session.py, which the service guard in actions.py reads as well.
session_loss = process_loss


def ancestors(pid: int | None = None) -> set[int]:
    """The process itself and everything above it, up to but excluding pid 1."""
    pid = os.getpid() if pid is None else pid
    out: set[int] = set()
    try:
        p: psutil.Process | None = psutil.Process(pid)
        while p is not None and p.pid > 1 and p.pid not in out:
            out.add(p.pid)
            p = p.parent()
    except psutil.Error:
        pass
    return out


def session_leaders(uid: int | None = None, sessions_dir: Path = SESSIONS_DIR) -> set[int]:
    """Leader pids of this user's login sessions, as logind records them.

    Ending a session leader ends the session; on a desktop that is a logout.
    """
    uid = os.getuid() if uid is None else uid
    out: set[int] = set()
    try:
        files = list(sessions_dir.iterdir())
    except OSError:
        return out
    for f in files:
        try:
            fields = dict(line.split("=", 1) for line in f.read_text().splitlines() if "=" in line)
        except (OSError, ValueError):
            continue
        if fields.get("UID") == str(uid) and fields.get("LEADER", "").isdigit():
            out.add(int(fields["LEADER"]))
    return out


def describe(p: ProcSample) -> str:
    """Three plain lines: what it is, who runs it, what was typed to start it."""
    program = p.display_name if p.display_name == p.name else f"{p.display_name} ({p.name})"
    owner = p.username or "unknown"
    owner += " (you)" if p.owned else " (not you)"
    command = p.cmdline or "(not readable)"
    if len(command) > MAX_COMMAND:
        command = command[:MAX_COMMAND - 1] + "…"
    return f"Program: {program}, process {p.pid}\nRuns as: {owner}\nCommand: {command}"


ROLE_WORDS = {"page": ("page", "pages"), "extension": ("extension process", "extension processes"),
              "graphics": ("the graphics", "the graphics"), "helper": ("helper", "helpers")}


def group_loss(lead: ProcSample, procs: list[ProcSample]) -> str:
    """What ending a group takes: the program and everything that belongs to
    it, with the count, and for a browser what the members are. Process ids
    help nobody at that moment, so none are listed."""
    counts: dict[str, int] = {}
    for p in procs:
        if p.role:
            key = p.role if p.role in ("page", "extension", "graphics") else "helper"
            counts[key] = counts.get(key, 0) + 1
    head = (f"{lead.display_name} and everything that belongs to it: "
            f"{len(procs)} processes")
    if not counts:
        return head + "."
    bits = []
    for key in ("page", "extension", "graphics", "helper"):
        n = counts.get(key, 0)
        if n:
            one, many = ROLE_WORDS[key]
            bits.append(one if key == "graphics" else f"{n} {one if n == 1 else many}")
    text = head + ", among them " + ", ".join(bits) + "."
    if counts.get("page"):
        text += " Every open page closes with it."
    return text


def check(procs: list[ProcSample], sig_name: str, tree: bool = False,
          always_ask: bool = False, list_all: bool = False, self_pid: int | None = None,
          above: set[int] | None = None, leaders: set[int] | None = None) -> Verdict:
    """Decide for one signal to these processes. For a tree, pass the whole tree.

    list_all names every process, one short line each, for a group row that
    stands for all of them; otherwise the first few are described in full."""
    sig_name = short(sig_name)
    self_pid = os.getpid() if self_pid is None else self_pid
    above = ancestors(self_pid) if above is None else above
    leaders = session_leaders() if leaders is None else leaders
    v = Verdict()
    what = "this process tree" if tree else "these processes"

    for p in procs:
        who = f"{p.display_name} ({p.pid})"
        if p.pid == self_pid:
            v.refused = (f"{who} is ArchPM itself." if not tree else
                         f"ArchPM itself is part of {what}. Nothing was sent.")
            return v
        if p.pid in above:
            v.refused = (f"{who} started ArchPM, directly or indirectly. Ending it ends "
                         "ArchPM with it. Close ArchPM first and do this from elsewhere.")
            return v
        if p.pid in leaders:
            v.refused = (f"{who} leads your login session. Ending it logs you out "
                         "and closes everything. Nothing was sent.")
            return v

    foreign = [p for p in procs if not p.owned]
    session = [(p, session_loss(p.name)) for p in procs if session_loss(p.name)]
    # Terminate and Force kill always ask: there is no undo, and a single
    # process is no exception to that (an audit sent a real SIGTERM to a live
    # browser because it was). STOP asks for another account or the session.
    v.confirm = sig_name != "CONT" and (always_ask or sig_name in ("KILL", "TERM")
                                        or bool(foreign) or bool(session))
    if not v.confirm:
        return v

    # For a group the members come children first (that is the signalling
    # order); the one carrying the program's name leads the dialog.
    lead = next((p for p in procs if p.app_name), procs[0])
    question, v.button = VERBS.get(sig_name, (f"Send {sig_name} to {{}}?", "Send"))
    subject = (f"{procs[0].display_name}" if len(procs) == 1
               else f"{lead.display_name} and {len(procs) - 1} more" if list_all
               else f"{len(procs)} processes")
    v.title = question.format(subject)

    if list_all and len(procs) > 1:
        parts = [group_loss(lead, procs)]
    else:
        parts = [describe(p) for p in procs[:MAX_LISTED]]
        if len(procs) > MAX_LISTED:
            parts.append(f"and {len(procs) - MAX_LISTED} more.")
    notes = []
    if sig_name == "KILL":
        notes.append("It gets no chance to save anything. Unsaved work is lost.")
    if sig_name == "STOP":
        notes.append("It freezes until you choose Resume. The rest of the system carries on.")
    if foreign:
        names = ", ".join(sorted({p.username or "unknown" for p in foreign}))
        notes.append(f"This runs under another account ({names}), so it goes through "
                     "the root helper and can affect the whole system, not just yours.")
    seen_loss: set[str] = set()
    for p, loss in session:
        if loss in seen_loss:
            continue
        seen_loss.add(loss)
        verb = "Pausing" if sig_name == "STOP" else "Ending"
        notes.append(f"{p.name} is part of your desktop session. {verb} it takes {loss} with it.")
    if sig_name in ("TERM", "KILL"):
        notes.append(CANNOT_UNDO)
    v.text = "\n\n".join(parts + notes)
    return v


# -- a service that starts the process again -----------------------------------
# A process inside a unit with Restart= other than "no" comes back after it is
# ended; the dialog says so, and where to stop the service instead. The
# setting is read from systemctl only when a dialog is about to open, one
# call per service unit among the targets, never on the sampling cycle.
# Measured on this machine: 4 ms median, 7 ms worst, for user and system units.

def unit_of_process(p: ProcSample) -> tuple[str, bool]:
    """(unit, run by your own user manager?) from the cgroup path; ("", False) if none."""
    return unit_of(p.cgroup), "/user@" in p.cgroup


def restart_policy(unit: str, user: bool, run=subprocess.run) -> tuple[str, int]:
    """(Restart=, MainPID) of a unit. ("", 0) when systemctl cannot say, and for
    a scope, which has no Restart= at all."""
    argv = ["systemctl", *(["--user"] if user else []), "show",
            "-p", "Restart", "-p", "MainPID", "--value", "--", unit]
    try:
        proc = run(argv, capture_output=True, text=True, timeout=RESTART_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return "", 0
    lines = proc.stdout.splitlines()
    if proc.returncode != 0 or len(lines) < 2:
        return "", 0
    restart, main = lines[0].strip(), lines[1].strip()
    return restart, int(main) if main.isdigit() else 0


def comes_back(restart: str, sig_name: str) -> str:
    """How a unit with this Restart= answers this signal; "" when it stays down."""
    if restart in ("", "no"):
        return ""
    if restart == "always":
        return "starts it again right away, whatever happens"
    if restart == "on-success":
        # a forced kill is not a clean exit; asking to quit usually is
        return "starts it again after a clean exit, which asking it to quit usually is" \
            if sig_name == "TERM" else ""
    if restart in ("on-failure", "on-abnormal", "on-abort"):
        if sig_name == "KILL":
            return "starts it again: a forced kill counts as a failure"
        return ("starts it again if the program exits with an error; a program asked to "
                "quit usually exits cleanly and stays down")
    if restart == "on-watchdog":
        return ""
    return f"has Restart={restart} and may start it again"


def where_to_stop(unit: str, user: bool) -> str:
    if not user:
        return (f"It is a system service, which ArchPM does not manage; stopping it needs "
                f"root: sudo systemctl stop {unit}")
    loss = unit_loss(unit)
    if loss:
        return (f"It is part of your desktop session ({loss}); if it misbehaves, restart it "
                "under Root tasks → your session's services rather than ending it.")
    return (f"To end it for good, stop the service instead: Root tasks → your session's "
            f"services → {unit}.")


def restart_note(procs: list[ProcSample], sig_name: str, policy=restart_policy) -> str:
    """One paragraph per service unit whose main process is among the targets
    and which would start it again after this signal; "" when none."""
    sig_name = short(sig_name)
    if sig_name not in ("TERM", "KILL"):
        return ""
    by_unit: dict[tuple[str, bool], list[ProcSample]] = {}
    for p in procs:
        unit, user = unit_of_process(p)
        if unit.endswith(".service"):
            by_unit.setdefault((unit, user), []).append(p)
    notes = []
    for (unit, user), members in by_unit.items():
        restart, main_pid = policy(unit, user)
        answer = comes_back(restart, sig_name)
        if not answer or not main_pid or main_pid not in {p.pid for p in members}:
            continue   # stays down, or only a helper of the service is targeted
        main = next(p for p in members if p.pid == main_pid)
        notes.append(f"{main.display_name} runs as the service {unit}, which has "
                     f"Restart={restart} and {answer}. {where_to_stop(unit, user)}")
    return "\n\n".join(notes)
