"""The Monitor widget's compact form, read as text: three meters with a
theme icon, a bar and a number, the widths reserved, the colours the
theme's, and the points where a bar turns negative the same numbers the
application uses. No Plasma here; the QML is not run."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from archpm import verdict

MAIN = (Path(__file__).resolve().parent.parent / "plasmoid" / "package" / "contents" / "ui"
        / "main.qml")


def block(text: str, head: str, start: int = 0) -> str:
    i = text.index(head, start)
    depth, j = 0, text.index("{", i)
    for k in range(j, len(text)):
        depth += {"{": 1, "}": -1}.get(text[k], 0)
        if depth == 0:
            return text[i:k + 1]
    raise AssertionError("unbalanced")


def prop(text: str, name: str) -> float:
    m = re.search(rf"readonly property real {name}: ([0-9.]+)", text)
    assert m, name
    return float(m.group(1))


class CompactForm(unittest.TestCase):
    def setUp(self):
        self.qml = MAIN.read_text()
        self.compact = block(self.qml, "compactRepresentation:")

    def test_the_limits_are_the_applications(self):
        self.assertEqual(prop(self.qml, "busyPct"), verdict.MACHINE_BUSY)
        self.assertEqual(prop(self.qml, "gpuFullPct"), verdict.GAME_GPU_FULL)
        self.assertEqual(prop(self.qml, "memFullPct"), verdict.MEM_FULL_PCT)
        self.assertEqual(prop(self.qml, "hotC"), verdict.HOT_C)
        for limit in ("root.busyPct", "root.gpuFullPct", "root.memFullPct"):
            self.assertIn(f"limit: {limit}", self.compact)
        self.assertIn("temp >= root.hotC", self.compact)

    def test_three_meters_with_theme_icons_and_fallbacks(self):
        icons = re.findall(r'icon: "([a-z-]+)"; iconFallback: "([a-z-]+)"', self.compact)
        self.assertEqual(icons, [("cpu", "computer"),
                                 ("video-display", "preferences-desktop-display"),
                                 ("memory", "media-flash")])
        self.assertIn("Kirigami.Icon {", self.compact)
        self.assertIn("fallback: meter.iconFallback", self.compact)
        self.assertIn("isMask: true", self.compact)
        for word in ('"CPU', '"GPU', '"RAM'):
            self.assertNotIn(word, self.compact, word)

    def test_a_bar_beside_each_number_in_the_themes_colours(self):
        self.assertIn("high ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.highlightColor",
                      self.compact)
        self.assertEqual(self.compact.count("visible: !compact.vertical && compact.withPct"), 1)
        self.assertEqual(self.compact.count("visible: compact.vertical && compact.withPct"), 1)
        self.assertNotRegex(self.compact, r"#[0-9a-fA-F]{6}")
        for own in ("root.cpuColor", "root.gpuColor", "root.memColor", "root.hotColor"):
            self.assertNotIn(own, self.compact, own)

    def test_the_widths_are_reserved(self):
        self.assertIn('"100% 100°" : "100%"', self.compact)
        self.assertIn("Layout.preferredWidth: vertical ? 0 : stripWidth", self.compact)
        self.assertNotIn("implicitWidth", self.compact)
        self.assertIn("Layout.maximumWidth: Layout.preferredWidth", self.compact)

    def test_the_tooltip_speaks_in_words(self):
        tip = block(self.qml, "toolTipSubText:")
        for word in ("Processor ", "graphics card ", "memory ", " of "):
            self.assertIn(word, tip)

    def test_the_full_form_keeps_its_own_colours(self):
        full = block(self.qml, "fullRepresentation:")
        for word in ("root.cpuColor", "root.memColor", "TOP PROCESSES"):
            self.assertIn(word, full)


if __name__ == "__main__":
    unittest.main()
