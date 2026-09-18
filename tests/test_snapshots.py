"""The snapshots module: detection, the plain read, the two parsers, the
origin of a snapshot, the description's character set, and what the
confirmation needs (position and remainder). No root, no real snapshot is
touched; the last test only reads this machine."""
from __future__ import annotations

import json
import subprocess
import time
import unittest
from types import SimpleNamespace

from archpm import snapshots as S

SNAPPER_JSON = json.dumps({"root": [
    {"subvolume": "/", "number": 0, "type": "single", "pre-number": None, "date": "",
     "user": "root", "cleanup": "", "description": "current", "userdata": None},
    {"subvolume": "/", "number": 264, "type": "pre", "pre-number": None,
     "date": "2026-09-17 19:02:09", "user": "root", "cleanup": "number",
     "description": "pacman -U archpm-0.2.36-1-any.pkg.tar.zst", "userdata": None},
    {"subvolume": "/", "number": 265, "type": "post", "pre-number": 264,
     "date": "2026-09-17 19:02:11", "user": "root", "cleanup": "number",
     "description": "archpm", "userdata": None},
    {"subvolume": "/", "number": 200, "type": "single", "pre-number": None,
     "date": "2026-09-10 02:00:00", "user": "root", "cleanup": "timeline",
     "description": "timeline", "userdata": None},
    {"subvolume": "/", "number": 266, "type": "single", "pre-number": None,
     "date": "2026-09-18 08:00:00", "user": "root", "cleanup": "",
     "description": "before nvidia 580", "userdata": {"made-by": "archpm"},
     "used-space": 123456789},
    {"subvolume": "/", "number": 150, "type": "single", "pre-number": None,
     "date": "2026-09-01 12:00:00", "user": "alex", "cleanup": "",
     "description": "clean install", "userdata": {"important": "yes"}},
]})

TIMESHIFT_LIST = """Device : /dev/sda2
UUID   : cded9b3d-e90d-4ea8-8f71-33fbfa45e51f
Path   : /run/timeshift/backup
Mode   : BTRFS
Status : OK
3 snapshots, 230.0 GB free

Num     Name                 Tags  Description
------------------------------------------------------------------------------
0    >  2026-09-17_21-00-18  O     {timeshift-autosnap} {created before upgrade}
1    >  2026-09-18_00-00-01  D
2    >  2026-09-18_09-30-00  O     before nvidia 580
"""


def fake_run(responses):
    """A subprocess.run that answers by the argv's first words."""
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        for key, (code, out, err) in responses.items():
            if " ".join(argv).startswith(key):
                return SimpleNamespace(returncode=code, stdout=out, stderr=err)
        raise AssertionError(f"unexpected command {argv}")
    run.calls = calls
    return run


class Detect(unittest.TestCase):
    def test_neither_tool(self):
        setup = S.detect(which=lambda n: None, run=fake_run({}))
        self.assertEqual((setup.snapper, setup.timeshift, setup.tool, setup.limine_entries),
                         (False, False, "", 0))

    def test_snapper_with_its_configs_and_limine(self):
        run = fake_run({"snapper --jsonout list-configs":
                        (0, '{"configs": [{"config": "root", "subvolume": "/"},'
                            ' {"config": "home", "subvolume": "/home"}]}', "")})
        setup = S.detect(which=lambda n: "/usr/bin/" + n, run=run)
        self.assertEqual((setup.tool, setup.configs), ("snapper", ["root", "home"]))
        self.assertGreater(setup.limine_entries, 0)

    def test_timeshift_alone(self):
        setup = S.detect(which=lambda n: "/usr/bin/timeshift" if n == "timeshift" else None,
                         run=fake_run({}))
        self.assertEqual((setup.tool, setup.configs, setup.limine_entries), ("timeshift", [], 0))

    def test_limine_entries_from_its_config(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as fh:
            fh.write("# comment\nMAX_SNAPSHOT_ENTRIES=8\nLIMIT_USAGE_PERCENT=85\n")
            path = fh.name
        try:
            self.assertEqual(S.limine_entries(path, which=lambda n: "/usr/bin/x"), 8)
            self.assertEqual(S.limine_entries(path, which=lambda n: None), 0)
        finally:
            import os
            os.unlink(path)
        self.assertEqual(S.limine_entries("/nonexistent", which=lambda n: "/usr/bin/x"), 5)


class ParseSnapper(unittest.TestCase):
    def test_rows_newest_first_without_the_live_row(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        self.assertEqual([s.id for s in rows], ["266", "265", "264", "200", "150"])
        self.assertTrue(all(s.tool == "snapper" and s.config == "root" for s in rows))

    def test_origin_and_why(self):
        by_id = {s.id: s for s in S.parse("snapper", [("root", SNAPPER_JSON)])}
        self.assertEqual(by_id["264"].why, "pacman, before")
        self.assertEqual(by_id["265"].why, "pacman, after")
        self.assertEqual(by_id["200"].origin, S.TIMELINE)
        self.assertEqual(by_id["266"].origin, S.ARCHPM)
        self.assertEqual(by_id["150"].origin, S.BY_HAND)

    def test_pairs_are_known_from_both_halves(self):
        by_id = {s.id: s for s in S.parse("snapper", [("root", SNAPPER_JSON)])}
        self.assertEqual(by_id["265"].pair, "264")
        self.assertEqual(by_id["264"].pair, "265")
        self.assertEqual(by_id["266"].pair, "")

    def test_size_only_where_snapper_reports_it(self):
        by_id = {s.id: s for s in S.parse("snapper", [("root", SNAPPER_JSON)])}
        self.assertEqual(by_id["266"].size, 123456789)
        self.assertIsNone(by_id["265"].size)

    def test_utc_date_becomes_epoch(self):
        by_id = {s.id: s for s in S.parse("snapper", [("root", SNAPPER_JSON)])}
        import calendar
        self.assertEqual(by_id["266"].taken_at,
                         calendar.timegm(time.strptime("2026-09-18 08:00:00", "%Y-%m-%d %H:%M:%S")))
        self.assertEqual(by_id["266"].label, "#266")

    def test_garbage_is_an_empty_list(self):
        self.assertEqual(S.parse("snapper", [("root", "not json"), ("root", "")]), [])
        self.assertEqual(S.parse("snapper", [("root", '{"root": "x"}')]), [])


class ParseTimeshift(unittest.TestCase):
    def test_rows_tags_and_origin(self):
        rows = S.parse("timeshift", [("timeshift", TIMESHIFT_LIST)])
        self.assertEqual([s.id for s in rows],
                         ["2026-09-18_09-30-00", "2026-09-18_00-00-01", "2026-09-17_21-00-18"])
        by_id = {s.id: s for s in rows}
        self.assertEqual(by_id["2026-09-17_21-00-18"].origin, S.PACMAN)
        self.assertEqual(by_id["2026-09-18_00-00-01"].origin, S.SCHEDULED)
        self.assertEqual(by_id["2026-09-18_09-30-00"].origin, S.BY_HAND)
        self.assertEqual(by_id["2026-09-18_09-30-00"].description, "before nvidia 580")
        self.assertEqual(by_id["2026-09-18_00-00-01"].description, "")
        self.assertIsNone(by_id["2026-09-18_09-30-00"].size)
        self.assertEqual(by_id["2026-09-18_09-30-00"].label, "2026-09-18_09-30-00")


class Rows(unittest.TestCase):
    """The list's rows: a pacman pair folded into one, the rest single,
    grouped by who took them with yours on top."""

    def test_a_pair_is_one_row_at_the_before_time(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        entries = S.fold(rows)
        self.assertEqual([e.label for e in entries], ["#266", "#264 · #265", "#200", "#150"])
        pair = entries[1]
        self.assertIsInstance(pair, S.Pair)
        self.assertEqual((pair.pre.id, pair.post.id), ("264", "265"))
        self.assertEqual(pair.taken_at, pair.pre.taken_at)
        self.assertEqual(pair.description, "pacman -U archpm-0.2.36-1-any.pkg.tar.zst")
        self.assertEqual([s.id for s in pair.halves], ["265", "264"])
        self.assertEqual((pair.why, pair.origin, pair.config), ("pacman", S.PACMAN, "root"))
        self.assertIsNone(pair.size)

    def test_a_pair_sums_the_sizes_it_has(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        by_id = {s.id: s for s in rows}
        by_id["264"].size, by_id["265"].size = 1000, 24
        self.assertEqual(S.fold(rows)[1].size, 1024)
        by_id["265"].size = None
        self.assertEqual(S.fold(rows)[1].size, 1000)

    def test_a_half_without_its_other_half_stays_a_row(self):
        rows = [s for s in S.parse("snapper", [("root", SNAPPER_JSON)]) if s.id != "265"]
        entries = S.fold(rows)
        self.assertEqual([e.label for e in entries], ["#266", "#264", "#200", "#150"])
        self.assertTrue(all(isinstance(e, S.Snapshot) for e in entries))
        self.assertEqual(entries[1].why, "pacman, before")

    def test_a_pair_needs_a_before_and_an_after(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        by_id = {s.id: s for s in rows}
        by_id["264"].kind = "single"          # the pair claim points at a single
        self.assertEqual(len(S.fold(rows)), 5)

    def test_grouped_yours_first_and_empty_groups_left_out(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        groups = S.grouped(S.fold(rows))
        self.assertEqual([(g, [e.label for e in m]) for g, m in groups],
                         [(S.YOURS, ["#266", "#150"]), (S.PACMANS, ["#264 · #265"]),
                          (S.TIMED, ["#200"])])
        pacman_only = [s for s in rows if s.origin == S.PACMAN]
        self.assertEqual([g for g, _m in S.grouped(S.fold(pacman_only))], [S.PACMANS])
        self.assertEqual(S.grouped([]), [])

    def test_timeshift_rows_fold_to_nothing_and_group_by_origin(self):
        rows = S.parse("timeshift", [("timeshift", TIMESHIFT_LIST)])
        entries = S.fold(rows)
        self.assertEqual(len(entries), 3)
        self.assertEqual([g for g, _m in S.grouped(entries)], [S.YOURS, S.PACMANS, S.TIMED])
        self.assertEqual(S.count_rows(rows), (6, 6))

    def test_count_rows_as_on_a_machine_of_pairs(self):
        """snap-pac only, NUMBER_LIMIT 50: 25 transactions, 50 snapshots."""
        rows = []
        for i in range(25):
            pre = S.Snapshot("snapper", "root", str(218 + 2 * i), taken_at=1000.0 + i,
                             kind="pre", origin=S.PACMAN, pair=str(219 + 2 * i))
            post = S.Snapshot("snapper", "root", str(219 + 2 * i), taken_at=1001.0 + i,
                              kind="post", origin=S.PACMAN, pair=str(218 + 2 * i))
            rows += [post, pre]
        rows.reverse()
        self.assertEqual(S.count_rows(rows), (26, 76))
        self.assertEqual(S.count_rows(S.parse("snapper", [("root", SNAPPER_JSON)])), (7, 9))
        self.assertEqual(S.count_rows([]), (0, 0))


class PlainRead(unittest.TestCase):
    def test_no_tool_is_an_empty_listing(self):
        listing = S.read_as_user(S.Setup(), run=fake_run({}))
        self.assertEqual((listing.tool, listing.needs_root, listing.snapshots), ("", False, []))

    def test_snapper_refusal_means_needs_root(self):
        run = fake_run({"snapper --jsonout --utc --iso -c root list": (1, "", "No permissions.\n")})
        listing = S.read_as_user(S.Setup(snapper=True, configs=["root"]), run=run)
        self.assertTrue(listing.needs_root)
        self.assertEqual(listing.error, "")
        self.assertEqual(listing.snapshots, [])

    def test_snapper_allowed_user_gets_the_list(self):
        run = fake_run({"snapper --jsonout --utc --iso -c root list": (0, SNAPPER_JSON, "")})
        listing = S.read_as_user(S.Setup(snapper=True, configs=["root"]), run=run)
        self.assertFalse(listing.needs_root)
        self.assertEqual(len(listing.snapshots), 5)
        self.assertTrue(listing.sized)
        self.assertGreaterEqual(listing.took_ms, 0)

    def test_other_error_is_reported(self):
        run = fake_run({"snapper": (1, "", "some other failure\n")})
        listing = S.read_as_user(S.Setup(snapper=True, configs=["root"]), run=run)
        self.assertFalse(listing.needs_root)
        self.assertEqual(listing.error, "some other failure")

    def test_timeshift_always_needs_root(self):
        run = fake_run({})
        listing = S.read_as_user(S.Setup(timeshift=True), run=run)
        self.assertTrue(listing.needs_root)
        self.assertEqual(run.calls, [], "timeshift is not even asked as a plain user")

    def test_from_helper(self):
        listing = S.from_helper({"tool": "snapper", "outputs": [["root", SNAPPER_JSON]],
                                 "took_ms": 31.5})
        self.assertTrue(listing.as_root)
        self.assertEqual(listing.took_ms, 31.5)
        self.assertEqual(len(listing.snapshots), 5)


class Description(unittest.TestCase):
    def test_sanitise_keeps_the_fixed_set_only(self):
        self.assertEqual(S.sanitise("before nvidia 580"), "before nvidia 580")
        self.assertEqual(S.sanitise("  before;rm -rf /  $(x) `y` 'z' \"q\"\n"), "before rm -rf x y z q")
        self.assertEqual(S.sanitise("é ünïcode – dash"), "n code dash")
        self.assertEqual(S.sanitise("a" * 100), "a" * S.DESCRIPTION_MAX)
        self.assertEqual(S.sanitise(""), "")
        self.assertEqual(S.sanitise("<b>bold</b>"), "b bold b")

    def test_the_result_always_passes_the_helper_rule(self):
        for text in ("x" * 200, "a\tb\nc", "ok. fine_really-yes", "\x00\x7f"):
            with self.subTest(text=text):
                self.assertIsNotNone(S.DESCRIPTION_RE.fullmatch(S.sanitise(text)))


class Confirmation(unittest.TestCase):
    def rows(self):
        return S.parse("snapper", [("root", SNAPPER_JSON)])

    def test_position(self):
        rows = self.rows()
        self.assertEqual(S.position(rows[0], rows), "the newest")
        self.assertEqual(S.position(rows[-1], rows), "the oldest")
        self.assertEqual(S.position(rows[2], rows), "")
        self.assertEqual(S.position(rows[0], rows[:1]), "")

    def test_remaining_leaves_the_others(self):
        rows = self.rows()
        left = S.remaining(rows[1], rows)
        self.assertEqual([s.id for s in left], ["266", "264", "200", "150"])

    def test_restore_advice_names_the_way(self):
        limine = S.restore_advice(S.Setup(snapper=True), which=lambda n: "/usr/bin/" + n)
        self.assertIn("limine-snapper-restore", limine)
        plain = S.restore_advice(S.Setup(snapper=True), which=lambda n: None)
        self.assertIn("snapper rollback", plain)
        self.assertIn("timeshift --restore", S.restore_advice(S.Setup(timeshift=True)))
        self.assertEqual(S.restore_advice(S.Setup()), "")


class OnThisMachine(unittest.TestCase):
    def test_the_plain_read_never_raises(self):
        setup = S.detect()
        listing = S.read_as_user(setup)
        self.assertEqual(listing.tool, setup.tool)
        if setup.tool == "snapper":
            self.assertTrue(listing.needs_root or listing.snapshots is not None)
        self.assertIsInstance(listing.took_ms, float)


if __name__ == "__main__":
    unittest.main()
