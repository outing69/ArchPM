"""The three sections of the process list with every process shown: where a
process sits in the cgroup tree says what it is.

  Apps                  an app-… scope or service under your user manager:
                        what Plasma made when you started a program
  Background processes  the rest of your session, everything else under
                        user@.service, and a login session's own scope
  System processes      everything under system.slice, and the kernel's own
                        threads, which have no cgroup path but "/"

The cgroup is what the sampler already reads, so this costs no extra read.
When it could not be read at all, the owner decides: a uid below UID_MIN is
the system's, the rest is background. Not to be confused with the Category
column (Browser, Game, ...), which says what a program is for.

No Qt in this file.
"""
from __future__ import annotations

import re

APPS, BACKGROUND, SYSTEM = "apps", "background", "system"
SECTIONS = (
    (APPS, "Apps",
     "Programs you started: everything in an app-… unit of your session, which is how "
     "Plasma files what you launch, helpers included."),
    (BACKGROUND, "Background processes",
     "The rest of your session: your enabled services, Plasma's own parts, D-Bus helpers, "
     "and the session's own scope."),
    (SYSTEM, "System processes",
     "Everything under system.slice (system services, the display manager, other users' "
     "daemons) and the kernel's own threads."),
)
LABEL = {key: label for key, label, _ in SECTIONS}
ABOUT = {key: about for key, _, about in SECTIONS}
RANK = {key: i for i, (key, _, _) in enumerate(SECTIONS)}
# Reserved pids for the section rows, far below where group rows go (-1, -2, ...).
SECTION_PID = {APPS: -1_000_001, BACKGROUND: -1_000_002, SYSTEM: -1_000_003}
KEY_OF_PID = {pid: key for key, pid in SECTION_PID.items()}
UID_MIN_DEFAULT = 1000
LOGIN_DEFS = "/etc/login.defs"

_APP_UNIT = re.compile(r"/app-[^/]+\.(?:scope|service)(?:/|$)")


def is_section(pid: int) -> bool:
    return pid in KEY_OF_PID


def cgroup_path(text: str) -> str:
    """The path in a /proc/<pid>/cgroup line, "0::/user.slice/…". Split at the
    second colon, not the last: a dbus-activated unit carries one in its name
    (dbus-:1.2-org.kde.kwalletd6@0.service). "" when there is no such line."""
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0":
            return parts[2].strip()
    return ""


def uid_min(path: str = LOGIN_DEFS) -> int:
    try:
        with open(path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "UID_MIN" and parts[1].isdigit():
                    return int(parts[1])
    except OSError:
        pass
    return UID_MIN_DEFAULT


def section_of(cgroup: str, uid: int, uid_floor: int = UID_MIN_DEFAULT) -> tuple[str, bool]:
    """(section, fell back to the owner?) for a process."""
    if cgroup.startswith("/"):
        if "/user@" in cgroup:
            return (APPS if _APP_UNIT.search(cgroup) else BACKGROUND), False
        if cgroup.startswith("/user.slice/"):
            return BACKGROUND, False      # a login session's own scope, no user manager
        return SYSTEM, False              # system.slice, init.scope, and "/" for kernel threads
    return (SYSTEM if 0 <= uid < uid_floor else BACKGROUND), True
