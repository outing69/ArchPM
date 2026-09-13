"""Tests for the validation in archpm-helper.

The helper is the security boundary of this project: it runs as root and takes
arguments from an unprivileged caller. Every refusal here is a rule that must
not silently disappear in a later change. Only refusal paths are exercised;
nothing in this file needs root or touches a real process.

Run with:  python3 -m unittest discover tests
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from archpm.root import helper


def args(**kw) -> SimpleNamespace:
    return SimpleNamespace(**kw)


class AsInt(unittest.TestCase):
    def test_accepts_bounds_inclusive(self):
        self.assertEqual(helper.as_int("0", 0, 7, "x"), 0)
        self.assertEqual(helper.as_int("7", 0, 7, "x"), 7)

    def test_rejects_out_of_range(self):
        with self.assertRaises(helper.HelperError):
            helper.as_int("8", 0, 7, "x")
        with self.assertRaises(helper.HelperError):
            helper.as_int("-1", 0, 7, "x")

    def test_rejects_non_integer(self):
        for bad in ("abc", "1.5", "", "1; rm -rf /", "0x10"):
            with self.subTest(bad=bad), self.assertRaises(helper.HelperError):
                helper.as_int(bad, 0, 100, "x")


class CheckPid(unittest.TestCase):
    def test_protects_pid_1_and_below(self):
        for pid in (1, 0, -1):
            with self.subTest(pid=pid), self.assertRaises(helper.HelperError):
                helper.check_pid(pid)

    def test_rejects_nonexistent_pid(self):
        with self.assertRaises(helper.HelperError):
            helper.check_pid(2**22)


class ProcCommands(unittest.TestCase):
    def test_nice_rejects_pid_1(self):
        with self.assertRaises(helper.HelperError):
            helper.cmd_proc_nice(args(pid="1", value="0"))

    def test_nice_rejects_out_of_range_value(self):
        for value in ("-21", "20"):
            with self.subTest(value=value), self.assertRaises(helper.HelperError):
                helper.cmd_proc_nice(args(pid="99999999", value=value))

    def test_signal_rejects_unlisted_signals(self):
        for sig in ("SEGV", "ABRT", "KILLALL", "9", ""):
            with self.subTest(sig=sig), self.assertRaises(helper.HelperError):
                helper.cmd_proc_signal(args(pid="99999999", signal=sig))

    def test_signal_rejects_pid_1_even_for_allowed_signal(self):
        with self.assertRaises(helper.HelperError):
            helper.cmd_proc_signal(args(pid="1", signal="TERM"))

    def test_affinity_rejects_empty_and_out_of_range_cores(self):
        with self.assertRaises(helper.HelperError):
            helper.cmd_proc_affinity(args(pid="1", cores=""))
        with self.assertRaises(helper.HelperError):
            helper.cmd_proc_affinity(args(pid="1", cores="0,99999"))

    def test_ionice_rejects_bad_class_and_priority(self):
        with self.assertRaises(helper.HelperError):
            helper.cmd_proc_ionice(args(pid="1", klass="4", value="0"))
        with self.assertRaises(helper.HelperError):
            helper.cmd_proc_ionice(args(pid="1", klass="2", value="8"))


class ServiceCommand(unittest.TestCase):
    def test_rejects_unknown_action(self):
        for action in ("enable", "disable", "mask", "kill", "daemon-reexec", ""):
            with self.subTest(action=action), self.assertRaises(helper.HelperError):
                helper.cmd_service(args(action=action, unit="sshd"))

    def test_rejects_invalid_unit_names(self):
        for unit in ("../etc", "a b", "unit;reboot", "$(id)", "x" * 200 + ".service",
                     "foo.conf", "-flag.service", "--no-block.service", "-.service"):
            with self.subTest(unit=unit), self.assertRaises(helper.HelperError) as ctx:
                helper.cmd_service(args(action="restart", unit=unit))
            # The helper itself must refuse; a failure from systemctl does not count.
            self.assertIn("invalid unit name", str(ctx.exception))

    def test_accepts_ordinary_unit_names(self):
        for unit in ("sshd.service", "bluetooth", "user@1000.service", "systemd-timesyncd",
                     "dbus-:1.2-org.example@0.service"):
            with self.subTest(unit=unit):
                full = unit if "." in unit else f"{unit}.service"
                self.assertIsNotNone(helper.UNIT_RE.match(full))

    def test_refuses_to_stop_or_restart_protected_units(self):
        for unit in sorted(helper.PROTECTED_UNITS):
            for action in ("stop", "restart"):
                with self.subTest(unit=unit, action=action), \
                        self.assertRaises(helper.HelperError):
                    helper.cmd_service(args(action=action, unit=unit))

    def test_protected_units_also_match_without_suffix(self):
        with self.assertRaises(helper.HelperError):
            helper.cmd_service(args(action="stop", unit="polkit"))


class MemoryCommands(unittest.TestCase):
    def test_swappiness_bounds(self):
        for value in ("-1", "201", "x"):
            with self.subTest(value=value), self.assertRaises(helper.HelperError):
                helper.cmd_swappiness(args(value=value))

    def test_drop_caches_level_bounds(self):
        for level in ("0", "4"):
            with self.subTest(level=level), self.assertRaises(helper.HelperError):
                helper.cmd_drop_caches(args(level=level))


class MainProtocol(unittest.TestCase):
    """The GUI relies on the JSON contract: one object per call with an `ok` key."""

    def run_main(self, *argv: str) -> tuple[int, dict]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = helper.main(list(argv))
        return code, json.loads(out.getvalue())

    def test_refusal_is_reported_as_json_not_exception(self):
        code, payload = self.run_main("proc-nice", "1", "0")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("pid", payload["error"])

    def test_status_needs_no_privileges(self):
        code, payload = self.run_main("status")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertIn("uid", payload["result"])

    def test_unknown_subcommand_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            helper.main(["reboot"])


class HardeningInvariants(unittest.TestCase):
    """Properties of the helper source that a reviewer would otherwise check by hand."""

    def test_no_shell_is_ever_used(self):
        import inspect
        src = inspect.getsource(helper)
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)

    def test_helper_imports_nothing_from_the_archpm_package(self):
        import inspect
        src = inspect.getsource(helper)
        self.assertNotIn("from .", src)
        self.assertNotIn("from archpm", src)
        self.assertNotIn("import archpm", src)

    def test_path_is_clean(self):
        self.assertTrue(all(p.startswith("/") for p in helper.PATH.split(":")))
