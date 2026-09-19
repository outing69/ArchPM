"""Actions on processes, behind a permissions layer.

Everything goes through a Backend. Today that is `UserBackend`: only your own
processes, and nice may only go up (less priority). If you later want more --
lowering nice, other users' processes, cgroups -- a `PolkitBackend` sits next
to it and the UI does not have to change.

Services are handled here as well, and only your own session's: `systemctl
--user` run as you. That never involves the root helper. A root process running
`systemctl --user` would address root's own user manager, not yours, so
elevation is both wrong and unnecessary for it. System-wide services are not
managed by ArchPM at all.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
from dataclasses import dataclass
from typing import NamedTuple

import psutil

from .session import unit_loss


class ActionError(Exception):
    """Action refused or failed; the message is meant for the user."""


class EnabledService(NamedTuple):
    """A service of your session that systemd starts at every login."""
    unit: str
    description: str = ""
    active: bool = False


def parse_enabled_services(unit_files: str, units: str) -> list[EnabledService]:
    """`list-unit-files --state=enabled` names them; `list-units --all` adds the
    description and whether each one is running right now."""
    info: dict[str, tuple[str, bool]] = {}
    for line in units.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            desc = " ".join(parts[4:])
            info[parts[0]] = (desc if desc != parts[0] else "", parts[2] == "active")
    out = []
    for line in unit_files.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "enabled":
            desc, active = info.get(parts[0], ("", False))
            out.append(EnabledService(parts[0], desc, active))
    return sorted(out, key=lambda e: (e.description or e.unit).lower())


class Service(NamedTuple):
    unit: str
    description: str = ""     # empty when systemd has none beyond the unit name

    @property
    def label(self) -> str:
        """What a person can recognise: the description, with the unit after it."""
        return f"{self.description}  ({self.unit})" if self.description else self.unit


class Cancelled(ActionError):
    """No authorisation came out of the password prompt, so the helper never
    ran and nothing changed: the prompt was cancelled, or the password was
    not accepted. pkexec exits 126 for a dismissed dialog and 127 for no
    authorisation, but KDE's agent completes a cancelled dialog without an
    error, so polkit reports it as not authorised and pkexec says 127 for
    both; the client tells that apart from a plain refusal with pkcheck."""


class PermissionDenied(ActionError):
    """Refused for lack of privileges only: another user's process, a nice
    value below the current one, a realtime IO class. The elevated backend
    retries exactly these through the root helper, and nothing else: a
    refusal for any other reason (ArchPM itself, a process that is gone, bad
    input) is final and must not come back as root."""


# -- your own session's services ----------------------------------------------
SERVICE_ACTIONS = ("start", "stop", "restart")
# An ordinary first character (a leading "-" would look like an option to
# systemctl; the "--" in the argv is the second line of defence) and no
# .target. Backslash is allowed because systemd escapes "-" in the names Plasma
# gives launched apps (app-brave\x2dbrowser@....service); there is no shell
# for it to matter. Matched with fullmatch so nothing trails the name.
UNIT_RE = re.compile(r"[A-Za-z0-9@_][A-Za-z0-9@._:\\-]{0,127}\.(service|socket|timer|path)")
# Units the desktop session itself runs on come from session.py, the list
# the signal guard reads too. Restart stays allowed: that is how you recover them.


def systemctl_user(*args: str, timeout: int = 30) -> str:
    """Run `systemctl --user ...` as the current user, without a shell."""
    try:
        proc = subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError:
        raise ActionError("systemctl not found.") from None
    except subprocess.TimeoutExpired:
        raise ActionError(f"systemctl did not respond within {timeout}s.") from None
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        raise ActionError(lines[-1] if lines else f"systemctl returned code {proc.returncode}")
    return proc.stdout.strip()


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    reason: str = ""


class UserBackend:
    """Unprivileged: exactly what you are allowed to do as a regular user."""

    name = "user"

    def __init__(self) -> None:
        self.uid = os.getuid()

    # -- checks ------------------------------------------------------------
    def _proc(self, pid: int) -> psutil.Process:
        if pid <= 0:
            # A group row in the process list carries a negative pid; the view
            # expands it into its members before it gets here. Say so rather
            # than let psutil's ValueError escape.
            raise ActionError(f"{pid} is not a process.")
        try:
            p = psutil.Process(pid)
        except psutil.NoSuchProcess:
            raise ActionError(f"Process {pid} no longer exists.") from None
        if not self.owns(p):
            raise PermissionDenied(
                f"Process {pid} ({p.name()}) does not run under your account. "
                "Enable root actions via Overview → Root tasks."
            )
        return p

    def owns(self, p: psutil.Process) -> bool:
        if self.uid == 0:
            return True
        try:
            return p.uids().real == self.uid
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def capabilities(self) -> list[Capability]:
        return [
            Capability("signal-own", True),
            Capability("signal-any", False, "root required"),
            Capability("nice-up", True),
            Capability("nice-down", False, "root or CAP_SYS_NICE required"),
            Capability("affinity", True),
            Capability("ionice-idle", True),
        ]

    # -- actions -----------------------------------------------------------
    def send_signal(self, pid: int, sig: signal.Signals) -> None:
        p = self._proc(pid)
        if pid == os.getpid():
            raise ActionError("That is this application itself.")
        try:
            p.send_signal(sig)
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            raise PermissionDenied(f"No permission to send {sig.name} to {pid}.") from None

    def terminate(self, pid: int) -> None:
        self.send_signal(pid, signal.SIGTERM)

    def kill(self, pid: int) -> None:
        self.send_signal(pid, signal.SIGKILL)

    def suspend(self, pid: int) -> None:
        self.send_signal(pid, signal.SIGSTOP)

    def resume(self, pid: int) -> None:
        self.send_signal(pid, signal.SIGCONT)

    def set_nice(self, pid: int, value: int) -> None:
        p = self._proc(pid)
        try:
            current = p.nice()
        except psutil.Error:
            current = 0
        if value < current and self.uid != 0:
            raise PermissionDenied(
                f"Raising priority (nice {current} → {value}) is not possible without "
                "root privileges. Enable that via Overview → Root tasks."
            )
        try:
            p.nice(value)
        except psutil.AccessDenied:
            raise PermissionDenied(f"No permission to change the nice value of {pid}.") from None
        except psutil.NoSuchProcess:
            raise ActionError(f"Process {pid} no longer exists.") from None

    def set_affinity(self, pid: int, cores: list[int]) -> None:
        if not cores:
            raise ActionError("Select at least one core.")
        p = self._proc(pid)
        try:
            p.cpu_affinity(sorted(set(cores)))
        except psutil.AccessDenied:
            raise PermissionDenied(f"No permission to change the affinity of {pid}.") from None
        except (psutil.NoSuchProcess, ValueError) as exc:
            raise ActionError(str(exc)) from None

    def get_affinity(self, pid: int) -> list[int]:
        try:
            return psutil.Process(pid).cpu_affinity()
        except psutil.Error:
            return []

    def set_ionice(self, pid: int, klass: int, value: int = 4) -> None:
        p = self._proc(pid)
        try:
            if klass == psutil.IOPRIO_CLASS_IDLE:
                p.ionice(klass)
            else:
                p.ionice(klass, value)
        except psutil.AccessDenied:
            raise PermissionDenied(
                "This IO class requires root privileges (realtime), or the process is not yours."
            ) from None
        except psutil.Error as exc:
            raise ActionError(str(exc)) from None

    # -- your own session's services ---------------------------------------
    def service_argv(self, action: str, unit: str) -> list[str]:
        """Validate and build the `systemctl --user` command; runs nothing.

        The root panel starts this argv asynchronously so a slow stop does not
        freeze the window; `service` below runs it in place.
        """
        if action not in SERVICE_ACTIONS:
            raise ActionError(f"Action {action!r} is not allowed.")
        unit = unit.strip()
        if not unit:
            raise ActionError("Pick a service first.")
        if "." not in unit:
            unit = f"{unit}.service"
        if not UNIT_RE.fullmatch(unit):
            raise ActionError(f"{unit!r} is not a valid unit name.")
        if action == "stop":
            effect = unit_loss(unit)
            if effect:
                raise ActionError(
                    f"{unit} is part of your desktop session: stopping it takes "
                    f"{effect} down with it. Use Restart if it misbehaves."
                )
        return ["systemctl", "--user", action, "--", unit]

    def service(self, action: str, unit: str) -> str:
        """Start, stop or restart one of your own session's services; returns its state."""
        argv = self.service_argv(action, unit)
        systemctl_user(*argv[2:])
        return systemctl_user("show", "-p", "ActiveState", "--value", "--", argv[-1])

    def enabled_services(self) -> list[EnabledService]:
        """The services of your session that start at every login. All unit
        files are asked for and the parser keeps the enabled ones: with
        --state=enabled systemctl exits 1 when there are none, and that is an
        answer, not an error."""
        files = systemctl_user("list-unit-files", "--type=service",
                               "--no-legend", "--plain", "--no-pager")
        units = systemctl_user("list-units", "--all", "--type=service",
                               "--no-legend", "--plain", "--no-pager")
        return parse_enabled_services(files, units)

    def list_services(self) -> list[Service]:
        """Your own session's services, as systemctl lists them, each with its
        description: the unit names Plasma gives launched apps
        (app-brave\\x2dbrowser@89185f01fb3e42e38b610935c88efd87.service) say
        nothing to a person; "Brave - Web Browser" does."""
        out = systemctl_user("list-units", "--type=service", "--no-legend", "--plain", "--no-pager")
        services = []
        for line in out.splitlines():
            parts = line.split()
            if not parts:
                continue
            unit, description = parts[0], " ".join(parts[4:])
            services.append(Service(unit, description if description != unit else ""))
        return services


def get_backend() -> UserBackend:
    """Later: pick a PolkitBackend here if one is configured."""
    return UserBackend()
