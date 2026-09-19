"""The user side of the root layer.

Nothing in this file runs as root; it only builds calls to
`pkexec /usr/lib/archpm/archpm-helper …` and translates the JSON reply back.
That keeps the separation strict: the GUI knows no passwords and runs no shell
commands, polkit does the authentication and the helper script does the
validation.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..actions import ActionError, PermissionDenied, UserBackend

# The distribution package installs the helper under /usr/lib, install.sh under
# /usr/local/lib. Prefer the package if both exist; report the manual path when neither does.
_HELPER_CANDIDATES = (
    Path("/usr/lib/archpm/archpm-helper"),
    Path("/usr/local/lib/archpm/archpm-helper"),
)
HELPER = next((p for p in _HELPER_CANDIDATES if p.is_file()), _HELPER_CANDIDATES[1])
POLICY = Path("/usr/share/polkit-1/actions/io.github.outing69.archpm.policy")
# One polkit action per helper subcommand: ACTION_PREFIX + the subcommand.
# The two reads (snapshots-list, firewall-status) keep an authentication for
# a few minutes; every change asks for the password again.
ACTION_PREFIX = "io.github.outing69.archpm.helper."

# pkexec exit codes that do not come from the helper itself
_PKEXEC_DISMISSED = 126
_PKEXEC_NOT_AUTHORISED = 127


@dataclass(frozen=True)
class RootStatus:
    helper: bool
    policy: bool
    pkexec: bool

    @property
    def ready(self) -> bool:
        return self.helper and self.policy and self.pkexec

    @property
    def problem(self) -> str:
        if not self.pkexec:
            return "pkexec is missing: install the 'polkit' package."
        if not self.helper:
            return f"helper not installed at {HELPER}"
        if not self.policy:
            return f"polkit policy not installed at {POLICY}"
        return ""


def check() -> RootStatus:
    return RootStatus(
        helper=HELPER.is_file(),
        policy=POLICY.is_file(),
        pkexec=shutil.which("pkexec") is not None,
    )


class RootClient:
    """Calls the helper. It keeps no notion of being "unlocked": polkit keeps
    an authentication only for the two reads, and a change asks every time."""

    def argv(self, *args: str, elevated: bool = True) -> list[str]:
        cmd = [str(HELPER), *args]
        return ["pkexec", *cmd] if elevated else cmd

    # ------------------------------------------------------------------
    def call(self, *args: str, elevated: bool = True, timeout: int = 180) -> dict:
        status = check()
        if elevated and not status.ready:
            raise ActionError(status.problem)
        if not elevated and not status.helper:
            raise ActionError(status.problem)
        try:
            proc = subprocess.run(
                self.argv(*args, elevated=elevated),
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            raise ActionError("The helper did not respond in time.") from None
        except OSError as exc:
            raise ActionError(str(exc)) from None
        return self.parse(proc.returncode, proc.stdout, proc.stderr)

    @staticmethod
    def parse(code: int, stdout: str, stderr: str) -> dict:
        """The helper's reply, or pkexec's exit code when there is none. Also
        used by the asynchronous QProcess variant in the UI."""
        text = (stdout or "").strip()
        if text:
            try:
                payload = json.loads(text.splitlines()[-1])
            except (ValueError, IndexError):
                payload = None
            if isinstance(payload, dict) and "ok" in payload:
                if payload["ok"]:
                    return payload.get("result") or {}
                raise ActionError(payload.get("error") or "unknown error")

        if code == _PKEXEC_DISMISSED:
            raise ActionError("Authentication cancelled.")
        if code == _PKEXEC_NOT_AUTHORISED:
            raise ActionError(
                "Not authorised. Is your account in the wheel group, and is the "
                "polkit policy installed?"
            )
        detail = (stderr or "").strip().splitlines()
        raise ActionError(detail[-1] if detail else f"helper returned exit code {code}")

    # -- convenience methods -----------------------------------------------
    @staticmethod
    def status() -> dict:
        """The helper's status: its uid and the current swappiness.

        Reading requires no privileges, so we do it in-process with the local
        copy of the helper. That way the panel fills in its controls even when
        the root helper is not installed yet.
        """
        from .helper import HelperError, cmd_status
        try:
            return cmd_status(None)
        except (HelperError, OSError) as exc:
            raise ActionError(str(exc)) from None


class ElevatedBackend(UserBackend):
    """Same interface as UserBackend, but falls back to the root helper.

    Try without privileges first: that is faster and most actions on your own
    processes need no root at all. Only a refusal for lack of privileges goes
    through pkexec. Every other refusal (ArchPM itself, a process that is
    gone, bad input) stands: root would not make it right, it would make it
    happen.
    """

    name = "root"

    def __init__(self, client: RootClient) -> None:
        super().__init__()
        self.client = client

    def capabilities(self):
        caps = super().capabilities()
        return [type(c)(c.name, True, "") for c in caps]

    def _fallback(self, fn, *args: str):
        try:
            return fn()
        except PermissionDenied:
            return self.client.call(*args)

    def send_signal(self, pid, sig):
        self._fallback(lambda: super(ElevatedBackend, self).send_signal(pid, sig),
                       "proc-signal", str(pid), sig.name)

    def set_nice(self, pid, value):
        self._fallback(lambda: super(ElevatedBackend, self).set_nice(pid, value),
                       "proc-nice", str(pid), str(value))

    def set_affinity(self, pid, cores):
        self._fallback(lambda: super(ElevatedBackend, self).set_affinity(pid, cores),
                       "proc-affinity", str(pid), ",".join(str(c) for c in sorted(set(cores))))

    def set_ionice(self, pid, klass, value=4):
        self._fallback(lambda: super(ElevatedBackend, self).set_ionice(pid, klass, value),
                       "proc-ionice", str(pid), str(int(klass)), str(value))
