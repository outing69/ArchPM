"""The environment for a tool whose output ArchPM reads.

Several pages parse what a command prints: snapper's refusal ("No
permissions."), systemctl's columns, journalctl's "take up", paccache's
"candidates", pkcheck's "requires authentication", nvidia-smi's numbers.
Some of those tools are translated (snapper is: a German desktop says
"Keine Berechtigungen."), so every such call runs with LC_ALL=C and gets the
English the parser expects. The rest of the session's environment stays,
because systemctl --user and journalctl --user need the session's bus and
runtime directory. The root helper cannot import this and pins its own
children the same way; firewall.py pins a bare PATH as well.

A test walks every subprocess call in the package and refuses one without
an env, so a new parser cannot forget it.
"""
from __future__ import annotations

import os


def english() -> dict[str, str]:
    """This process's environment with the messages locale forced to C."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    return env
