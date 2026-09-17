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
import subprocess
import tempfile
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


def regular() -> bool:
    return helper.is_regular_uid(os.getuid())


@contextlib.contextmanager
def target_uid(uid: int):
    """Make the helper see every target as running under `uid`. The tests
    then use their own pid, which exists everywhere; a real root process
    such as kthreadd is not there in a build chroot with its own pid
    namespace, and a test must not hope for one."""
    original = helper.proc_uid
    helper.proc_uid = lambda pid: uid
    try:
        yield
    finally:
        helper.proc_uid = original


class RegularUsers(unittest.TestCase):
    """Who the helper acts for: UID_MIN to UID_MAX, nothing below, nothing above."""

    RANGE = (1000, 60000)

    def test_system_accounts_nobody_and_dynamic_users_are_not_regular(self):
        for uid in (0, 1, 81, 999, 60001, 61184, 63000, 65519, 65534, 4294967294):
            with self.subTest(uid=uid):
                self.assertFalse(helper.is_regular_uid(uid, self.RANGE))

    def test_the_range_itself_is_regular_inclusive(self):
        for uid in (1000, 1001, 59999, 60000):
            with self.subTest(uid=uid):
                self.assertTrue(helper.is_regular_uid(uid, self.RANGE))

    def test_range_read_from_login_defs(self):
        with tempfile.NamedTemporaryFile("w", suffix=".defs", delete=False) as fh:
            fh.write("# comment\nUID_MIN\t\t 500\nUID_MAX\t\t60000\nSYS_UID_MAX 499\n")
            path = fh.name
        try:
            self.assertEqual(helper.regular_uid_range(path), (500, 60000))
        finally:
            os.unlink(path)

    def test_missing_or_odd_login_defs_gives_the_usual_range(self):
        self.assertEqual(helper.regular_uid_range("/nonexistent/login.defs"), (1000, 60000))
        for text in ("UID_MIN 70000\nUID_MAX 60000\n", "UID_MIN 0\n", "UID_MIN abc\n"):
            with tempfile.NamedTemporaryFile("w", delete=False) as fh:
                fh.write(text)
                path = fh.name
            try:
                with self.subTest(text=text):
                    self.assertEqual(helper.regular_uid_range(path), (1000, 60000))
            finally:
                os.unlink(path)

    def test_this_machine_has_a_sane_range(self):
        lo, hi = helper.regular_uid_range()
        self.assertGreaterEqual(lo, 1)
        self.assertLess(hi, 61184, "DynamicUser range must stay outside")


class Pinning(unittest.TestCase):
    """Every process command opens a pidfd first and reports a target that
    exited mid-change instead of pretending the change landed."""

    def test_pin_refuses_a_missing_pid(self):
        with self.assertRaises(helper.HelperError):
            helper.pin(2**22)

    def test_change_runs_apply_on_a_live_regular_process(self):
        if not regular():
            self.skipTest("test itself runs as a system account")
        child = subprocess.Popen(["sleep", "30"])
        try:
            seen = []
            out = helper.change(child.pid, lambda: seen.append(child.pid) or {"ok": 1})
            self.assertEqual((seen, out), ([child.pid], {"ok": 1}))
        finally:
            child.kill()
            child.wait()

    def test_change_reports_a_target_that_ended_during_the_change(self):
        if not regular():
            self.skipTest("test itself runs as a system account")
        child = subprocess.Popen(["sleep", "30"])

        def apply():
            child.kill()
            child.wait()      # exited and reaped: the pid is free for reuse
            return {"ok": 1}
        with self.assertRaises(helper.HelperError) as ctx:
            helper.change(child.pid, apply)
        self.assertIn("reused", str(ctx.exception))

    def test_change_checks_the_target_before_apply(self):
        original = helper.proc_units
        helper.proc_units = lambda pid: {"systemd-journald.service"}
        try:
            if not regular():
                self.skipTest("test itself runs as a system account")
            with self.assertRaises(helper.HelperError):
                helper.change(os.getpid(), lambda: self.fail("apply must not run"))
        finally:
            helper.proc_units = original

    def test_all_four_process_commands_go_through_the_same_check(self):
        """A process seen as root's: every command must refuse it because of
        who it is, before doing anything."""
        me = str(os.getpid())
        before = os.getpriority(os.PRIO_PROCESS, 0)
        with target_uid(0):
            for name, a in (("nice", args(pid=me, value="19")),
                            ("affinity", args(pid=me, cores="0")),
                            ("ionice", args(pid=me, klass="3", value="0")),
                            ("signal", args(pid=me, signal="CONT"))):
                with self.subTest(name), self.assertRaises(helper.HelperError) as ctx:
                    getattr(helper, f"cmd_proc_{name}")(a)
                self.assertIn("not a regular user", str(ctx.exception))
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, 0), before, "nothing was applied")

    def test_nobody_and_dynamic_users_are_refused_by_every_command(self):
        me = str(os.getpid())
        for uid in (65534, 61184):
            with target_uid(uid), self.subTest(uid=uid), \
                    self.assertRaises(helper.HelperError) as ctx:
                helper.cmd_proc_nice(args(pid=me, value="19"))
            self.assertIn(f"uid {uid}", str(ctx.exception))

    def test_kthreadd_is_refused_where_it_exists(self):
        """The same on a real root process, on a machine that shows one. In a
        build chroot or a fresh pid namespace pid 2 is missing, or is not
        root's; then there is nothing to test here and the fake-uid tests
        above carry the rule."""
        try:
            if helper.proc_uid(2) != 0:
                self.skipTest("pid 2 is not a root process in this pid namespace")
        except helper.HelperError:
            self.skipTest("no pid 2 in this pid namespace")
        with self.assertRaises(helper.HelperError) as ctx:
            helper.cmd_proc_signal(args(pid="2", signal="CONT"))
        self.assertIn("not a regular user", str(ctx.exception))

    def test_nice_affinity_ionice_refuse_a_protected_unit(self):
        original = helper.proc_units
        helper.proc_units = lambda pid: {"sddm.service"}
        try:
            if not regular():
                self.skipTest("test itself runs as a system account")
            me = str(os.getpid())
            before = os.getpriority(os.PRIO_PROCESS, 0)
            for name, a in (("nice", args(pid=me, value="19")),
                            ("affinity", args(pid=me, cores="0")),
                            ("ionice", args(pid=me, klass="3", value="0"))):
                with self.subTest(name), self.assertRaises(helper.HelperError) as ctx:
                    getattr(helper, f"cmd_proc_{name}")(a)
                self.assertIn("protected", str(ctx.exception))
            self.assertEqual(os.getpriority(os.PRIO_PROCESS, 0), before, "nothing was applied")
        finally:
            helper.proc_units = original


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
        # Refused because of *who* it is, not because it is missing: the
        # target exists (it is this test) and is seen as root's.
        with target_uid(0), self.assertRaises(helper.HelperError) as ctx:
            helper.cmd_proc_signal(args(pid=str(os.getpid()), signal="CONT"))
        self.assertIn("not a regular user", str(ctx.exception))

    def test_target_check_accepts_a_regular_user_process(self):
        if not regular():
            self.skipTest("test itself runs as a system account")
        helper.check_target(os.getpid())  # must not raise

    def test_target_check_refuses_protected_cgroup(self):
        original = helper.proc_units
        helper.proc_units = lambda pid: {"sddm.service", "system.slice"}
        try:
            if not regular():
                self.skipTest("test itself runs as a system account")
            with self.assertRaises(helper.HelperError) as ctx:
                helper.check_target(os.getpid())
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
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
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
