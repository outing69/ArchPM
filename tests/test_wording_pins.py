"""Numbers and names that appear in more than one place are pinned to each
other here, the way the README's checkout tag and the polkit actions are:
the thresholds in the Help, the README and the widget's settings page; the
rail's icon count; the agent's measured cost; the tools whose stderr the
helper relays; the hint keys the pages attach; one screenshot per page;
the two widgets; the one shape a span of time has."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from archpm import helptext, verdict

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
SECURITY = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
HELPER = (ROOT / "archpm" / "root" / "helper.py").read_text(encoding="utf-8")
CONFIG_QML = (ROOT / "plasmoid" / "package" / "contents" / "ui" / "configGeneral.qml").read_text()
MAIN_QML = (ROOT / "plasmoid" / "package" / "contents" / "ui" / "main.qml").read_text()
UI_SOURCES = "".join(p.read_text(encoding="utf-8")
                     for p in sorted((ROOT / "archpm" / "ui").glob("*.py")))
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10}

try:
    from PySide6.QtWidgets import QApplication
except ImportError:                       # pragma: no cover
    QApplication = None


def flat(text: str) -> str:
    return " ".join(text.split())


class Thresholds(unittest.TestCase):
    """verdict.py holds the numbers; the Help builds its sentences from them,
    and the README and the widget's settings page are held to them here."""

    def test_the_help_names_the_codes_numbers(self):
        cpu = helptext.term("CPU temperature").text
        self.assertIn(f"warm from {verdict.WARM_C:.0f} °C", cpu)
        self.assertIn(f"turns red at {verdict.HOT_C:.0f} °C", cpu)
        scale = dict(helptext.COLOURS)["Green · orange · red"]
        self.assertIn(f"green is under {verdict.LOAD_WARN_PCT:.0f}%", scale)
        self.assertIn(f"red from {verdict.LOAD_HOT_PCT:.0f}%", scale)
        self.assertIn(f"normal is under {verdict.WARM_C:.0f} °C, warm to {verdict.HOT_C:.0f} °C",
                      scale)
        line = helptext.hint("tile.verdict").normal
        self.assertIn(f"memory above {verdict.MEM_FULL_PCT:.0f}%", line)
        self.assertIn(f"a part above {verdict.HOT_C:.0f} °C", line)

    def test_the_readme_says_the_same(self):
        text = flat(README)
        self.assertIn(f"memory above {verdict.MEM_FULL_PCT:.0f}% of RAM", text)
        self.assertIn(f"whole processor above {verdict.MACHINE_BUSY:.0f}%", text)
        self.assertIn(f"a part above {verdict.HOT_C:.0f} °C", text)
        self.assertIn(f"(under {verdict.WARM_C:.0f} °C, to {verdict.HOT_C:.0f} °C, above)", text)

    def test_the_widget_settings_page_and_the_widget_agree(self):
        self.assertIn(f"Values turn red above {verdict.HOT_C:.0f} °C", CONFIG_QML)
        m = re.search(r"readonly property real hotC: ([0-9.]+)", MAIN_QML)
        self.assertEqual(float(m.group(1)), verdict.HOT_C)

    @unittest.skipUnless(QApplication, "PySide6 not installed")
    def test_the_theme_colours_load_at_those_steps(self):
        from archpm.ui import theme
        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)
        self.assertEqual(theme.heat(verdict.LOAD_WARN_PCT - 1).name(), theme.OK.lower())
        self.assertEqual(theme.heat(verdict.LOAD_WARN_PCT).name(), theme.WARN.lower())
        self.assertEqual(theme.heat(verdict.LOAD_HOT_PCT).name(), theme.CRIT.lower())


class Counts(unittest.TestCase):
    @unittest.skipUnless(QApplication, "PySide6 not installed")
    def test_the_rail_icon_count_in_the_help_and_the_docstring(self):
        from archpm.ui import navrail
        n = len(navrail.ADWAITA_ICONS)
        m = re.search(r"every one of its (\w+) icons", helptext.term("Rail icons").text)
        self.assertEqual(WORDS[m.group(1)], n)
        m = re.search(r"theme for (\w+) icons", navrail.__doc__ or "")
        doc = (ROOT / "archpm" / "ui" / "navrail.py").read_text(encoding="utf-8")
        m = re.search(r"the app's theme for (\w+) icons", doc)
        self.assertEqual(WORDS[m.group(1)], n)

    def test_the_agents_cost_is_the_readmes(self):
        from archpm import agent
        in_doc = set(re.findall(r"\d+\.\d+%", agent.__doc__))
        row = next(line for line in README.splitlines() if line.startswith("| **Agent**"))
        self.assertEqual(in_doc, set(re.findall(r"\d+\.\d+%", row)))
        self.assertEqual(len(in_doc), 4)

    def test_security_names_every_tool_whose_stderr_the_helper_relays(self):
        from archpm.root import helper
        tools = set(re.findall(r'run\("([a-z-]+)"', HELPER))
        tools |= {cmd[0] for cmd, _timeout in helper.CLEANUP.values()}
        self.assertGreaterEqual(len(tools), 7)
        sentence = next(p for p in flat(SECURITY).split("- ")
                        if "stderr" in p and "passed back" in p)
        for tool in tools:
            with self.subTest(tool=tool):
                self.assertIn(tool, sentence)

    def test_two_widgets_everywhere(self):
        n = len(list((ROOT / "plasmoid").glob("*/metadata.json")))
        self.assertEqual(n, 2)
        word = {v: k for k, v in WORDS.items()}[n]
        for path, needle in ((ROOT / "pyproject.toml", f"{word} Plasma 6 widgets"),
                             (ROOT / "packaging" / "aur" / "PKGBUILD", f"{word} Plasma 6 widgets"),
                             (ROOT / "systemd" / "archpm-agent.service", f"{word} Plasma widgets")):
            with self.subTest(file=path.name):
                self.assertIn(needle, path.read_text(encoding="utf-8"))

    def test_one_screenshot_per_page(self):
        app_src = (ROOT / "archpm" / "ui" / "app.py").read_text(encoding="utf-8")
        pages = re.findall(r'add_page\([^,]+, "([A-Za-z]+)"\)', app_src)
        self.assertGreaterEqual(len(pages), 8)
        for page in pages:
            with self.subTest(page=page):
                self.assertTrue((ROOT / "docs" / f"{page.lower()}.png").is_file())
                self.assertIn(f"docs/{page.lower()}.png", README)


class Hints(unittest.TestCase):
    def test_every_hint_is_attached_and_every_attached_key_exists(self):
        prefixes = {k.split(".")[0] for k in helptext.HINTS}
        pattern = re.compile('"((?:' + "|".join(sorted(prefixes)) + r')\.[a-z0-9 ._%-]+)"')
        used = set(pattern.findall(UI_SOURCES))
        self.assertEqual(sorted(set(helptext.HINTS) - used), [], "hints nothing attaches")
        self.assertEqual(sorted(used - set(helptext.HINTS)), [], "keys with no hint")


class Words(unittest.TestCase):
    def test_a_span_of_time_has_one_shape(self):
        d = helptext.duration
        spans = [d(3), d(45), d(12 * 60), d(3 * 3600 + 5 * 60), d(2 * 86400 + 14 * 3600)]
        self.assertEqual(spans, ["just now", "45 s", "12 min", "3 h 05", "2 d 14 h"])
        for name in ("dashboard.py", "proc_model.py"):
            src = (ROOT / "archpm" / "ui" / name).read_text(encoding="utf-8")
            self.assertIn("duration(", src)
        sysinfo = (ROOT / "archpm" / "sysinfo.py").read_text(encoding="utf-8")
        self.assertIn("duration(up)", sysinfo)

    def test_pages_are_pages_not_tabs(self):
        for path in sorted((ROOT / "archpm" / "ui").glob("*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue
            with self.subTest(file=path.name):
                self.assertNotRegex(lines[0], r"\btab\b(?! bar)")   # "instead of a tab bar" is fine
        self.assertNotIn("This tab", UI_SOURCES)
        for section in helptext.GLOSSARY:
            for term in section.terms:
                self.assertNotRegex(term.where, r"\btab\b", term.name)

    def test_the_series_colours_the_help_describes_are_the_graphs(self):
        src = (ROOT / "archpm" / "ui" / "dashboard.py").read_text(encoding="utf-8")
        self.assertIn('Graph([("GPU load", "GPU"), ("Video memory", "DISK")]', src)
        self.assertIn('Graph([("Download", "NET"), ("Upload", "CPU")]', src)
        self.assertIn('Graph([("Disk read", "DISK"), ("Disk write", "SWAP")]', src)
        text = dict(helptext.COLOURS)["Series colours"]
        for phrase in ("video memory takes disk's pink", "upload takes CPU's yellow",
                       "disk write takes swap's orange"):
            self.assertIn(phrase, text)

    def test_controls_the_glossary_points_at_exist(self):
        src = (ROOT / "archpm" / "ui" / "procview.py").read_text(encoding="utf-8")
        model = (ROOT / "archpm" / "ui" / "proc_model.py").read_text(encoding="utf-8")
        for where, needle, where_src in (
                ("Threads column", '"Threads"', model), ("Priority column", '"Priority"', model),
                ("Disk column", '"Disk"', model), ("Video memory column", '"Video memory"', model),
                ("Cores it may use…", '"Cores it may use…"', src),
                ("Pause, Resume", '"Pause"', src)):
            with self.subTest(where=where):
                self.assertTrue(any(where in t.where for s in helptext.GLOSSARY
                                    for t in s.terms), where)
                self.assertIn(needle, where_src)
        self.assertIn('"CPU as % of all cores"', src)
        parent = helptext.term("Parent and children").text
        self.assertIn("Terminate with everything it started", parent)


if __name__ == "__main__":
    unittest.main()
