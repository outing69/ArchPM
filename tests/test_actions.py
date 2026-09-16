"""Your own session's services: validated on the client side, run as you, never via pkexec.

A root process running `systemctl --user` talks to root's own user manager, so
services must never go through the helper. These tests pin that, plus the guard
that keeps the desktop session itself from being stopped.
"""
from __future__ import annotations

import subprocess
import unittest

from archpm import actions


class ServiceArgv(unittest.TestCase):
    def setUp(self):
        self.b = actions.UserBackend()

    def test_builds_systemctl_user_and_appends_service_suffix(self):
        argv = self.b.service_argv("restart", "archpm-agent")
        self.assertEqual(argv, ["systemctl", "--user", "restart", "--", "archpm-agent.service"])
        self.assertNotIn("pkexec", argv)

    def test_accepts_the_escaped_names_plasma_gives_launched_apps(self):
        unit = "app-brave\\x2dbrowser@008aa35f90454f87a16c295e41f27147.service"
        self.assertEqual(self.b.service_argv("stop", unit)[-1], unit)

    def test_double_dash_sits_right_before_the_unit_in_every_argv(self):
        # A unit name is the last argument and "--" is always the one before it,
        # so a name that looks like an option can never be read as one.
        for action in actions.SERVICE_ACTIONS:
            argv = self.b.service_argv(action, "archpm-agent")
            self.assertEqual(argv[-2:], ["--", "archpm-agent.service"], action)
        seen = []
        original, actions.systemctl_user = actions.systemctl_user, \
            lambda *a, timeout=30: seen.append(a) or "active"
        try:
            self.b.service("restart", "archpm-agent")
        finally:
            actions.systemctl_user = original
        self.assertEqual(len(seen), 2)
        for args in seen:
            self.assertEqual(args[-2:], ("--", "archpm-agent.service"), args)

    def test_keeps_an_explicit_suffix(self):
        self.assertEqual(self.b.service_argv("start", "pipewire.socket")[-1], "pipewire.socket")

    def test_refuses_to_stop_the_desktop_session_itself(self):
        for unit in ("plasma-plasmashell", "plasma-plasmashell.service",
                     "plasma-kwin_wayland.service", "plasma-kwin_x11", "plasma-ksmserver.service",
                     "dbus-broker.service", "dbus.service",
                     "pipewire", "pipewire-pulse.service", "pipewire.socket",
                     "wireplumber", "xdg-desktop-portal", "xdg-desktop-portal-kde.service"):
            with self.subTest(unit=unit), self.assertRaises(actions.ActionError) as ctx:
                self.b.service_argv("stop", unit)
            self.assertIn("desktop session", str(ctx.exception))

    def test_a_dbus_activated_program_may_be_stopped(self):
        unit = "dbus-:1.2-org.kde.kwalletd6@0.service"
        self.assertEqual(self.b.service_argv("stop", unit)[-1], unit)

    def test_restart_of_the_desktop_session_is_allowed(self):
        argv = self.b.service_argv("restart", "plasma-plasmashell")
        self.assertEqual(argv[-1], "plasma-plasmashell.service")

    def test_similar_names_are_not_caught_by_accident(self):
        self.assertEqual(self.b.service_argv("stop", "pipewireless")[-1], "pipewireless.service")

    def test_rejects_bad_unit_names(self):
        for unit in ("", "   ", "../etc", "a b", "unit;reboot", "$(id)", "-flag.service",
                     "--no-block.service", "default.target", "x" * 200 + ".service"):
            with self.subTest(unit=unit), self.assertRaises(actions.ActionError):
                self.b.service_argv("restart", unit)

    def test_rejects_every_other_systemctl_verb(self):
        for action in ("enable", "disable", "mask", "kill", "isolate", "daemon-reload", ""):
            with self.subTest(action=action), self.assertRaises(actions.ActionError):
                self.b.service_argv(action, "archpm-agent")


class ServiceRun(unittest.TestCase):
    def _with_fake(self, fake, fn):
        original, actions.systemctl_user = actions.systemctl_user, fake
        try:
            return fn()
        finally:
            actions.systemctl_user = original

    def test_runs_the_action_then_reports_the_state(self):
        calls = []

        def fake(*args, timeout=30):
            calls.append(args)
            return "active" if args[0] == "show" else ""
        state = self._with_fake(
            fake, lambda: actions.UserBackend().service("restart", "archpm-agent"))
        self.assertEqual(state, "active")
        self.assertEqual(calls[0], ("restart", "--", "archpm-agent.service"))
        self.assertEqual(calls[1][:1], ("show",))
        self.assertEqual(calls[1][-1], "archpm-agent.service")

    def test_guard_fires_before_systemctl_is_called(self):
        calls = []
        with self.assertRaises(actions.ActionError):
            self._with_fake(lambda *a, timeout=30: calls.append(a),
                            lambda: actions.UserBackend().service("stop", "wireplumber"))
        self.assertEqual(calls, [])

    def test_list_services_parses_plain_output_with_descriptions(self):
        out = ("archpm-agent.service loaded active running ArchPM agent\n"
               "app-brave\\x2dbrowser@89185f01fb3e42e38b610935c88efd87.service loaded active "
               "running Brave - Web Browser\n"
               "dbus-:1.2-org.kde.kwalletd6@0.service loaded active running "
               "dbus-:1.2-org.kde.kwalletd6@0.service\n\n")
        units = self._with_fake(lambda *a, timeout=30: out,
                                lambda: actions.UserBackend().list_services())
        self.assertEqual(units, [
            actions.Service("archpm-agent.service", "ArchPM agent"),
            actions.Service("app-brave\\x2dbrowser@89185f01fb3e42e38b610935c88efd87.service",
                            "Brave - Web Browser"),
            actions.Service("dbus-:1.2-org.kde.kwalletd6@0.service", ""),
        ], "a description equal to the unit name is no description")

    def test_enabled_services_come_from_unit_files_with_state_from_list_units(self):
        files = ("archpm-agent.service  enabled enabled\n"
                 "wireplumber.service   enabled enabled\n"
                 "ydotool.service       enabled enabled\n"
                 "foo.service           disabled enabled\n")
        units = ("archpm-agent.service loaded active   running ArchPM sampler (feeds the widget)\n"
                 "wireplumber.service  loaded active   running Multimedia Service Session Manager\n"
                 "ydotool.service      loaded inactive dead    ydotool.service\n")
        got = actions.parse_enabled_services(files, units)
        self.assertEqual(got, [
            actions.EnabledService("archpm-agent.service",
                                   "ArchPM sampler (feeds the widget)", True),
            actions.EnabledService("wireplumber.service",
                                   "Multimedia Service Session Manager", True),
            actions.EnabledService("ydotool.service", "", False),
        ], "sorted by description, a description equal to the name dropped, disabled left out")

    def test_enabled_services_on_this_machine_match_systemctl(self):
        try:
            got = actions.UserBackend().enabled_services()
        except actions.ActionError as exc:
            self.skipTest(f"no user systemd here: {exc}")
        expected = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "--type=service", "--state=enabled",
             "--no-legend", "--plain"], capture_output=True, text=True, check=False).stdout
        names = sorted(line.split()[0] for line in expected.splitlines() if line.split())
        self.assertEqual(sorted(e.unit for e in got), names)

    def test_service_label_is_what_a_person_recognises(self):
        unit = "app-brave\\x2dbrowser@89185f01fb3e42e38b610935c88efd87.service"
        self.assertEqual(actions.Service(unit, "Brave - Web Browser").label,
                         f"Brave - Web Browser  ({unit})")
        self.assertEqual(actions.Service(unit).label, unit)


class GroupRows(unittest.TestCase):
    def test_a_negative_pid_is_refused_as_not_a_process(self):
        """A group row carries a negative pid. psutil raises ValueError for
        it, which is not an ActionError and used to escape the view unseen."""
        backend = actions.UserBackend()
        for pid in (-18, 0):
            with self.subTest(pid=pid), self.assertRaises(actions.ActionError) as ctx:
                backend.set_nice(pid, 0)
            self.assertIn("not a process", str(ctx.exception))

    def test_elevated_backend_retries_only_a_permission_refusal_as_root(self):
        """A refusal meant as final (ArchPM itself, a process that is gone, bad
        input) must not come back as a root action."""
        import os

        from archpm.root.client import ElevatedBackend

        class Client:
            calls: list = []

            def call(self, *a):
                self.calls.append(a)
                return {}
        client = Client()
        backend = ElevatedBackend(client)
        # ArchPM's own pid: the user backend refuses it for what it is, not for privileges.
        with self.assertRaises(actions.ActionError) as ctx:
            backend.send_signal(os.getpid(), __import__("signal").SIGTERM)
        self.assertNotIsInstance(ctx.exception, actions.PermissionDenied)
        with self.assertRaises(actions.ActionError):
            backend.set_affinity(os.getpid(), [])
        with self.assertRaises(actions.ActionError):
            backend.set_nice(2**22, 5)      # no such process
        self.assertEqual(client.calls, [], "none of these may reach the helper")
        # And only PermissionDenied does.
        backend._fallback(lambda: (_ for _ in ()).throw(actions.PermissionDenied("no")),
                          "proc-nice", "1234", "-5")
        self.assertEqual(client.calls, [("proc-nice", "1234", "-5")])

    def test_elevated_backend_never_routes_services_through_the_helper(self):
        from archpm.root.client import ElevatedBackend, RootClient
        argv = ElevatedBackend(RootClient()).service_argv("stop", "archpm-agent")
        self.assertEqual(argv[:2], ["systemctl", "--user"])
        self.assertNotIn("pkexec", argv)


if __name__ == "__main__":
    unittest.main()
