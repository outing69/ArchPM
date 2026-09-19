"""Every command whose output ArchPM reads runs in the C locale, so a
parser gets the English it matches on. snapper is translated ("Keine
Berechtigungen."), and through 0.2.54 the Snapshots page matched its
English refusal without pinning the locale, so a German desktop saw an
error where the root read should have been offered. This walks every
subprocess call in the package: each must carry an env."""
from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

from archpm import toolenv

PACKAGE = Path(__file__).resolve().parent.parent / "archpm"
# the helper imports nothing from the package and pins its children itself
EXEMPT = {PACKAGE / "root" / "helper.py"}


def subprocess_calls(tree: ast.AST):
    """Calls of subprocess.run / Popen / check_output, and of an injected
    `run` (the modules take `run=subprocess.run` so tests can fake it)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        module_call = (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                       and f.value.id == "subprocess"
                       and f.attr in ("run", "Popen", "check_output"))
        injected = isinstance(f, ast.Name) and f.id == "run"
        if module_call or injected:
            yield node


class EveryToolRunsInEnglish(unittest.TestCase):
    def test_every_subprocess_call_pins_the_locale(self):
        missing = []
        for path in sorted(PACKAGE.rglob("*.py")):
            if path in EXEMPT:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for call in subprocess_calls(tree):
                if not any(k.arg == "env" for k in call.keywords):
                    missing.append(f"{path.relative_to(PACKAGE.parent)}:{call.lineno}")
        self.assertEqual(missing, [], "subprocess calls without an env")

    def test_the_helper_pins_its_children_itself(self):
        text = (PACKAGE / "root" / "helper.py").read_text(encoding="utf-8")
        self.assertIn('"LC_ALL": "C"', text)

    def test_english_keeps_the_session_and_forces_the_locale(self):
        env = toolenv.english()
        self.assertEqual(env["LC_ALL"], "C")
        for key in ("PATH", "HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
            if key in os.environ:
                self.assertEqual(env[key], os.environ[key], f"{key} must reach systemctl --user")
        self.assertIsNot(env, os.environ)
        self.assertNotEqual(os.environ.get("LC_ALL", "unset"), "C-from-the-test",
                            "the process's own environment is untouched")

    def test_the_snapshot_reads_get_it(self):
        from archpm import snapshots
        seen = []

        def run(argv, **kw):
            seen.append(kw.get("env", {}).get("LC_ALL"))
            raise OSError("not here")
        snapshots.snapper_configs(run)
        snapshots.read_as_user(snapshots.Setup(snapper=True, configs=["root"]), run)
        self.assertEqual(seen, ["C", "C"])


if __name__ == "__main__":
    unittest.main()
