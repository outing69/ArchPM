"""Checks before a signal is sent.

There is no undo for a signal, so the GUI asks here first: what is refused
outright, what needs a confirmation, and what the dialog should say in plain
language. No Qt in this file, so every rule is testable.

This guard acts on pids and process names. The service guard in actions.py
acts on unit names and does not cover this path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import psutil

from .model import ProcSample

# Processes the desktop session itself runs on, with what ending one costs you.
SESSION_PROCESSES = {
    "plasmashell": "the panel, the desktop and its widgets",
    "kwin": "the window borders and window switching, and on Wayland the whole screen",
    "pipewire": "all sound",
    "wireplumber": "all sound",
    "xdg-desktop-portal": "file dialogs and screen sharing for sandboxed apps",
}
SESSIONS_DIR = Path("/run/systemd/sessions")
MAX_LISTED = 6
MAX_COMMAND = 120

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


def session_loss(name: str) -> str:
    """What you lose when a process with this name ends; empty if nothing special.

    Matches the name itself and its variants (pipewire-pulse, kwin_wayland,
    xdg-desktop-portal-kde). /proc truncates names to 15 characters, so
    "xdg-desktop-por" must match too.
    """
    for key, loss in SESSION_PROCESSES.items():
        if name == key or name.startswith(key + "-") or name.startswith(key + "_"):
            return loss
        if len(name) == 15 and key.startswith(name):
            return loss
    return ""


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


def check(procs: list[ProcSample], sig_name: str, tree: bool = False,
          always_ask: bool = False, list_all: bool = False, self_pid: int | None = None,
          above: set[int] | None = None, leaders: set[int] | None = None) -> Verdict:
    """Decide for one signal to these processes. For a tree, pass the whole tree.

    list_all names every process, one short line each, for a group row that
    stands for all of them; otherwise the first few are described in full."""
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
    v.confirm = sig_name != "CONT" and (always_ask or sig_name == "KILL"
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
        parts = [describe(lead),
                 "Every process this reaches:\n" + "\n".join(
                     f"  {p.display_name} ({p.pid})" for p in procs)]
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
    v.text = "\n\n".join(parts + notes)
    return v
