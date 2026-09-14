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

import psutil


class ActionError(Exception):
    """Action refused or failed; the message is meant for the user."""


# -- your own session's services ----------------------------------------------
SERVICE_ACTIONS = ("start", "stop", "restart")
# An ordinary first character (a leading "-" would look like an option to
# systemctl; the "--" in the argv is the second line of defence) and no
# .target. Backslash is allowed because systemd escapes "-" in the names Plasma
# gives launched apps (app-brave\x2dbrowser@....service); there is no shell
# for it to matter. Matched with fullmatch so nothing trails the name.
UNIT_RE = re.compile(r"[A-Za-z0-9@_][A-Za-z0-9@._:\\-]{0,127}\.(service|socket|timer|path)")
# Units the desktop session itself runs on, with what stopping them costs you.
# Matched on the unit's base name and its variants (pipewire-pulse,
# xdg-desktop-portal-kde). Restart stays allowed: that is how you recover them.
SESSION_UNITS = {
    "plasma-plasmashell": "your panel, desktop and widgets",
    "pipewire": "all sound",
    "wireplumber": "all sound",
    "xdg-desktop-portal": "file dialogs, screen sharing and the rest of the desktop "
                          "integration of sandboxed apps",
}


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
        try:
            p = psutil.Process(pid)
        except psutil.NoSuchProcess:
            raise ActionError(f"Process {pid} no longer exists.") from None
        if not self.owns(p):
            raise ActionError(
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
            raise ActionError(f"No permission to send {sig.name} to {pid}.") from None

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
            raise ActionError(
                f"Raising priority (nice {current} → {value}) is not possible without "
                "root privileges. Enable that via Overview → Root tasks."
            )
        try:
            p.nice(value)
        except psutil.AccessDenied:
            raise ActionError(f"No permission to change the nice value of {pid}.") from None
        except psutil.NoSuchProcess:
            raise ActionError(f"Process {pid} no longer exists.") from None

    def set_affinity(self, pid: int, cores: list[int]) -> None:
        if not cores:
            raise ActionError("Select at least one core.")
        p = self._proc(pid)
        try:
            p.cpu_affinity(sorted(set(cores)))
        except psutil.AccessDenied:
            raise ActionError(f"No permission to change the affinity of {pid}.") from None
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
            raise ActionError(
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
        base = unit.rsplit(".", 1)[0]
        if action == "stop":
            for name, effect in SESSION_UNITS.items():
                if base == name or base.startswith(name + "-"):
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

    def list_services(self) -> list[str]:
        """Unit names of your own session's services, as systemctl lists them."""
        out = systemctl_user("list-units", "--type=service", "--no-legend", "--plain", "--no-pager")
        return [line.split()[0] for line in out.splitlines() if line.strip()]


def get_backend() -> UserBackend:
    """Later: pick a PolkitBackend here if one is configured."""
    return UserBackend()
