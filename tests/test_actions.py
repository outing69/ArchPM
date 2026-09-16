"""Your own session's services: validated on the client side, run as you, never via pkexec.

A root process running `systemctl --user` talks to root's own user manager, so
services must never go through the helper. These tests pin that, plus the guard
that keeps the desktop session itself from being stopped.
"""
from __future__ import annotations

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
                     "pipewire", "pipewire-pulse.service", "pipewire.socket",
                     "wireplumber", "xdg-desktop-portal", "xdg-desktop-portal-kde.service"):
            with self.subTest(unit=unit), self.assertRaises(actions.ActionError) as ctx:
                self.b.service_argv("stop", unit)
            self.assertIn("desktop session", str(ctx.exception))

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

    def test_list_services_parses_plain_output(self):
        out = ("archpm-agent.service loaded active running ArchPM agent\n"
               "plasma-plasmashell.service loaded active running KDE Plasma Workspace\n\n")
        units = self._with_fake(lambda *a, timeout=30: out,
                                lambda: actions.UserBackend().list_services())
        self.assertEqual(units, ["archpm-agent.service", "plasma-plasmashell.service"])

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
