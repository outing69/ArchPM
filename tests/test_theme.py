"""Colours: every token has a dark and a light value, no hex outside the
theme module, text reads on its surface in both modes, a stylesheet put
through the registry follows a mode change, and the system preference is
read from Qt first, the portal second, dark last."""
from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm.ui import theme

UI = Path(__file__).resolve().parent.parent / "archpm"


def luminance(hexv: str) -> float:
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


class Tokens(unittest.TestCase):
    def test_every_token_has_both_values_and_they_are_hex(self):
        self.assertEqual(set(theme.DARK), set(theme.LIGHT))
        for table in (theme.DARK, theme.LIGHT):
            for name, value in table.items():
                self.assertRegex(value, r"^#[0-9a-f]{6}$", name)

    def test_no_hex_outside_the_theme_module(self):
        offenders = []
        for path in UI.rglob("*.py"):
            if path.name == "theme.py":
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if re.search(r"#[0-9a-fA-F]{6}\b", line):
                    offenders.append(f"{path.relative_to(UI.parent)}:{n}")
        self.assertEqual(offenders, [])

    def test_no_stylesheet_bakes_a_token_outside_the_registry(self):
        offenders = []
        for path in (UI / "ui").glob("*.py"):
            if path.name == "theme.py":
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if "setStyleSheet(f" in line and "theme." in line:
                    offenders.append(f"{path.name}:{n}")
        self.assertEqual(offenders, [], "use theme.style() so a mode change reaches it")

    def test_text_reads_on_the_surface_in_both_modes(self):
        for name, table in (("dark", theme.DARK), ("light", theme.LIGHT)):
            for tok in ("TEXT", "MUTED", "LABEL", "ACCENT", "WARN", "CRIT", "OK"):
                with self.subTest(mode=name, token=tok):
                    self.assertGreaterEqual(contrast(table[tok], table["SURFACE"]), 4.5)
                    self.assertGreaterEqual(contrast(table[tok], table["BG"]), 4.5)
            with self.subTest(mode=name, token="FAINT"):
                self.assertGreaterEqual(contrast(table["FAINT"], table["SURFACE"]), 3.0)
            for tok in ("CPU", "GPU", "MEM", "NET", "DISK", "SWAP"):
                with self.subTest(mode=name, series=tok):
                    self.assertGreaterEqual(contrast(table[tok], table["SURFACE"]), 3.0)
            # a selected row is a highlighted component: 3:1 is the bar for those
            self.assertGreaterEqual(contrast(table["ON_SELECT"], table["SELECT"]), 3.0)
            self.assertGreaterEqual(contrast(table["ON_ACCENT"], table["ACCENT"]), 4.5)

    def test_light_is_a_choice_not_an_inversion(self):
        """An inverted yellow is blue; the light accent is still a warm tone."""
        r, g, b = (int(theme.LIGHT["ACCENT"][i:i + 2], 16) for i in (1, 3, 5))
        self.assertGreater(r, b)
        self.assertGreater(g, b)


class Preference(unittest.TestCase):
    def test_hints_first_then_portal_then_dark(self):
        def app_with(scheme):
            return SimpleNamespace(styleHints=lambda: SimpleNamespace(colorScheme=lambda: scheme))
        self.assertEqual(theme.scheme_from_hints(app_with(Qt.ColorScheme.Dark)), "dark")
        self.assertEqual(theme.scheme_from_hints(app_with(Qt.ColorScheme.Light)), "light")
        self.assertIsNone(theme.scheme_from_hints(app_with(Qt.ColorScheme.Unknown)))
        self.assertIsNone(theme.scheme_from_hints(SimpleNamespace()))
        original = theme.scheme_from_portal
        theme.scheme_from_portal = lambda: None
        try:
            self.assertEqual(theme.system_scheme(app_with(Qt.ColorScheme.Unknown)), "dark")
            theme.scheme_from_portal = lambda: "light"
            self.assertEqual(theme.system_scheme(app_with(Qt.ColorScheme.Unknown)), "light")
            self.assertEqual(theme.system_scheme(app_with(Qt.ColorScheme.Dark)), "dark",
                             "Qt's answer wins over the portal")
        finally:
            theme.scheme_from_portal = original


@unittest.skipUnless(QApplication, "PySide6 not installed")
class LiveSwitch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        theme.set_mode(self.app, "dark")

    def test_registered_stylesheet_and_module_names_follow_the_mode(self):
        label = QLabel()
        theme.style(label, "color: {MUTED}; border: 1px solid {BORDER};")
        seen = []
        theme.signals.changed.connect(seen.append)
        theme.set_mode(self.app, "light")
        self.assertEqual(label.styleSheet(), "color: {MUTED}; border: 1px solid {BORDER};"
                         .format(**theme.LIGHT))
        self.assertEqual(theme.MUTED, theme.LIGHT["MUTED"])
        self.assertEqual(theme.resolve("CPU"), theme.LIGHT["CPU"])
        self.assertEqual(theme.resolve("#123456"), "#123456")
        self.assertEqual(seen, ["light"])
        self.assertEqual(self.app.palette().color(self.app.palette().ColorRole.Window).name(),
                         theme.LIGHT["BG"])

    def test_preference_is_stored_and_applied(self):
        store = {}
        settings = SimpleNamespace(setValue=store.__setitem__,
                                   value=lambda k, d, type=str: store.get(k, d))
        theme.set_preference(self.app, "light", settings)
        self.assertEqual((store[theme.SETTINGS_KEY], theme.mode()), ("light", "light"))
        theme.set_preference(self.app, "dark", settings)
        self.assertEqual(theme.mode(), "dark")
        with self.assertRaises(ValueError):
            theme.set_preference(self.app, "sepia", settings)


if __name__ == "__main__":
    unittest.main()
