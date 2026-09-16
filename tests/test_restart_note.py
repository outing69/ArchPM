"""A service with Restart= other than "no" starts its process again after a
kill; the dialog says so, names the unit, and says where to stop the service
instead. Read from systemctl only when the dialog opens, one call per unit."""
from __future__ import annotations

import os
import subprocess
import unittest
from types import SimpleNamespace

from archpm import signalguard
from archpm.model import ProcSample

USER = "/user.slice/user-1000.slice/user@1000.service/app.slice/"
SYSTEM = "/system.slice/"


def proc(pid, name, cgroup, ppid=1):
    return ProcSample(pid=pid, ppid=ppid, name=name, cgroup=cgroup, owned=True, username="alex")


def policy_of(table):
    """A fake systemctl: unit -> (Restart, MainPID), counting the calls."""
    calls = []

    def policy(unit, user):
        calls.append((unit, user))
        return table.get(unit, ("", 0))
    policy.calls = calls
    return policy


class UnitOfProcess(unittest.TestCase):
    def test_user_system_and_none(self):
        self.assertEqual(signalguard.unit_of_process(proc(1, "a", USER + "archpm-agent.service")),
                         ("archpm-agent.service", True))
        self.assertEqual(signalguard.unit_of_process(proc(1, "a", SYSTEM + "sddm.service")),
                         ("sddm.service", False))
        self.assertEqual(signalguard.unit_of_process(proc(1, "a", "")), ("", False))


class Policy(unittest.TestCase):
    def test_parses_systemctl_show_and_addresses_the_right_manager(self):
        seen = []

        def run(argv, **kw):
            seen.append(argv)
            return SimpleNamespace(returncode=0, stdout="always\n892\n")
        self.assertEqual(signalguard.restart_policy("sddm.service", False, run), ("always", 892))
        self.assertEqual(signalguard.restart_policy("x.service", True, run), ("always", 892))
        self.assertNotIn("--user", seen[0])
        self.assertEqual(seen[1][:2], ["systemctl", "--user"])
        for argv in seen:
            self.assertEqual(argv[-2:], ["--", argv[-1]], "-- before the unit name")

    def test_a_scope_a_failure_and_a_timeout_give_nothing(self):
        self.assertEqual(signalguard.restart_policy(
            "a.scope", True, lambda *a, **k: SimpleNamespace(returncode=0, stdout="")), ("", 0))
        self.assertEqual(signalguard.restart_policy(
            "a.service", True, lambda *a, **k: SimpleNamespace(returncode=1, stdout="no\n0\n")),
            ("", 0))

        def slow(*a, **k):
            raise subprocess.TimeoutExpired("systemctl", 2)
        self.assertEqual(signalguard.restart_policy("a.service", True, slow), ("", 0))

    def test_on_this_machine_the_agent_unit_reads_as_systemctl_says(self):
        expected = subprocess.run(
            ["systemctl", "--user", "show", "-p", "Restart", "-p", "MainPID", "--value",
             "archpm-agent.service"], capture_output=True, text=True, check=False)
        if expected.returncode != 0 or len(expected.stdout.splitlines()) < 2:
            self.skipTest("no user systemd here")
        restart, main = expected.stdout.split()
        self.assertEqual(signalguard.restart_policy("archpm-agent.service", True),
                         (restart, int(main)))


class SignalNames(unittest.TestCase):
    def test_the_view_passes_sigterm_and_the_guard_understands_it(self):
        """signal.SIGKILL.name is "SIGKILL"; the guard's rules are keyed "KILL"."""
        p = proc(4242, "game", "")
        v = signalguard.check([p], "SIGKILL", self_pid=1, above=set(), leaders=set())
        self.assertTrue(v.confirm)
        self.assertEqual(v.title, "Force kill game?")
        self.assertIn("no chance to save", v.text)
        v = signalguard.check([p], "SIGTERM", self_pid=1, above=set(), leaders=set(),
                              always_ask=True)
        self.assertEqual(v.title, "Ask game to quit?")
        note = signalguard.restart_note([proc(892, "sddm", SYSTEM + "sddm.service")], "SIGTERM",
                                        policy_of({"sddm.service": ("always", 892)}))
        self.assertIn("sddm.service", note)


class ComesBack(unittest.TestCase):
    def test_always_comes_back_after_both(self):
        for sig in ("TERM", "KILL"):
            self.assertIn("right away", signalguard.comes_back("always", sig))

    def test_no_and_unknown_stay_down(self):
        for restart in ("no", ""):
            for sig in ("TERM", "KILL"):
                self.assertEqual(signalguard.comes_back(restart, sig), "")

    def test_on_failure_is_a_failure_after_a_kill_only(self):
        self.assertIn("counts as a failure", signalguard.comes_back("on-failure", "KILL"))
        self.assertIn("exits with an error", signalguard.comes_back("on-failure", "TERM"))

    def test_on_success_needs_a_clean_exit(self):
        self.assertIn("clean exit", signalguard.comes_back("on-success", "TERM"))
        self.assertEqual(signalguard.comes_back("on-success", "KILL"), "")


class Note(unittest.TestCase):
    def test_names_the_unit_and_points_at_root_tasks_for_a_session_service(self):
        p = proc(8905, "archpm-agent", USER + "archpm-agent.service")
        note = signalguard.restart_note([p], "KILL", policy_of(
            {"archpm-agent.service": ("on-failure", 8905)}))
        self.assertIn("archpm-agent runs as the service archpm-agent.service", note)
        self.assertIn("Restart=on-failure", note)
        self.assertIn("Root tasks → your session's services → archpm-agent.service", note)

    def test_a_system_service_points_at_sudo_and_a_desktop_piece_at_restart(self):
        sddm = proc(892, "sddm", SYSTEM + "sddm.service")
        note = signalguard.restart_note([sddm], "TERM",
                                        policy_of({"sddm.service": ("always", 892)}))
        self.assertIn("sudo systemctl stop sddm.service", note)
        kwin = proc(1200, "kwin_wayland", USER + "plasma-kwin_wayland.service")
        note = signalguard.restart_note([kwin], "TERM", policy_of(
            {"plasma-kwin_wayland.service": ("on-failure", 1200)}))
        self.assertIn("exits with an error", note, "TERM on on-failure: said with the nuance")
        self.assertIn("part of your desktop session", note)
        note = signalguard.restart_note([kwin], "KILL", policy_of(
            {"plasma-kwin_wayland.service": ("on-failure", 1200)}))
        self.assertIn("part of your desktop session", note)
        self.assertIn("restart it", note)

    def test_a_helper_of_the_service_gets_no_note(self):
        helper = proc(9000, "worker", USER + "archpm-agent.service", ppid=8905)
        note = signalguard.restart_note([helper], "KILL", policy_of(
            {"archpm-agent.service": ("always", 8905)}))
        self.assertEqual(note, "")

    def test_restart_no_a_scope_and_other_signals_give_nothing(self):
        app = proc(4558, "brave", USER + "app-brave\\x2dbrowser@1.service")
        self.assertEqual(signalguard.restart_note([app], "KILL", policy_of(
            {"app-brave\\x2dbrowser@1.service": ("no", 4558)})), "")
        scope = proc(4558, "brave", USER + "app-org.chromium.Chromium-4558.scope")
        pol = policy_of({})
        self.assertEqual(signalguard.restart_note([scope], "KILL", pol), "")
        self.assertEqual(pol.calls, [], "a scope has no Restart=; systemctl is not asked")
        svc = proc(892, "sddm", SYSTEM + "sddm.service")
        pol = policy_of({"sddm.service": ("always", 892)})
        for sig in ("STOP", "CONT", "HUP"):
            self.assertEqual(signalguard.restart_note([svc], sig, pol), "")
        self.assertEqual(pol.calls, [], "only TERM and KILL ask")

    def test_one_call_per_unit_however_many_processes(self):
        procs = [proc(892, "sddm", SYSTEM + "sddm.service")] + [
            proc(900 + i, "sddm-helper", SYSTEM + "sddm.service", ppid=892) for i in range(20)]
        pol = policy_of({"sddm.service": ("always", 892)})
        note = signalguard.restart_note(procs, "TERM", pol)
        self.assertEqual(len(pol.calls), 1)
        self.assertEqual(note.count("sddm.service"), 2, "named once in the note, once in the hint")

    def test_it_is_not_read_while_sampling(self):
        """The sampler and the model never import or call the lookup."""
        for module in ("archpm/sampler.py", "archpm/ui/proc_model.py", "archpm/ui/worker.py",
                       "archpm/publisher.py"):
            with open(os.path.join(os.path.dirname(__file__), "..", module)) as fh:
                self.assertNotIn("restart_policy", fh.read(), module)


if __name__ == "__main__":
    unittest.main()
