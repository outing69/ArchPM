"""The Help tab's content: nothing empty, search works, changelog is found."""
from __future__ import annotations

import unittest

from archpm import helptext


class Glossary(unittest.TestCase):
    def test_every_term_has_a_real_explanation(self):
        names = []
        for sec in helptext.GLOSSARY:
            self.assertTrue(sec.terms, sec.title)
            for t in sec.terms:
                names.append(t.name)
                self.assertGreater(len(t.text), 60, t.name)
                self.assertTrue(t.text.endswith("."), t.name)
        self.assertEqual(len(names), len(set(names)), "duplicate term")

    def test_the_words_a_beginner_asked_about_are_in(self):
        all_names = {t.name.lower() for s in helptext.GLOSSARY for t in s.terms}
        for word in ("pid", "nice", "thread", "vram", "affinity", "root", "cache"):
            self.assertTrue(any(word in n for n in all_names), word)

    def test_search_narrows_and_is_case_insensitive(self):
        hits = helptext.search("NICE")
        self.assertTrue(hits)
        self.assertTrue(all("nice" in (t.name + t.text).lower()
                            for s in hits for t in s.terms))
        self.assertEqual(helptext.search("zzzz-nothing"), [])
        self.assertEqual(helptext.search("  "), list(helptext.GLOSSARY))

    def test_colours_cover_the_two_roles(self):
        names = [n for n, _ in helptext.COLOURS]
        self.assertIn("Yellow", names)
        self.assertIn("Blue", names)


class Changelog(unittest.TestCase):
    def test_changelog_is_found_in_the_checkout_and_lists_every_tag(self):
        text = helptext.changelog_text()
        for version in ("0.1.0", "0.1.1", "0.1.2", "0.1.3", "0.1.4", "0.1.5"):
            self.assertIn(f"## {version}", text)
        self.assertIn(helptext.__version__.split("+")[0][:5], text)


if __name__ == "__main__":
    unittest.main()


class Hints(unittest.TestCase):
    def test_every_hint_points_at_a_real_term_and_reads_as_a_sentence(self):
        for key, h in helptext.HINTS.items():
            self.assertTrue(h.text.endswith("."), key)
            self.assertLess(len(h.text), 160, f"{key}: a tooltip is one line, not a lecture")
            if h.term:
                self.assertIsNotNone(helptext.term(h.term), f"{key} → {h.term!r}")
            if h.normal:
                self.assertTrue(h.normal.endswith("."), key)

    def test_the_things_a_beginner_hovers_over_have_a_normal_line(self):
        for key in ("tile.cpu", "tile.cpu temp", "tile.gpu", "tile.gpu temp", "tile.memory",
                    "tile.vram", "graph.mem", "net.doors"):
            self.assertTrue(helptext.hint(key).normal, key)

    def test_unknown_key_is_none(self):
        self.assertIsNone(helptext.hint("tile.nonsense"))
        self.assertIsNone(helptext.term("Nonsense"))
