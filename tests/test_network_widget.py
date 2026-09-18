"""The Network widget's compact form, read as text: what a panel gets. No
Plasma here, so the QML is not run; the checks are on what it declares:
both representations, a compact form that shows two rates and nothing
else, the width reserved for the widest number, the theme's colours, and
no settings left that the strip no longer reads."""
from __future__ import annotations

import unittest
from pathlib import Path

WIDGET = Path(__file__).resolve().parent.parent / "plasmoid" / "network"
MAIN = WIDGET / "contents" / "ui" / "main.qml"


def block(text: str, head: str) -> str:
    """The braces block that `head` opens, e.g. "compactRepresentation:"."""
    start = text.index(head)
    depth, i = 0, text.index("{", start)
    for j in range(i, len(text)):
        depth += {"{": 1, "}": -1}.get(text[j], 0)
        if depth == 0:
            return text[start:j + 1]
    raise AssertionError("unbalanced")


class CompactForm(unittest.TestCase):
    def setUp(self):
        self.qml = MAIN.read_text()
        self.compact = block(self.qml, "compactRepresentation:")
        self.full = block(self.qml, "fullRepresentation:")

    def test_both_representations_and_the_panel_gets_the_compact_one(self):
        self.assertIn("fullRepresentation:", self.qml)
        self.assertIn("compactRepresentation:", self.qml)
        self.assertIn("preferredRepresentation: inPanel ? compactRepresentation : "
                      "fullRepresentation", self.qml)
        self.assertIn("PlasmaCore.Types.Vertical", self.qml)

    def test_the_strip_is_two_rates_and_nothing_else(self):
        self.assertEqual(self.compact.count("Rate {"), 2)
        for word in ("VPN", "talkers", "doors", "Rectangle", "configuration", "ifaces"):
            self.assertNotIn(word, self.compact, word)
        self.assertIn('arrow: "↓"', self.compact)
        self.assertIn('arrow: "↑"', self.compact)
        self.assertIn("root.expanded = !root.expanded", self.compact)

    def test_the_width_is_reserved_for_the_widest_number(self):
        self.assertIn('text: "↓ 1023.9 MB/s"', self.compact)       # fmtBytes' widest
        self.assertIn('text: "↓999M"', self.compact)               # shortRate's widest
        self.assertIn("Layout.preferredWidth: vertical ? 0 : stripWidth", self.compact)
        self.assertNotIn("implicitWidth", self.compact)             # never per update
        self.assertIn("columns: compact.vertical ? 1 : 2", self.compact)

    def test_the_colours_are_the_themes(self):
        self.assertNotRegex(self.compact, r"#[0-9a-fA-F]{6}")
        self.assertNotIn("root.downColor", self.compact)
        self.assertNotIn("root.upColor", self.compact)
        self.assertIn("Kirigami.Theme.textColor", self.compact)

    def test_the_full_form_and_the_settings_page(self):
        # the full form keeps its own colours and sections, untouched
        for word in ("INTERFACES", "OPEN DOORS", "root.downColor", "Open ArchPM"):
            self.assertIn(word, self.full, word)
        # the strip reads no setting, so the widget ships none
        self.assertFalse((WIDGET / "contents" / "config").exists())
        self.assertFalse((WIDGET / "contents" / "ui" / "configGeneral.qml").exists())
        self.assertNotIn("Plasmoid.configuration", self.qml)

    def test_short_rate_widest_case(self):
        """shortRate as written: the next unit from 1000, so the number has
        at most three digits, and a decimal only under 10: "999K" at most."""
        fn = block(self.qml, "function shortRate")
        self.assertIn("n < 10 ? n.toFixed(1) : n.toFixed(0)", fn)
        self.assertIn('["B", "K", "M", "G", "T"]', fn)
        self.assertRegex(fn, r"while \(n >= 1000")


if __name__ == "__main__":
    unittest.main()
