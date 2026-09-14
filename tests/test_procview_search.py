"""Searching in Tree mode: the way to a match opens, and closes again afterwards.

Needs PySide6 and runs offscreen; skipped where PySide6 is missing. QSettings
is redirected to a temporary directory so the test never touches your config.
"""
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

from archpm.model import ProcSample, Snapshot, SystemSample


def proc(pid, ppid, name):
    return ProcSample(pid=pid, ppid=ppid, name=name, username="alex", owned=True,
                      cmdline=f"/usr/bin/{name}", program=True)


PROCS = [
    proc(1, 0, "systemd"),
    proc(1000, 1, "systemd"),      # systemd --user
    proc(2000, 1000, "steam"),
    proc(3000, 2000, "reaper"),
    proc(4000, 3000, "game.exe"),
    proc(5000, 1000, "firefox"),
]


@unittest.skipUnless(QApplication, "PySide6 not installed")
class TreeSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
            QSettings.setPath(fmt, QSettings.Scope.UserScope, cls.tmp.name)
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from archpm.actions import UserBackend
        from archpm.ui.procview import ProcessView
        self.view = ProcessView(8, UserBackend())
        self.view.cb_tree.setChecked(True)
        self.view.cb_all.setChecked(True)
        self.view.update_view(Snapshot(system=SystemSample(), procs=PROCS))

    def expanded(self, pid) -> bool:
        index = self.view.proxy.mapFromSource(self.view.model.index_for_pid(pid))
        self.assertTrue(index.isValid(), f"pid {pid} not visible")
        return self.view.table.isExpanded(index)

    def visible(self, pid) -> bool:
        return self.view.proxy.mapFromSource(self.view.model.index_for_pid(pid)).isValid()

    def test_pid_1_and_the_user_manager_are_not_containers(self):
        steam = self.view.proxy.mapFromSource(self.view.model.index_for_pid(2000))
        self.assertFalse(steam.parent().isValid(), "steam sits at the root")
        self.assertFalse(self.view.model.has_children(1))
        self.assertFalse(self.view.model.has_children(1000))
        self.assertTrue(self.view.model.has_children(2000))

    def test_nothing_is_expanded_on_startup(self):
        self.assertFalse(self.expanded(2000))
        self.assertFalse(self.expanded(3000))
        self.assertEqual(self.view.model.expanded_pids(), set())

    def test_a_search_opens_the_way_to_the_match_and_hides_the_rest(self):
        self.view.search.setText("game")
        self.assertTrue(self.visible(4000))
        self.assertTrue(self.expanded(2000))
        self.assertTrue(self.expanded(3000))
        self.assertFalse(self.visible(5000), "firefox does not match and is not an ancestor")

    def test_clearing_the_search_puts_the_tree_back(self):
        self.view.search.setText("game")
        self.view.search.setText("")
        self.assertTrue(self.visible(5000))
        self.assertFalse(self.expanded(2000))
        self.assertFalse(self.expanded(3000))
        self.assertEqual(self.view.model.expanded_pids(), set())

    def test_a_branch_opened_by_hand_stays_open_after_the_search(self):
        idx = self.view.proxy.mapFromSource(self.view.model.index_for_pid(2000))
        self.view.table.expand(idx)
        self.view.search.setText("game")
        self.assertTrue(self.expanded(3000), "opened while searching, it is on the way")
        self.view.search.setText("")
        self.assertTrue(self.expanded(2000), "back to how the user left it")
        self.assertFalse(self.expanded(3000))

    def test_a_match_that_appears_during_the_search_is_opened_too(self):
        self.view.search.setText("late")
        late = PROCS + [proc(6000, 2000, "launcher"), proc(7000, 6000, "latecomer")]
        self.view.update_view(Snapshot(system=SystemSample(), procs=late))
        self.assertTrue(self.visible(7000))
        self.assertTrue(self.expanded(2000))
        self.assertTrue(self.expanded(6000))

    def test_ancestors_of_a_match_are_faint_and_the_match_is_not(self):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor
        from archpm.ui import theme
        self.view.search.setText("game")

        def colour(pid):
            index = self.view.proxy.mapFromSource(self.view.model.index_for_pid(pid))
            return self.view.proxy.data(index, Qt.ItemDataRole.ForegroundRole)
        for ancestor in (2000, 3000):
            self.assertEqual(colour(ancestor), QColor(theme.FAINT), ancestor)
        self.assertFalse(self.visible(1000), "no longer an ancestor, so it is filtered out")
        self.assertNotEqual(colour(4000), QColor(theme.FAINT), "the match keeps its colour")
        self.view.search.setText("")
        self.assertNotEqual(colour(2000), QColor(theme.FAINT), "no search, no dimming")

    def test_no_settings_written_outside_the_temporary_directory(self):
        real = os.path.expanduser("~/.config/archpm")
        before = os.path.getmtime(real) if os.path.exists(real) else None
        self.view.cb_tree.setChecked(False)
        self.view.cb_tree.setChecked(True)
        after = os.path.getmtime(real) if os.path.exists(real) else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
