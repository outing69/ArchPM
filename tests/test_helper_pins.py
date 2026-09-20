"""The helper may import nothing from the package, so archpm/root/helper.py
carries its own copies of what archpm/snapshots.py has: the three name and
description regexes, the row regex for timeshift's listing, and a second
reading of snapper's JSON (snapper_numbers) and of timeshift's list
(timeshift_names). Nothing but a test holds the copies to each other;
these do. The last class feeds a real helper reply, the JSON line as main()
prints it and as the client reads it, straight into from_helper, and holds
that listing to the plain read's parse of the same text."""
from __future__ import annotations

import contextlib
import io
import json
import re
import unittest

from archpm import firewall, snapshots
from archpm.root import helper
from archpm.root.client import RootClient
from tests.test_firewall import FIREWALLD_PUBLIC, UFW_THIS_MACHINE
from tests.test_snapshots import SNAPPER_JSON, TIMESHIFT_LIST

# snapper's JSON with the shapes both readers must agree on: the live row
# (number 0), a negative number, a number that is text, a row that is not a
# dict, and the listing keyed by another name than the config
ODD_SNAPPER = json.dumps({"other": [
    {"number": 0, "type": "single", "description": "current"},
    {"number": -3, "type": "single"},
    {"number": "12", "type": "single"},
    "not a row",
    {"number": 7, "type": "single", "date": "2026-09-18 08:00:00"},
    {"number": 9, "type": "pre", "date": "2026-09-18 09:00:00"},
]})

# timeshift's listing with the shapes both readers must agree on: the
# header's own digits, a row without the ">" marker, extra spaces, and a
# name that is not a name
ODD_TIMESHIFT = """Device : /dev/sda2
3 snapshots, 230.0 GB free

Num     Name                 Tags  Description
------------------------------------------------------------------------------
0    >  2026-09-17_21-00-18  O     {timeshift-autosnap} {created before upgrade}
1       2026-09-18_00-00-01  D
2   >     2026-09-18_09-30-00  O B   before nvidia 580
3    >  not-a-snapshot-name  O
"""


def fake_run(answers: dict[str, str]):
    """helper.run answering by the command's first words."""
    def run(*cmd, timeout=20):
        key = " ".join(cmd)
        for k, v in answers.items():
            if key.startswith(k):
                return v
        raise AssertionError(f"unexpected command {cmd}")
    return run


class Regexes(unittest.TestCase):
    def test_the_three_patterns_are_the_same_text(self):
        for name in ("SNAPPER_CONFIG_RE", "DESCRIPTION_RE", "TIMESHIFT_NAME_RE"):
            with self.subTest(name=name):
                self.assertEqual(getattr(helper, name).pattern,
                                 getattr(snapshots, name).pattern)

    def test_what_the_page_lets_through_the_helper_accepts_and_the_rest_it_refuses(self):
        """sanitise() reduces a description to the helper's set so the
        helper never has to refuse one; the two rules must be the same rule."""
        cases = ["before nvidia 580", "clean install", "a" * 72, "a" * 73, "é", "x\n",
                 "$(id)", "a;b", "quote'", "  two   words  ", "", "dot.under_score-dash"]
        for text in cases:
            with self.subTest(text=text):
                clean = snapshots.sanitise(text)
                self.assertEqual(helper.check_description(clean), clean)
                accepted = helper.DESCRIPTION_RE.fullmatch(text) is not None
                self.assertEqual(accepted, snapshots.DESCRIPTION_RE.fullmatch(text) is not None)
                if not accepted:
                    self.assertNotEqual(clean, text, "what the helper refuses, sanitise changes")

    def test_the_timeshift_row_regex_finds_the_same_names_as_the_parser(self):
        for text in (TIMESHIFT_LIST, ODD_TIMESHIFT):
            helper_names = [m.group(1) for m in
                            (helper.TIMESHIFT_ROW_RE.match(line) for line in text.splitlines())
                            if m]
            page_names = [s.id for s in snapshots.parse_timeshift(text)]
            self.assertEqual(helper_names, page_names)
        self.assertEqual([s.id for s in snapshots.parse_timeshift(ODD_TIMESHIFT)],
                         ["2026-09-17_21-00-18", "2026-09-18_00-00-01", "2026-09-18_09-30-00"],
                         "the header's digits and a bad name match neither")
        self.assertTrue(all(re.fullmatch(helper.TIMESHIFT_NAME_RE.pattern, n)
                            for n in ["2026-09-17_21-00-18"]))


class SecondReadings(unittest.TestCase):
    """snapper_numbers and timeshift_names are what the helper's delete
    checks an id against; the page's parsers are what the user picked the
    id from. They must see the same snapshots."""

    def setUp(self):
        self.addCleanup(setattr, helper, "run", helper.run)

    def test_snapper_numbers_are_the_parsers_ids(self):
        for text in (SNAPPER_JSON, ODD_SNAPPER):
            with self.subTest(text=text[:40]):
                helper.run = fake_run({"snapper --jsonout --utc --iso -c root list": text})
                self.assertEqual(helper.snapper_numbers("root"),
                                 [int(s.id) for s in snapshots.parse_snapper("root", text)])
        self.assertEqual(helper.snapper_numbers("root"), [7, 9],
                         "row 0, a negative, a text number and a non-row are skipped by both; "
                         "a listing keyed by another name is read by both")

    def test_timeshift_names_are_the_parsers_ids(self):
        for text in (TIMESHIFT_LIST, ODD_TIMESHIFT):
            with self.subTest(text=text[:40]):
                helper.run = fake_run({"timeshift --list": text})
                self.assertEqual(helper.timeshift_names(),
                                 [s.id for s in snapshots.parse_timeshift(text)])


class RealReply(unittest.TestCase):
    """The helper's reply as pkexec hands it over: main() prints one JSON
    line, the client reads it, from_helper builds the listing. Held to the
    plain read's parse of the same text, so the two routes cannot drift."""

    def setUp(self):
        self.addCleanup(setattr, helper, "run", helper.run)
        self.addCleanup(setattr, helper, "snapshot_tool", helper.snapshot_tool)
        self.addCleanup(setattr, helper.os.path, "isfile", helper.os.path.isfile)

    def reply(self, argv: list[str]) -> dict:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = helper.main(argv)
        self.assertEqual(code, 0, out.getvalue())
        return RootClient.parse(code, out.getvalue(), "")

    def test_snapper_list_through_the_helper_is_the_plain_reads_list(self):
        helper.snapshot_tool = lambda: "snapper"
        helper.run = fake_run({"snapper --jsonout list-configs":
                               '{"configs": [{"config": "root", "subvolume": "/"}]}',
                               "snapper --jsonout --utc --iso -c root list": SNAPPER_JSON})
        listing = snapshots.from_helper(self.reply(["snapshots-list"]))
        self.assertEqual((listing.tool, listing.as_root, listing.error), ("snapper", True, ""))
        self.assertIsInstance(listing.took_ms, float)
        self.assertEqual(listing.snapshots, snapshots.parse("snapper", [("root", SNAPPER_JSON)]))
        self.assertEqual([s.id for s in listing.snapshots], ["266", "265", "264", "200", "150"],
                         "newest first, as the plain read orders them")
        pre = next(s for s in listing.snapshots if s.id == "264")
        self.assertEqual((pre.kind, pre.pair), ("pre", "265"), "the pair survives the round trip")

    def test_timeshift_list_through_the_helper_is_the_plain_reads_list(self):
        helper.snapshot_tool = lambda: "timeshift"
        helper.run = fake_run({"timeshift --list": TIMESHIFT_LIST})
        listing = snapshots.from_helper(self.reply(["snapshots-list"]))
        self.assertEqual((listing.tool, listing.as_root), ("timeshift", True))
        self.assertEqual(listing.snapshots,
                         snapshots.parse("timeshift", [("timeshift", TIMESHIFT_LIST)]))
        self.assertEqual([s.origin for s in listing.snapshots],
                         [snapshots.BY_HAND, snapshots.SCHEDULED, snapshots.PACMAN],
                         "newest first: the one taken by hand, the scheduled one, pacman's")

    def test_ufw_status_through_the_helper_is_the_plain_reads_state(self):
        helper.os.path.isfile = lambda p: p == helper.UFW_BIN
        helper.run = fake_run({"ufw status verbose": UFW_THIS_MACHINE})
        state = firewall.from_helper(self.reply(["firewall-status"]))
        plain = firewall.parse("ufw", [("status", UFW_THIS_MACHINE)])
        self.assertEqual((state.tool, state.as_root), ("ufw", True))
        self.assertIsInstance(state.took_ms, float)
        for field in ("running", "incoming", "rules", "needs_root", "error"):
            with self.subTest(field=field):
                self.assertEqual(getattr(state, field), getattr(plain, field))
        self.assertTrue(state.running)
        self.assertTrue(state.rules, "the rules came through")

    def test_firewalld_status_through_the_helper_is_the_plain_reads_state(self):
        helper.os.path.isfile = lambda p: p == helper.FIREWALL_CMD_BIN
        helper.run = fake_run({"firewall-cmd --state": "running",
                               "firewall-cmd --get-default-zone": "public",
                               "firewall-cmd --zone=public --list-all": FIREWALLD_PUBLIC})
        state = firewall.from_helper(self.reply(["firewall-status"]))
        plain = firewall.parse("firewalld", [("state", "running"), ("zone", "public"),
                                             ("list-all", FIREWALLD_PUBLIC)])
        self.assertEqual((state.tool, state.as_root), ("firewalld", True))
        for field in ("running", "incoming", "rules", "needs_root", "error"):
            with self.subTest(field=field):
                self.assertEqual(getattr(state, field), getattr(plain, field))
        self.assertTrue(state.running)
        self.assertTrue(state.rules)


if __name__ == "__main__":
    unittest.main()
