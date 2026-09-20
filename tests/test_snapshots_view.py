"""The Snapshots page's states: no tool, a tool without snapshots, a tool
that keeps its list for root, and a list; the buttons that go with each,
and the confirmation that says what is lost and what remains. Offscreen;
nothing is taken or deleted (no helper is run)."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QSettings
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm import snapshots as S
from tests.test_snapshots import SNAPPER_JSON


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def view(self, setup, listing, ready=None):
        from archpm.root.client import RootClient
        from archpm.ui import snapshots as view
        v = view.SnapshotsView(RootClient())
        v.read = lambda: None            # no real read in a test
        if ready is not None:
            fake = type("St", (), {"ready": ready})()
            view.check = lambda: fake
            self.addCleanup(setattr, view, "check", __import__("archpm.root.client",
                                                                fromlist=["check"]).check)
        v.setup = setup
        v._show(listing)
        self.addCleanup(self.settle, v)
        return v

    @staticmethod
    def settle(v):
        """Rows that clear() has handed to deleteLater are deleted by the
        event loop, while the page is still alive; a page dropped by Python
        with those deletes pending crashes a later test's event loop."""
        QTest.qWait(10)
        v.deleteLater()
        QTest.qWait(10)

    def buttons(self, v):
        """The page's buttons: the head's when shown, and the rows'. A row
        that clear() has just removed is gone from rows() at once, while
        its widgets wait for deleteLater, so the rows are walked."""
        head = [b for b in (v.btn_create, v.btn_read) if not b.isHidden()]
        rows = [w for r in v.list.rows() for w in r.suffix if isinstance(w, QPushButton)]
        return head + rows

    def test_neither_tool_one_line_no_buttons(self):
        v = self.view(S.Setup(), S.Listing(), ready=True)
        text = " ".join(v.situation())
        self.assertIn("neither Snapper nor Timeshift is installed", text)
        self.assertNotIn("install", text.replace("installed", ""))
        self.assertEqual(self.buttons(v), [])
        self.assertEqual(v.list.rows(), [])

    def test_tool_without_snapshots_reads_differently_from_no_tool(self):
        v = self.view(S.Setup(snapper=True, configs=["root"]), S.Listing(tool="snapper"),
                      ready=True)
        rows = v.list.rows()
        self.assertEqual(len(rows), 1)
        self.assertIn("Snapper is installed and has no snapshots yet", rows[0].title.text())
        self.assertNotIn("neither", " ".join(v.situation()))

    def test_list_for_root_with_the_helper_offers_the_read_button(self):
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", needs_root=True), ready=True)
        text = " ".join(v.situation())
        self.assertIn("ALLOW_USERS", text)
        self.assertIn("asks for your password; reads in the next few minutes need none", text)
        self.assertIn("Taking and deleting go through the helper too and ask every time", text)
        self.assertEqual(v.btn_read.text(), "Read snapshots")
        self.assertFalse(v.btn_read.isHidden())
        self.assertFalse(v.btn_create.isHidden())
        self.assertEqual(v.list.rows(), [])

    def test_list_for_root_without_the_helper_reads_and_shows_no_buttons(self):
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", needs_root=True), ready=False)
        text = " ".join(v.situation())
        self.assertIn("root helper", text)
        self.assertIn("not installed", text)
        self.assertEqual(self.buttons(v), [])

    @staticmethod
    def shown(v):
        return [r for r in v.list.rows() if not r.isHidden()]

    def test_plain_list_without_the_helper_shows_rows_and_no_delete(self):
        listing = S.Listing(tool="snapper",
                            snapshots=S.parse("snapper", [("root", SNAPPER_JSON)]))
        v = self.view(S.Setup(snapper=True, configs=["root"]), listing, ready=False)
        rows = self.shown(v)
        self.assertEqual(len(rows), 7)
        self.assertEqual(len(v.list.rows()), 9)      # the pair's two halves are there, hidden
        self.assertTrue(rows[1].title.text().endswith("ArchPM"), rows[1].title.text())
        self.assertIn("pacman", rows[4].title.text())
        self.assertEqual([b.text() for b in self.buttons(v)], ["Refresh"])
        text = " ".join(v.situation())
        self.assertIn("need the root helper", text)
        self.assertIn("Restoring is not done here", text)
        self.assertIn("A pacman transaction is one row", text)

    def test_groups_in_order_with_counts_and_yours_on_top(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", snapshots=rows), ready=True)
        shown = self.shown(v)
        headers = [r for r in shown if r.property("header")]
        self.assertEqual([h.title.text() for h in headers],
                         ["Taken by you (2)", "Taken by pacman (1)", "Taken on a timer (1)"])
        self.assertIn("1 row, 2 snapshots", headers[1].toolTip())
        self.assertTrue(shown[1].title.text().endswith("ArchPM"))
        self.assertTrue(shown[2].title.text().endswith("by hand"))
        self.assertTrue(shown[4].title.text().endswith("  ·  pacman"))
        self.assertTrue(shown[6].title.text().endswith("timeline"))
        # the pacman group sits between yours and the timer's even when yours is empty
        v._show(S.Listing(tool="snapper",
                          snapshots=[s for s in rows if s.origin not in (S.ARCHPM, S.BY_HAND)]))
        QTest.qWait(10)
        self.assertEqual([h.title.text() for h in self.shown(v) if h.property("header")],
                         ["Taken by pacman (1)", "Taken on a timer (1)"])

    def test_the_pair_row_carries_both_numbers_and_opens_on_a_click(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", snapshots=rows), ready=True)
        pair = self.shown(v)[4]
        self.assertTrue(pair.property("activatable"))
        self.assertEqual(pair.subtitle.text(), "pacman -U archpm-0.2.36-1-any.pkg.tar.zst")
        nums = [w.text() for w in pair.suffix if isinstance(w, QLabel)]
        self.assertIn("#264 · #265", nums)
        self.assertFalse(any(isinstance(w, QPushButton) for w in pair.suffix))
        self.assertEqual(len(self.shown(v)), 7)
        pair.activated.emit()
        shown = self.shown(v)
        self.assertEqual(len(shown), 9)
        self.assertIn("pacman, after", shown[5].title.text())
        self.assertIn("pacman, before", shown[6].title.text())
        self.assertTrue(all(any(isinstance(w, QPushButton) for w in r.suffix)
                            for r in shown[5:7]))
        self.assertTrue(pair.accessibleName().endswith("open"))
        # a refresh keeps it open; a second click closes it
        v._show(S.Listing(tool="snapper", snapshots=rows))
        QTest.qWait(10)
        self.assertEqual(len(self.shown(v)), 9)
        self.shown(v)[4].activated.emit()
        self.assertEqual(len(self.shown(v)), 7)

    def test_a_half_on_its_own_is_a_plain_row(self):
        rows = [s for s in S.parse("snapper", [("root", SNAPPER_JSON)]) if s.id != "265"]
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", snapshots=rows), ready=True)
        self.assertEqual(len(v.list.rows()), len(self.shown(v)))
        half = self.shown(v)[4]
        self.assertIn("pacman, before", half.title.text())
        self.assertFalse(half.property("activatable"))
        self.assertNotIn("A pacman transaction is one row", " ".join(v.situation()))

    def test_with_the_helper_every_row_has_delete_but_the_last_one(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", snapshots=rows), ready=True)
        deletes = [b for b in self.buttons(v) if b.text() == "Delete…"]
        self.assertEqual(len(deletes), 5)
        self.assertTrue(all(b.isEnabled() for b in deletes))
        v._show(S.Listing(tool="snapper", snapshots=rows[:1]))
        QTest.qWait(10)
        deletes = [b for b in self.buttons(v) if b.text() == "Delete…"]
        self.assertEqual(len(deletes), 1)
        self.assertFalse(deletes[0].isEnabled())
        self.assertIn("last snapshot stays", deletes[0].toolTip())

    # -- the helper route and what a fault does --------------------------------
    def helper_reply(self, v, result, pending=("list",)):
        """The helper answered: its result as the wrapper hands it over
        (the JSON line and pkexec's exit codes are the client's, in
        test_root_client), with the call's time."""
        v._pending = pending
        v._helper_done(result, 13.0)

    def test_read_snapshots_goes_through_the_helper_not_the_plain_read_again(self):
        """Until 0.2.41 the button repeated the refused plain read: no
        helper call, no error, no rows."""
        from archpm.ui import snapshots as view
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", needs_root=True), ready=True)
        del v.read                                 # the real one, not the test stub
        calls, threads = [], []
        v._run_helper = lambda pending, *args: calls.append((pending, args))
        real_read = view._read_plain
        view._read_plain = lambda: threads.append("plain read") or real_read()
        self.addCleanup(setattr, view, "_read_plain", real_read)
        v.btn_read.click()
        self.assertEqual(calls, [(("list",), ("snapshots-list",))])
        self.assertEqual(threads, [])
        self.assertEqual(v.lbl_state.text(), "reading as root…")

    def test_the_helper_reply_becomes_rows(self):
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", needs_root=True), ready=True)
        self.helper_reply(v, {"tool": "snapper", "outputs": [["root", SNAPPER_JSON]],
                              "took_ms": 13.0})
        self.assertTrue(v.listing.as_root)
        self.assertEqual(len(v.listing.snapshots), 5)
        self.assertEqual(len(self.shown(v)), 7)
        self.assertIn("as root", v.lbl_state.text())
        self.assertEqual(v.btn_read.text(), "Refresh")

    def test_a_fault_between_the_reply_and_the_list_is_shown(self):
        """The process list's rule: a fault of our own lands where the user
        looks, never in a traceback on stderr. Here the parser is made to
        raise something that is not an ActionError."""
        from archpm.ui import snapshots as view
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", needs_root=True), ready=True)
        real = view.snapshots.from_helper

        def broken(result):
            raise ValueError("a shape the parser did not expect")
        view.snapshots.from_helper = broken
        self.addCleanup(setattr, view.snapshots, "from_helper", real)
        self.helper_reply(v, {"tool": "snapper", "outputs": [["root", SNAPPER_JSON]]})
        self.assertEqual(v.lbl_state.text(),
                         "Not read: ValueError: a shape the parser did not expect")
        self.assertEqual(self.shown(v), [])
        self.assertTrue(v.btn_read.isEnabled())
        # and the same for a fault while the rows are built
        view.snapshots.from_helper = real
        real_fill = v._fill
        v._fill = lambda: (_ for _ in ()).throw(KeyError("origin"))
        self.helper_reply(v, {"tool": "snapper", "outputs": [["root", SNAPPER_JSON]]})
        self.assertEqual(v.lbl_state.text(), "Not shown: KeyError: 'origin'")
        v._fill = real_fill

    def test_a_fault_in_create_or_delete_goes_to_the_status_bar(self):
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", needs_root=True), ready=True)
        said = []
        v.status.connect(said.append)
        v._pending = ("create",)
        v._helper_failed("helper returned exit code 0")
        self.assertEqual(said, ["Not done: helper returned exit code 0"])
        v._after_change = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        self.helper_reply(v, {"id": "270"}, pending=("create",))
        self.assertEqual(said[-2:], ["Snapshot #270 taken", "Not done: RuntimeError: boom"])

    def test_a_plain_read_that_raises_reports_instead_of_hanging(self):
        from archpm.ui import snapshots as view
        real = view.snapshots.detect

        def broken():
            raise OSError("snapper exploded")
        view.snapshots.detect = broken
        self.addCleanup(setattr, view.snapshots, "detect", real)
        _setup, listing = view._read_plain()
        self.assertEqual(listing.error, "Not read: OSError: snapper exploded")

    def test_confirmation_says_what_is_lost_and_what_remains(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        v = self.view(S.Setup(snapper=True, configs=["root"]),
                      S.Listing(tool="snapper", snapshots=rows), ready=True)
        oldest = v.confirmation(rows[-1])
        self.assertIn("Delete #150?", oldest)
        self.assertIn("This is the oldest snapshot.", oldest)
        self.assertIn("Left after it: 4 snapshots", oldest)
        self.assertIn("This cannot be undone.", oldest)
        newest = v.confirmation(rows[0])
        self.assertIn("This is the newest snapshot.", newest)
        pre = v.confirmation(next(s for s in rows if s.id == "264"))
        self.assertIn("Its pair #265 (the after half) stays", pre)
        self.assertNotIn("oldest", pre)

    def test_sizes_line_when_snapper_reports_none(self):
        rows = S.parse("snapper", [("root", SNAPPER_JSON)])
        for s in rows:
            s.size = None
        v = self.view(S.Setup(snapper=True, configs=["root"], limine_entries=8),
                      S.Listing(tool="snapper", snapshots=rows), ready=True)
        text = " ".join(v.situation())
        self.assertIn("btrfs quota", text)
        self.assertIn("newest 8 snapshots", text)


if __name__ == "__main__":
    unittest.main()
