"""Failed services: two systemctl calls, details and logs only for what
failed, the system journal probed only when a system unit failed and its
rows saying so when it is not readable. Read-only throughout."""
from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace

from archpm import failed

SYS_LIST = ("● foo.service loaded failed failed Foo Daemon\n"
            "bar.service loaded failed failed bar.service\n")
USER_LIST = "archpm-agent.service loaded failed failed ArchPM sampler (feeds the widget)\n"
SYS_SHOW = ("Id=foo.service\nDescription=Foo Daemon\nStateChangeTimestamp=Wed 2026-09-16 "
            "17:28:03 CEST\n\nId=bar.service\nDescription=\nStateChangeTimestamp=Wed "
            "2026-09-16 18:00:00 CEST\n")
USER_SHOW = ("Id=archpm-agent.service\nDescription=ArchPM sampler (feeds the widget)\n"
             "StateChangeTimestamp=Wed 2026-09-16 19:00:00 CEST\n")


def fake_run(journal_ok=True):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        out, err, code = "", "", 0
        if argv[0] == "systemctl":
            user = "--user" in argv
            if "--failed" in argv:
                out = USER_LIST if user else SYS_LIST
            elif "show" in argv:
                out = USER_SHOW if user else SYS_SHOW
        elif argv[0] == "journalctl":
            if "--system" in argv:
                if not journal_ok:
                    err, code = "No journal files were opened due to insufficient permissions.", 1
            else:
                unit = argv[argv.index("-u") + 1]
                out = f"sep 16 17:28:03 host {unit}: line one\nsep 16 17:28:03 host {unit}: two\n"
        return SimpleNamespace(returncode=code, stdout=out, stderr=err)
    run.calls = calls
    return run


class Parsing(unittest.TestCase):
    def test_list_with_and_without_the_marker(self):
        self.assertEqual(failed.parse_list(SYS_LIST),
                         [("foo.service", "Foo Daemon"), ("bar.service", "")])
        self.assertEqual(failed.parse_list(""), [])

    def test_show_blocks(self):
        blocks = failed.parse_show(SYS_SHOW)
        self.assertEqual(set(blocks), {"foo.service", "bar.service"})
        self.assertEqual(blocks["foo.service"]["StateChangeTimestamp"],
                         "Wed 2026-09-16 17:28:03 CEST")


class Check(unittest.TestCase):
    def test_rows_scope_since_and_log(self):
        run = fake_run()
        report = failed.check(run)
        self.assertEqual([(u.unit, u.scope) for u in report.units],
                         [("foo.service", "system"), ("bar.service", "system"),
                          ("archpm-agent.service", "session")])
        foo, bar, agent = report.units
        self.assertEqual(foo.title, "Foo Daemon")
        self.assertEqual(bar.title, "bar.service", "no description: the unit name stands")
        self.assertEqual(foo.since, "Wed 2026-09-16 17:28:03 CEST")
        self.assertEqual(len(foo.log), 2)
        self.assertTrue(report.journal_readable)
        self.assertGreater(report.took_ms, 0)
        user_log = [a for a in run.calls if a[0] == "journalctl" and "--user" in a]
        self.assertEqual(len(user_log), 1, "a session unit's log comes from journalctl --user")
        self.assertIn("archpm-agent.service", user_log[0])

    def test_unreadable_system_journal_is_said_in_the_row_and_not_read(self):
        run = fake_run(journal_ok=False)
        report = failed.check(run)
        self.assertFalse(report.journal_readable)
        foo, bar, agent = report.units
        self.assertEqual(foo.log, [])
        self.assertIn("not readable for this user", foo.note)
        self.assertEqual(len(agent.log), 2, "the user's own journal is still read")
        sys_logs = [a for a in run.calls
                    if a[0] == "journalctl" and "-u" in a and "--user" not in a]
        self.assertEqual(sys_logs, [], "no pointless read of a journal we cannot see")

    def test_nothing_failed_means_two_calls_and_no_journal(self):
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        report = failed.check(run)
        self.assertEqual(report.units, [])
        self.assertEqual([a[:2] for a in calls], [["systemctl", "--failed"],
                                                  ["systemctl", "--user"]])
        self.assertTrue(report.journal_readable, "not probed, nothing to read")

    def test_a_missing_systemctl_is_reported_not_raised(self):
        def run(*a, **k):
            raise FileNotFoundError("systemctl")
        report = failed.check(run)
        self.assertEqual(report.units, [])
        self.assertIn("could not be asked", report.error)

    def test_read_only_argv(self):
        run = fake_run()
        failed.check(run)
        for argv in run.calls:
            for verb in ("start", "stop", "restart", "reset-failed", "kill", "enable", "disable"):
                self.assertNotIn(verb, argv, argv)
            self.assertNotIn("pkexec", argv)

    def test_on_this_machine(self):
        try:
            subprocess.run(["systemctl", "--version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("no systemctl")
        report = failed.check()
        self.assertEqual(report.error, "")
        for u in report.units:
            self.assertIn(u.scope, ("system", "session"))
            self.assertTrue(u.log or u.note)


if __name__ == "__main__":
    unittest.main()
