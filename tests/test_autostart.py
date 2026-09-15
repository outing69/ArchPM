"""Tests for archpm.autostart on a fixture tree: precedence, desktop filtering,
and that disabling/enabling only ever writes inside the user's directory."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from archpm import autostart

KDECONNECT = """\
[Desktop Entry]
Name=KDE Connect
Exec=/usr/bin/kdeconnectd
Icon=kdeconnect
Type=Application
X-KDE-autostart-phase=2
"""
GNOME_ONLY = """\
[Desktop Entry]
Name=Secret Storage Service
Exec=/usr/bin/gnome-keyring-daemon --start --components=secrets
OnlyShowIn=GNOME;Unity;MATE;Cinnamon;
Type=Application
"""
NOT_KDE = """\
[Desktop Entry]
Name=Something not for KDE
Exec=nokde
NotShowIn=KDE;
Type=Application
"""
USER_APP = """\
[Desktop Entry]
Type=Application
Name=Octopi Notifier
Exec=/usr/bin/octopi-notifier
Icon=octopi
Categories=System;
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class Reading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.user = root / "user" / "autostart"
        self.sys = root / "etc" / "xdg" / "autostart"
        write(self.sys / "org.kde.kdeconnect.daemon.desktop", KDECONNECT)
        write(self.sys / "gnome-keyring-secrets.desktop", GNOME_ONLY)
        write(self.sys / "nokde.desktop", NOT_KDE)
        write(self.user / "octopi-notifier.desktop", USER_APP)
        self.a = autostart.Autostart(self.user, [self.sys], desktops={"KDE"})

    def tearDown(self):
        self.tmp.cleanup()

    def by_id(self):
        return {e.id: e for e in self.a.entries()}

    def test_lists_user_and_system_entries(self):
        e = self.by_id()
        self.assertEqual(set(e), {"org.kde.kdeconnect.daemon.desktop",
                                  "gnome-keyring-secrets.desktop",
                                  "nokde.desktop", "octopi-notifier.desktop"})
        self.assertEqual(e["octopi-notifier.desktop"].source, "User")
        self.assertEqual(e["org.kde.kdeconnect.daemon.desktop"].source, "System")
        self.assertEqual(e["octopi-notifier.desktop"].category, "System")

    def test_desktop_filters(self):
        e = self.by_id()
        self.assertTrue(e["org.kde.kdeconnect.daemon.desktop"].for_this_desktop)
        self.assertFalse(e["gnome-keyring-secrets.desktop"].for_this_desktop)
        self.assertFalse(e["nokde.desktop"].for_this_desktop)

    def test_kind_and_description(self):
        e = self.by_id()
        self.assertEqual(e["octopi-notifier.desktop"].kind, "App")
        self.assertEqual(e["octopi-notifier.desktop"].description,
                         "Octopi: tells you when package updates are available.")
        # kdeconnect: system-installed, no OnlyShowIn, not a desktop part
        self.assertEqual(e["org.kde.kdeconnect.daemon.desktop"].kind, "System")
        self.assertIn("KDE Connect", e["org.kde.kdeconnect.daemon.desktop"].description)
        # gnome-keyring is a desktop part by executable and by OnlyShowIn
        self.assertEqual(e["gnome-keyring-secrets.desktop"].kind, "Desktop")
        self.assertTrue(e["gnome-keyring-secrets.desktop"].essential)

    def test_comment_beats_curated_description(self):
        write(self.sys / "powerdevil.desktop", "[Desktop Entry]\nName=Power Management\n"
              "Exec=/usr/lib/org_kde_powerdevil\nComment=Battery, Display and CPU power\n"
              "OnlyShowIn=KDE;\nType=Application\n")
        e = self.by_id()["powerdevil.desktop"]
        self.assertEqual(e.description, "Battery, Display and CPU power")
        self.assertEqual(e.kind, "Desktop")

    def test_all_enabled_initially(self):
        self.assertTrue(all(e.enabled for e in self.a.entries()))

    def test_disable_system_entry_writes_override_only_in_user_dir(self):
        e = self.by_id()["org.kde.kdeconnect.daemon.desktop"]
        self.a.set_enabled(e, False)
        override = self.user / e.id
        self.assertTrue(override.is_file())
        text = override.read_text()
        self.assertIn("Hidden=true", text)
        self.assertIn(f"{autostart.OVERRIDE_MARK}=true", text)
        self.assertEqual((self.sys / e.id).read_text(), KDECONNECT, "system file untouched")
        e2 = self.by_id()[e.id]
        self.assertFalse(e2.enabled)
        self.assertEqual(e2.name, "KDE Connect", "name still known through the override")
        self.assertTrue(e2.is_override)

    def test_enable_removes_our_override_but_not_a_real_user_file(self):
        e = self.by_id()["org.kde.kdeconnect.daemon.desktop"]
        self.a.set_enabled(e, False)
        e = self.by_id()[e.id]
        self.a.set_enabled(e, True)
        self.assertFalse((self.user / e.id).exists(), "override removed, system entry rules again")
        self.assertTrue(self.by_id()[e.id].enabled)

    def test_user_entry_toggles_in_place_and_keeps_other_lines(self):
        e = self.by_id()["octopi-notifier.desktop"]
        self.a.set_enabled(e, False)
        text = (self.user / e.id).read_text()
        self.assertIn("Hidden=true", text)
        self.assertIn("Categories=System;", text)
        self.assertFalse(self.by_id()[e.id].enabled)
        self.a.set_enabled(self.by_id()[e.id], True)
        text = (self.user / e.id).read_text()
        self.assertIn("Hidden=false", text)
        self.assertEqual(text.count("Hidden="), 1)
        self.assertTrue(self.by_id()[e.id].enabled)

    def test_hidden_line_is_only_touched_inside_the_main_group(self):
        write(self.user / "two-groups.desktop",
              "[Desktop Entry]\nType=Application\nName=X\nExec=x\n\n"
              "[Desktop Action a]\nName=A\nExec=x --a\n")
        e = self.by_id()["two-groups.desktop"]
        self.a.set_enabled(e, False)
        text = (self.user / "two-groups.desktop").read_text()
        self.assertEqual(text.index("Hidden=true") < text.index("[Desktop Action a]"), True)
        self.assertEqual(text.count("Hidden="), 1)


class Running(unittest.TestCase):
    def test_matches_exec_prefix_against_process_argv(self):
        a = autostart.Autostart(Path("/nonexistent"), [], desktops=set())
        kde = autostart.StartupEntry("k.desktop", "KDE Connect", "", "/usr/bin/kdeconnectd",
                                     Path("/x"), None, None, True, True,
                                     tokens=autostart.exec_tokens("/usr/bin/kdeconnectd"))
        arch = autostart.StartupEntry("a.desktop", "ArchPM", "", "/usr/bin/python3 -m archpm",
                                      Path("/x"), None, None, True, True,
                                      tokens=autostart.exec_tokens("/usr/bin/python3 -m archpm"))
        argvs = {10: ["/usr/bin/kdeconnectd"], 11: ["python3", "-m", "http.server"],
                 12: ["/usr/bin/python3", "-m", "archpm"], 13: []}
        self.assertEqual(autostart.running_pids([kde, arch], argvs),
                         {"k.desktop": 10, "a.desktop": 12})
        spaced = autostart.StartupEntry("s.desktop", "Spaced", "", '"/opt/My App/app" --x',
                                        Path("/x"), None, None, True, True,
                                        tokens=autostart.exec_tokens('"/opt/My App/app" --x'))
        self.assertEqual(autostart.running_pids([spaced], {20: ["/opt/My App/app", "--x"]}),
                         {"s.desktop": 20}, "a path with a space must match as one argument")
        del a


if __name__ == "__main__":
    unittest.main()


class TildeTest(unittest.TestCase):
    def test_home_is_shortened(self):
        home = Path(os.path.expanduser("~"))
        self.assertEqual(autostart.tilde(home / ".config" / "autostart"), "~/.config/autostart")
        self.assertEqual(autostart.tilde(home), "~")

    def test_outside_home_is_unchanged(self):
        self.assertEqual(autostart.tilde(Path("/etc/xdg/autostart")), "/etc/xdg/autostart")

