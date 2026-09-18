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
    from PySide6.QtWidgets import QApplication, QPushButton
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
        self.assertIn("asks for your password once", text)
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

    def test_plain_list_without_the_helper_shows_rows_and_no_delete(self):
        listing = S.Listing(tool="snapper",
                            snapshots=S.parse("snapper", [("root", SNAPPER_JSON)]))
        v = self.view(S.Setup(snapper=True, configs=["root"]), listing, ready=False)
        rows = v.list.rows()
        self.assertEqual(len(rows), 5)
        self.assertTrue(rows[0].title.text().endswith("ArchPM"), rows[0].title.text())
        self.assertIn("pacman, after", rows[1].title.text())
        self.assertEqual([b.text() for b in self.buttons(v)], ["Refresh"])
        text = " ".join(v.situation())
        self.assertIn("need the root helper", text)
        self.assertIn("Restoring is not done here", text)

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
