"""The Cleanup page reads every size without root and asks for the password
only when a root item is removed, never at page entry. Needs PySide6 and
runs offscreen; skipped where PySide6 is missing."""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:                       # pragma: no cover
    QApplication = None

from archpm.cleanup import CleanupItem


@unittest.skipUnless(QApplication, "PySide6 not installed")
class NoPasswordAtEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def view(self):
        from archpm.root.client import RootClient
        from archpm.ui.cleanup import CleanupView
        v = CleanupView(RootClient())
        v.scan = lambda: None            # no real scan in a test
        return v

    def test_first_visit_starts_no_pkexec(self):
        v = self.view()
        v._first_visit = lambda: True    # the user pressed "I understand"
        v._first_visit_flow()
        self.assertTrue(v._acknowledged)
        self.assertIsNone(v._proc, "the scan needs no root, so no pkexec at entry")
        self.assertFalse(hasattr(v, "_authenticate"), "no pre-authentication exists any more")

    def test_root_rows_say_when_the_password_comes(self):
        v = self.view()
        pacman = CleanupItem(id="pacman", name="Package cache", description="", size=10 << 20,
                             needs_root=True, helper_item="pacman")
        text, _ = v._note_for(pacman)
        self.assertIn("asks for your password on Remove", text)
        missing = CleanupItem(id="pacman", name="Package cache", description="", size=0,
                              needs_root=True, note="install pacman-contrib")
        self.assertIn("install pacman-contrib", v._note_for(missing)[0])

    def test_the_page_says_which_parts_need_root(self):
        from PySide6.QtWidgets import QLabel
        v = self.view()
        texts = " ".join(lbl.text() for lbl in v.findChildren(QLabel))
        self.assertIn("read without root", texts)
        self.assertIn("asked when you press Remove", texts)

    def test_a_root_row_is_tickable_before_any_password_when_the_helper_is_there(self):
        from archpm.root.client import check
        if not check().ready:
            self.skipTest("root helper not installed here")
        v = self.view()
        v.items = [CleanupItem(id="journal", name="System logs", description="", size=5 << 20,
                               needs_root=True, helper_item="journal")]
        v._fill()
        box = v._checks[0]
        self.assertTrue(box.isEnabled())
        box.toggle()
        self.assertEqual([i.id for i in v._selected()], ["journal"])
        self.assertFalse(hasattr(v.client, "authenticated"), "the client keeps no lock state")


if __name__ == "__main__":
    unittest.main()
