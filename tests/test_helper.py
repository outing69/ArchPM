"""Tests for the validation in archpm-helper.

The helper is the security boundary of this project: it runs as root and takes
arguments from an unprivileged caller. Every refusal here is a rule that must
not silently disappear in a later change. Only refusal paths are exercised;
nothing in this file needs root or touches a real process.

Run with:  python3 -m unittest discover tests
"""
from __future__ import annotations

import contextlib
import io
import json
import os
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

    def test_rejects_everything_int_would_accept_but_we_do_not(self):
        # int() takes all of these; a root helper should not.
        for bad in ("+5", " 5 ", "5\n", "1_0", "\u0665", "\u0661\u0662", "5 "):
            with self.subTest(bad=bad), self.assertRaises(helper.HelperError):
                helper.as_int(bad, 0, 100, "x")

    def test_negative_is_allowed_when_in_range(self):
        self.assertEqual(helper.as_int("-10", -20, 19, "nice"), -10)


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

    def test_signal_refuses_system_account_processes(self):
        # pid 2 (kthreadd) runs as root on every Linux system; it must be refused
        # because of *who* it is, not because it is missing.
        with self.assertRaises(helper.HelperError) as ctx:
            helper.cmd_proc_signal(args(pid="2", signal="CONT"))
        self.assertIn("system account", str(ctx.exception))

    def test_signal_target_check_accepts_a_regular_user_process(self):
        if os.getuid() <= helper.SYSTEM_UID_MAX:
            self.skipTest("test itself runs as a system account")
        helper.check_signal_target(os.getpid())  # must not raise

    def test_signal_target_check_refuses_protected_cgroup(self):
        original = helper.proc_units
        helper.proc_units = lambda pid: {"sddm.service", "system.slice"}
        try:
            if os.getuid() <= helper.SYSTEM_UID_MAX:
                self.skipTest("test itself runs as a system account")
            with self.assertRaises(helper.HelperError) as ctx:
                helper.check_signal_target(os.getpid())
            self.assertIn("protected", str(ctx.exception))
        finally:
            helper.proc_units = original

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


class ServiceCommandRemoved(unittest.TestCase):
    """Services left the helper: your own session's run through systemctl --user
    as you (see tests/test_actions.py) and system services are not managed at
    all. An old client that still sends `service` gets a JSON refusal and no
    systemctl call is ever made."""

    def test_service_is_refused_as_json_before_anything_runs(self):
        calls: list[tuple[str, ...]] = []
        original, helper.run = helper.run, lambda *cmd, timeout=20: calls.append(cmd) or ""
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                code = helper.main(["service", "stop", "sshd"])
        finally:
            helper.run = original
        payload = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("no longer manages services", payload["error"])
        self.assertEqual(calls, [])

    def test_parser_has_no_service_subcommand(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            helper.build_parser().parse_args(["service", "restart", "sshd"])

    def test_service_machinery_is_gone_but_signal_protection_stays(self):
        for name in ("cmd_service", "unit_names", "DENIED_UNITS", "SERVICE_ACTIONS", "UNIT_RE"):
            self.assertFalse(hasattr(helper, name), name)
        self.assertIn("sddm.service", helper.PROTECTED_UNITS)
        self.assertIn("dbus.service", helper.PROTECTED_UNITS)


class MemoryCommands(unittest.TestCase):
    def test_swappiness_bounds(self):
        for value in ("-1", "201", "x"):
            with self.subTest(value=value), self.assertRaises(helper.HelperError):
                helper.cmd_swappiness(args(value=value))

    def test_drop_caches_level_bounds(self):
        for level in ("0", "4"):
            with self.subTest(level=level), self.assertRaises(helper.HelperError):
                helper.cmd_drop_caches(args(level=level))


class CleanupCommands(unittest.TestCase):
    """The two cleanup subcommands take nothing from the caller."""

    def test_take_no_arguments(self):
        for argv in (["paccache-clean", "-rk0"], ["paccache-clean", "/"],
                     ["journal-vacuum", "--vacuum-size=0"], ["journal-vacuum", "x"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), \
                    redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                helper.main(argv)

    def test_run_fixed_command_lines(self):
        calls = []

        def fake_run(*cmd, timeout=20):
            calls.append(cmd)
            return "done"
        original, helper.run = helper.run, fake_run
        try:
            helper.cmd_paccache_clean(None)
            helper.cmd_journal_vacuum(None)
        finally:
            helper.run = original
        self.assertEqual(calls, [("paccache", "-rk2"), ("journalctl", "--vacuum-size=100M")])


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

    def test_abbreviated_subcommands_are_rejected(self):
        for argv in (["proc", "2", "0"], ["serv", "stop", "x"], ["drop"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), \
                    redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                helper.main(argv)


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

    def test_helper_never_runs_systemctl(self):
        import inspect
        src = inspect.getsource(helper)
        self.assertNotIn('run("systemctl', src)
        self.assertNotIn('"systemctl",', src)

    def test_path_is_clean(self):
        self.assertTrue(all(p.startswith("/") for p in helper.PATH.split(":")))
