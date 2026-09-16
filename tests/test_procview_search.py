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
        self.view.show()            # a never-shown widget counts as hidden and defers updates
        self.view.set_mode("tree")
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
        self.view.set_mode("flat")
        self.view.set_mode("tree")
        after = os.path.getmtime(real) if os.path.exists(real) else None
        self.assertEqual(before, after)


SLICE = "/user.slice/user-1000.slice/user@1000.service/app.slice/"


def app(pid, ppid, name, unit, cpu=0.0, rss=0, app_name="", cmdline=""):
    return ProcSample(pid=pid, ppid=ppid, name=name, username="alex", owned=True, program=True,
                      cmdline=cmdline or f"/usr/bin/{name}", cgroup=SLICE + unit,
                      cpu_percent=cpu, mem_rss=rss, num_threads=1, app_name=app_name)


GROUPED = [
    app(100, 1, "brave", "app-brave@1.service", cpu=5, rss=300, app_name="Brave"),
    app(101, 100, "brave", "app-brave@1.service", cpu=1, rss=100),
    app(102, 101, "brave", "app-brave@1.service", cpu=20, rss=600,
        cmdline="/opt/brave/brave --type=renderer"),
    app(200, 1, "steam", "app-steam@2.service", cpu=2, rss=200, app_name="Steam"),
    app(201, 200, "steamwebhelper", "app-steam@2.service", cpu=9, rss=400),
    app(300, 1, "konsole", "app-org.kde.konsole-300.scope", cpu=50, rss=50, app_name="Konsole"),
]


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Grouped(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TreeSearch.setUpClass()

    def setUp(self):
        from archpm.actions import UserBackend
        from archpm.ui.procview import ProcessView
        self.view = ProcessView(8, UserBackend())
        self.view.show()            # a never-shown widget counts as hidden and defers updates
        self.view.set_mode("grouped")
        self.view.update_view(Snapshot(system=SystemSample(), procs=GROUPED))
        self.model, self.proxy = self.view.model, self.view.proxy

    def roots(self):
        from archpm.ui.proc_model import PID_ROLE
        return [self.proxy.index(r, 0).data(PID_ROLE) for r in range(self.proxy.rowCount())]

    def test_grouped_is_the_default_and_is_remembered(self):
        self.assertEqual(self.view.combo_mode.currentData(), "grouped")
        self.view.set_mode("flat")
        self.assertEqual(self.view.settings.value("view_mode"), "flat")

    def test_one_row_per_application_and_singletons_stay_themselves(self):
        roots = self.roots()
        self.assertEqual(len(roots), 3, roots)
        self.assertIn(300, roots, "konsole alone is its own row")
        groups = [pid for pid in roots if pid < 0]
        self.assertEqual(len(groups), 2, "brave and steam")

    def test_group_row_carries_the_sums_and_the_count(self):
        from archpm.ui.proc_model import COL_CPU, COL_MEM, COL_PID
        brave = next(n for n in self.model._nodes.values()
                     if n.proc.members and n.proc.name == "brave").proc
        self.assertEqual((brave.members, brave.cpu_percent, brave.mem_rss), (3, 26.0, 1000))
        idx = self.model.index_for_pid(brave.pid)
        self.assertEqual(self.model.data(idx.siblingAtColumn(COL_PID)), "", "no pid on a group row")
        self.assertEqual(self.model.data(idx.siblingAtColumn(COL_CPU)), "26.0")
        from PySide6.QtCore import Qt
        tip = self.model.data(idx.siblingAtColumn(COL_MEM), Qt.ItemDataRole.ToolTipRole)
        self.assertIn("ten seconds old", tip)
        self.assertIn("RSS instead", tip, "no member has PSS in this fixture")

    def test_sorting_orders_groups_by_their_aggregate(self):
        from PySide6.QtCore import Qt

        from archpm.ui.proc_model import COL_CPU, COL_NAME, PID_ROLE
        self.view.table.sortByColumn(COL_CPU, Qt.SortOrder.DescendingOrder)
        names = [self.proxy.index(r, COL_NAME).data() for r in range(self.proxy.rowCount())]
        self.assertEqual(names, ["Konsole", "Brave", "Steam"], "50 > 26 > 11")
        brave = self.proxy.index(1, 0)
        members = [self.proxy.index(r, 0, brave).data(PID_ROLE)
                   for r in range(self.proxy.rowCount(brave))]
        self.assertEqual(members, [102, 100, 101], "within the group, by their own CPU")

    def test_search_matches_a_member_and_keeps_its_group_visible(self):
        self.view.search.setText("renderer")
        roots = self.roots()
        self.assertEqual(len(roots), 1)
        brave = self.proxy.index(0, 0)
        self.assertEqual(self.proxy.rowCount(brave), 1)
        self.assertTrue(self.view.table.isExpanded(brave), "opened so the match shows")

    def test_a_group_row_stands_for_every_member_when_signalled(self):
        from archpm import signalguard
        from archpm.ui.proc_model import COL_NAME
        gid = next(pid for pid in self.roots() if pid < 0
                   and self.model.index_for_pid(pid).siblingAtColumn(COL_NAME).data() == "Brave")
        procs = self.model.procs_under(gid)
        self.assertEqual(sorted(p.pid for p in procs), [100, 101, 102])
        v = signalguard.check(procs, "TERM", tree=True, always_ask=True, list_all=True,
                              self_pid=4242, above={4242}, leaders=set())
        self.assertTrue(v.confirm)
        for pid in (100, 101, 102):
            self.assertIn(f"({pid})", v.text)
        self.assertEqual(v.title, "Ask Brave and 2 more to quit?")

    def test_every_member_shows_under_its_group_even_a_quiet_helper(self):
        helper = app(103, 100, "brave-helper", "app-brave@1.service")
        helper.program = False           # no menu entry, idle: hidden as a root row
        self.view.update_view(Snapshot(system=SystemSample(), procs=GROUPED + [helper]))
        from archpm.ui.proc_model import COL_NAME, PID_ROLE
        brave = next(self.proxy.index(r, 0) for r in range(self.proxy.rowCount())
                     if self.proxy.index(r, COL_NAME).data() == "Brave")
        members = {self.proxy.index(r, 0, brave).data(PID_ROLE)
                   for r in range(self.proxy.rowCount(brave))}
        self.assertEqual(members, {100, 101, 102, 103})
        self.view.search.setText("renderer")
        members = {self.proxy.index(r, 0, brave).data(PID_ROLE)
                   for r in range(self.proxy.rowCount(brave))}
        self.assertEqual(members, {102}, "the search still filters members")

    def test_a_process_that_gets_company_moves_under_a_new_group(self):
        procs = GROUPED + [app(301, 300, "konsole-helper", "app-org.kde.konsole-300.scope")]
        self.view.update_view(Snapshot(system=SystemSample(), procs=procs))
        self.assertTrue(self.model.index_for_pid(300).parent().isValid(),
                        "konsole now sits in a group")
        self.view.update_view(Snapshot(system=SystemSample(), procs=GROUPED))
        self.assertFalse(self.model.index_for_pid(300).parent().isValid(), "and is alone again")


@unittest.skipUnless(QApplication, "PySide6 not installed")
class HiddenPage(unittest.TestCase):
    """While another page is on screen the list keeps the sample but does not
    rebuild its rows; the newest sample is applied when it comes back."""

    @classmethod
    def setUpClass(cls):
        TreeSearch.setUpClass()

    def test_updates_are_deferred_while_hidden_and_applied_on_show(self):
        from PySide6.QtWidgets import QLabel, QStackedWidget

        from archpm.actions import UserBackend
        from archpm.ui.procview import ProcessView
        stack = QStackedWidget()
        other = QLabel("other page")
        view = ProcessView(8, UserBackend())
        view.set_mode("flat")
        view.cb_all.setChecked(True)
        stack.addWidget(other)
        stack.addWidget(view)
        stack.setCurrentWidget(other)
        stack.show()
        TreeSearch.app.processEvents()
        self.assertTrue(view.isHidden())
        view.update_view(Snapshot(system=SystemSample(), procs=PROCS))
        self.assertEqual(view.model.rowCount(), 0, "no rows built while hidden")
        self.assertEqual(len(view.model._last), len(PROCS),
                         "the sample is kept for the game-end path")
        newer = PROCS + [proc(9999, 1, "late")]
        view.update_view(Snapshot(system=SystemSample(), procs=newer))
        stack.setCurrentWidget(view)
        TreeSearch.app.processEvents()
        # with every process shown the root rows are the three sections, so
        # count the process rows themselves
        def rows():
            return len([pid for pid in view.model.pids() if pid > 0])
        self.assertEqual(rows(), len(newer), "the newest sample, applied on show")
        view.update_view(Snapshot(system=SystemSample(), procs=PROCS))
        self.assertEqual(rows(), len(PROCS), "visible again: updates apply directly")


@unittest.skipUnless(QApplication, "PySide6 not installed")
class Tooltip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TreeSearch.setUpClass()

    def test_long_command_line_is_wrapped_and_cut(self):
        from PySide6.QtCore import Qt

        from archpm.ui.proc_model import COL_CMD, COL_NAME, TIP_WIDTH, ProcModel
        long_cmd = "/usr/lib/steam/steamwebhelper " + " ".join(
            f"--flag-{i}=value{i}" for i in range(120))
        self.assertGreater(len(long_cmd), 1500)
        m = ProcModel(8)
        m.set_mode("flat")
        m.update([ProcSample(pid=7, name="steamwebhelper", cmdline=long_cmd, owned=True)])
        for col in (COL_NAME, COL_CMD):
            tip = m.data(m.index(0, col), Qt.ItemDataRole.ToolTipRole)
            self.assertLessEqual(max(len(line) for line in tip.splitlines()), TIP_WIDTH)
            self.assertIn("…", tip, "cut short")
            self.assertLess(len(tip), 400)
        self.assertEqual(m.data(m.index(0, COL_CMD)), long_cmd, "the column keeps it all")


if __name__ == "__main__":
    unittest.main()
