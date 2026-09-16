"""One list of the desktop session's pieces for both guards. The signal guard
reads it by process name, the service guard by unit name; a piece in the
list is known to both, so they cannot drift apart again."""
from __future__ import annotations

import unittest

from archpm import actions, session, signalguard

# key -> (a process name of it, a user unit of it), as seen on Plasma 6
SEEN = {
    "plasmashell": ("plasmashell", "plasma-plasmashell.service"),
    "kwin": ("kwin_wayland", "plasma-kwin_wayland.service"),
    "ksmserver": ("ksmserver", "plasma-ksmserver.service"),
    "dbus": ("dbus-broker", "dbus-broker.service"),
    "pipewire": ("pipewire", "pipewire.service"),
    "wireplumber": ("wireplumber", "wireplumber.service"),
    "xdg-desktop-portal": ("xdg-desktop-portal", "xdg-desktop-portal.service"),
}


class OneList(unittest.TestCase):
    def test_every_piece_is_known_to_both_guards(self):
        self.assertEqual(set(SEEN), set(session.SESSION), "the table above covers the list")
        for key, (proc, unit) in SEEN.items():
            with self.subTest(key=key):
                loss = session.SESSION[key]
                self.assertEqual(session.process_loss(proc), loss)
                self.assertEqual(session.unit_loss(unit), loss)
                self.assertEqual(signalguard.session_loss(proc), loss)
                with self.assertRaises(actions.ActionError) as ctx:
                    actions.UserBackend().service_argv("stop", unit)
                self.assertIn(loss, str(ctx.exception))

    def test_the_guards_have_no_list_of_their_own(self):
        self.assertFalse(hasattr(actions, "SESSION_UNITS"))
        self.assertFalse(hasattr(signalguard, "SESSION_PROCESSES"))


class Units(unittest.TestCase):
    def test_variants_and_suffixes(self):
        for unit in ("plasma-kwin_x11.service", "plasma-kwin_wayland", "pipewire-pulse.service",
                     "pipewire.socket", "xdg-desktop-portal-kde.service", "dbus.service",
                     "dbus-broker.service", "dbus.socket"):
            with self.subTest(unit=unit):
                self.assertTrue(session.unit_loss(unit))

    def test_a_dbus_activated_program_is_not_the_bus(self):
        for unit in ("dbus-:1.2-org.kde.kwalletd6@0.service",
                     "dbus-:1.15-org.a11y.atspi.Registry@0.service"):
            with self.subTest(unit=unit):
                self.assertEqual(session.unit_loss(unit), "")

    def test_lookalikes_do_not_match(self):
        for unit in ("pipewireless.service", "plasma-kwinner.service", "plasma-discover.service",
                     "kwalletd6.service", "xdg-document-portal.service", "archpm-agent.service"):
            with self.subTest(unit=unit):
                self.assertEqual(session.unit_loss(unit), "")


class Processes(unittest.TestCase):
    def test_variants_and_truncation(self):
        for name in ("kwin_wayland", "kwin_x11", "kwin_wayland_wr", "ksmserver", "dbus-daemon",
                     "dbus-broker", "dbus-broker-lau", "xdg-desktop-por", "pipewire-pulse"):
            with self.subTest(name=name):
                self.assertTrue(session.process_loss(name))

    def test_lookalikes_do_not_match(self):
        for name in ("pipewireless", "kwinner", "plasma-discover", "kwalletd6", "xdg-open", ""):
            with self.subTest(name=name):
                self.assertEqual(session.process_loss(name), "")


if __name__ == "__main__":
    unittest.main()
