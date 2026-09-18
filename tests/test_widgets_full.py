"""The full representation of both widgets, read as text: the rules that
keep the content inside the widget's width. An address is never cut, a
sentence wraps, a program name may elide with the full name in a tooltip,
and no row holds a text that can neither shrink nor wrap next to one that
cannot either. No Plasma here; the QML is not run."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "plasmoid"
NETWORK = ROOT / "network" / "contents" / "ui" / "main.qml"
MONITOR = ROOT / "package" / "contents" / "ui" / "main.qml"


def block(text: str, head: str, start: int = 0) -> str:
    i = text.index(head, start)
    depth, j = 0, text.index("{", i)
    for k in range(j, len(text)):
        depth += {"{": 1, "}": -1}.get(text[k], 0)
        if depth == 0:
            return text[i:k + 1]
    raise AssertionError("unbalanced")


class NetworkFull(unittest.TestCase):
    def setUp(self):
        self.qml = NETWORK.read_text()
        self.full = block(self.qml, "fullRepresentation:")

    def test_an_interface_is_a_flow_and_its_address_never_elides(self):
        row = block(self.full, "Flow {", self.full.index("model: root.ifaces"))
        self.assertIn("modelData.addr", row)
        self.assertNotIn("elide", row)
        self.assertNotIn("fillWidth: true\n                        elide", row)

    def test_a_program_name_elides_with_the_full_name_in_a_tooltip(self):
        name = block(self.qml, "component Name:")
        self.assertIn("elide: Text.ElideRight", name)
        self.assertIn("QQC2.ToolTip.visible: hover.hovered && truncated", name)
        self.assertIn("QQC2.ToolTip.text: text", name)
        talkers = block(self.full, "RowLayout {", self.full.index("model: root.talkers"))
        self.assertIn("Name {", talkers)
        self.assertIn("Layout.minimumWidth: 0", talkers)

    def test_a_door_row_wraps_its_ports_and_bounds_its_name(self):
        door = block(self.full, "Flow {", self.full.index("model: root.doors"))
        self.assertIn("wrapMode: Text.WordWrap", door)
        self.assertIn("width: Math.min(implicitWidth, door.width)", door)
        self.assertEqual(door.count("width: Math.min(implicitWidth, door.width)"), 2)

    def test_sentences_wrap(self):
        for sentence in ("Reachable from other devices", "No data. Start the agent"):
            i = self.full.index(sentence)
            text = self.full[self.full.rindex("Text {", 0, i):i]
            self.assertIn("wrapMode: Text.WordWrap", text, sentence)
            self.assertIn("Layout.fillWidth: true", text, sentence)

    def test_the_compact_form_is_untouched_since_0_2_42(self):
        compact = block(self.qml, "compactRepresentation:")
        self.assertEqual(compact.count("Rate {"), 2)
        self.assertIn('text: "↓ 1023.9 MB/s"', compact)
        self.assertNotIn("QQC2", compact)


class MonitorFull(unittest.TestCase):
    def setUp(self):
        self.qml = MONITOR.read_text()
        self.full = block(self.qml, "fullRepresentation:")

    def test_top_processes_elide_the_name_with_a_tooltip(self):
        rows = block(self.full, "RowLayout {", self.full.index("model: root.stats.top_cpu"))
        self.assertIn("elide: Text.ElideRight", rows)
        self.assertIn("Layout.fillWidth: true", rows)
        self.assertIn("QQC2.ToolTip.visible: nameHover.hovered && truncated", rows)

    def test_the_game_line_wraps_and_the_title_has_a_tooltip(self):
        game = block(self.full, "ColumnLayout {", self.full.index("the running game"))
        self.assertIn("wrapMode: Text.WordWrap", game)
        self.assertIn("QQC2.ToolTip.visible: gameHover.hovered && truncated", game)

    def test_the_compact_form_is_untouched(self):
        compact = block(self.qml, "compactRepresentation:")
        self.assertNotIn("QQC2", compact)
        self.assertNotIn("wrapMode", compact)


if __name__ == "__main__":
    unittest.main()
