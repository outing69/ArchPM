"""Actions on processes, behind a permissions layer.

Everything goes through a Backend. Today that is `UserBackend`: only your own
processes, and nice may only go up (less priority). If you later want more --
lowering nice, other users' processes, cgroups -- a `PolkitBackend` sits next
to it and the UI does not have to change.
"""
from __future__ import annotations

import os
import signal
from dataclasses import dataclass

import psutil


class ActionError(Exception):
    """Action refused or failed; the message is meant for the user."""


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


def get_backend() -> UserBackend:
    """Later: pick a PolkitBackend here if one is configured."""
    return UserBackend()
