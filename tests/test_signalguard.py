"""The guard that sits in front of every signal the GUI sends.

No Qt: the rules and the dialog text are checked here directly.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from archpm import signalguard
from archpm.model import ProcSample


def proc(pid, name, owned=True, username="alex", cmdline="", app_name=""):
    return ProcSample(pid=pid, ppid=1, name=name, username=username, owned=owned,
                      cmdline=cmdline or f"/usr/bin/{name}", app_name=app_name)


def verdict(procs, sig="TERM", **kw):
    kw.setdefault("self_pid", 4242)
    kw.setdefault("above", {4242, 4200, 4100})
    kw.setdefault("leaders", {1023})
    return signalguard.check(procs, sig, **kw)


class SessionNames(unittest.TestCase):
    def test_desktop_pieces_and_their_variants_match(self):
        for name in ("plasmashell", "kwin_wayland", "kwin_x11", "kwin_wayland_wr", "ksmserver",
                     "dbus-broker", "dbus-daemon", "pipewire",
                     "pipewire-pulse", "wireplumber", "xdg-desktop-portal",
                     "xdg-desktop-portal-kde", "xdg-desktop-por"):
            with self.subTest(name=name):
                self.assertTrue(signalguard.session_loss(name))

    def test_lookalikes_do_not_match(self):
        for name in ("pipewireless", "kwinner", "plasma-discover", "firefox", "xdg-open", ""):
            with self.subTest(name=name):
                self.assertEqual(signalguard.session_loss(name), "")

    def test_each_loss_is_named_plainly(self):
        self.assertIn("sound", signalguard.session_loss("pipewire"))
        self.assertIn("panel", signalguard.session_loss("plasmashell"))
        self.assertIn("window borders", signalguard.session_loss("kwin_wayland"))


class Lookups(unittest.TestCase):
    def test_ancestors_include_self_and_parent_but_not_pid_1(self):
        above = signalguard.ancestors()
        self.assertIn(os.getpid(), above)
        self.assertIn(os.getppid(), above)
        self.assertNotIn(1, above)

    def test_session_leaders_come_from_logind_files_of_this_uid_only(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "2").write_text("UID=1000\nACTIVE=1\nTYPE=wayland\nLEADER=1023\n")
            Path(d, "3").write_text("UID=1000\nCLASS=manager\nLEADER=1029\n")
            Path(d, "7").write_text("UID=1001\nTYPE=tty\nLEADER=5555\n")
            Path(d, "junk").write_text("not a session file")
            self.assertEqual(signalguard.session_leaders(1000, Path(d)), {1023, 1029})
            self.assertEqual(signalguard.session_leaders(1001, Path(d)), {5555})

    def test_session_leaders_survive_a_missing_directory(self):
        self.assertEqual(signalguard.session_leaders(1000, Path("/nonexistent")), set())


class Refusals(unittest.TestCase):
    def test_archpm_itself_is_refused(self):
        v = verdict([proc(4242, "python")])
        self.assertIn("ArchPM itself", v.refused)

    def test_an_ancestor_of_archpm_is_refused(self):
        v = verdict([proc(4100, "konsole")])
        self.assertIn("started ArchPM", v.refused)

    def test_a_tree_containing_archpm_is_refused(self):
        v = verdict([proc(4100, "konsole"), proc(4242, "python")], tree=True)
        self.assertTrue(v.refused)

    def test_a_tree_containing_the_session_leader_is_refused(self):
        v = verdict([proc(9000, "steam"), proc(1023, "startplasma-way")], tree=True)
        self.assertIn("login session", v.refused)

    def test_a_refusal_wins_over_a_confirmation(self):
        v = verdict([proc(4100, "konsole", owned=False, username="root")], "KILL")
        self.assertTrue(v.refused)
        self.assertFalse(v.confirm)

    def test_an_ordinary_own_process_is_not_refused_and_terminate_still_asks(self):
        # since 0.2.32: Terminate asks for a single process as for a group,
        # and every irreversible action says the one sentence
        from archpm.helptext import CANNOT_UNDO
        v = verdict([proc(9000, "firefox")])
        self.assertEqual(v.refused, "")
        self.assertTrue(v.confirm)
        self.assertTrue(v.text.endswith(CANNOT_UNDO))
        self.assertTrue(verdict([proc(9000, "firefox")], "KILL").text.endswith(CANNOT_UNDO))
        self.assertFalse(verdict([proc(9000, "firefox")], "CONT").confirm)


class Confirmations(unittest.TestCase):
    def test_force_kill_always_asks(self):
        self.assertTrue(verdict([proc(9000, "firefox")], "KILL").confirm)

    def test_a_process_of_another_user_asks_and_says_so(self):
        v = verdict([proc(9000, "sshd", owned=False, username="root")])
        self.assertTrue(v.confirm)
        self.assertIn("Runs as: root (not you)", v.text)
        self.assertIn("another account", v.text)

    def test_a_desktop_process_asks_and_names_the_loss(self):
        v = verdict([proc(1307, "plasmashell")])
        self.assertTrue(v.confirm)
        self.assertIn("plasmashell is part of your desktop session", v.text)
        self.assertIn("the panel, the desktop and its widgets", v.text)

    def test_pause_on_a_desktop_process_says_pausing(self):
        v = verdict([proc(1167, "kwin_wayland")], "STOP")
        self.assertIn("Pausing it takes", v.text)
        self.assertEqual(v.button, "Pause")

    def test_resume_never_asks(self):
        v = verdict([proc(1307, "plasmashell", owned=False, username="root")], "CONT")
        self.assertFalse(v.confirm)

    def test_dialog_shows_name_owner_and_command_line(self):
        v = verdict([proc(9000, "firefox", app_name="Firefox",
                          cmdline="/usr/lib/firefox/firefox --new-window")], "KILL")
        self.assertEqual(v.title, "Force kill Firefox?")
        self.assertEqual(v.button, "Force kill")
        self.assertIn("Program: Firefox (firefox), process 9000", v.text)
        self.assertIn("Runs as: alex (you)", v.text)
        self.assertIn("Command: /usr/lib/firefox/firefox --new-window", v.text)
        self.assertIn("Unsaved work is lost.", v.text)

    def test_many_processes_are_summarised_not_dumped(self):
        procs = [proc(9000 + i, f"worker{i}") for i in range(10)]
        v = verdict(procs, "KILL")
        self.assertEqual(v.title, "Force kill 10 processes?")
        self.assertIn("and 4 more.", v.text)
        self.assertNotIn("worker9", v.text)

    def test_list_all_names_every_process_for_a_group(self):
        procs = [proc(9000 + i, f"worker{i}") for i in range(12)]
        procs[0].app_name = "Brave"
        v = verdict(procs, "TERM", tree=True, always_ask=True, list_all=True)
        self.assertEqual(v.title, "Ask Brave and 11 more to quit?")
        for p in procs:
            self.assertIn(f"{p.display_name} ({p.pid})", v.text)
        self.assertNotIn("more.", v.text)

    def test_a_long_command_line_is_cut(self):
        v = verdict([proc(9000, "game", cmdline="/opt/game/bin " + "x" * 300)], "KILL")
        self.assertLess(max(len(line) for line in v.text.splitlines()), 140)

    def test_no_em_dash_or_shouting_in_any_text(self):
        cases = [
            verdict([proc(9000, "firefox")], "KILL"),
            verdict([proc(9000, "sshd", owned=False, username="root")], "STOP"),
            verdict([proc(1307, "plasmashell")]),
            verdict([proc(4100, "konsole")]),
            verdict([proc(1023, "startplasma-way")], tree=True),
        ]
        for v in cases:
            for text in (v.refused, v.title, v.text, v.button):
                self.assertNotIn("\u2014", text)
                self.assertNotRegex(text, r"\b[A-Z]{4,}\b", text)


if __name__ == "__main__":
    unittest.main()
